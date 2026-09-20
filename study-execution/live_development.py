"""Explicitly authorized synthetic development CLI; defaults to plan-only."""
import argparse
import ctypes
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from adapters import ROOT, MODELS, LOCAL_DIGEST, canonical, strict_json
from budget import CampaignBudget
from development import run, load_development
from local_resources import LocalBudget, ResourceGuard, probe_nvidia_smi
from locks import write_once
from transport import CloudTransport


def memory_available_mb():
    class Memory(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(n,ctypes.c_ulonglong) for n in
            ('total','available','page_total','page_available','virtual_total','virtual_available','extended')]
    if os.name!='nt':
        raise RuntimeError('Windows memory resource probe unavailable')
    info=Memory(); info.length=ctypes.sizeof(info)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(info)):
        raise RuntimeError('memory resource probe unavailable')
    return info.available//1048576


def cpu_times():
    """Windows system totals, including idle in kernel; no process inspection."""
    if os.name != 'nt':
        raise RuntimeError('Windows CPU resource probe unavailable')
    class FileTime(ctypes.Structure):
        _fields_ = [('low', ctypes.c_uint32), ('high', ctypes.c_uint32)]
    idle, kernel, user = FileTime(), FileTime(), FileTime()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        raise RuntimeError('CPU resource probe unavailable')
    return tuple((v.high << 32) + v.low for v in (idle, kernel, user))


def cpu_percent(previous, current):
    if len(previous) != 3 or len(current) != 3 or any(type(v) is not int or v < 0 for v in (*previous, *current)):
        raise RuntimeError('invalid CPU resource measurements')
    idle, kernel, user = [b-a for a,b in zip(previous,current)]
    total = kernel + user
    if min(idle,kernel,user) < 0 or total <= 0 or idle > total:
        raise RuntimeError('CPU resource measurements did not advance consistently')
    return 100 * (1 - idle / total)


def bounded_gpu_probe(timeout):
    def bounded_run(*args, **kwargs):
        kwargs['timeout'] = min(timeout, kwargs.get('timeout', timeout))
        return subprocess.run(*args, **kwargs)
    return probe_nvidia_smi(run=bounded_run)


class LocalTransport:
    """One owned child per request, hard elapsed deadline, no persisted model load.

    Warm cache is not assumed: keep_alive=0 releases this run's model after each call.
    Shared local allowance charges child startup, load, inference and teardown.
    """
    def __init__(self,budget,record,*,guard=None,clock=time.monotonic,sleep=time.sleep,
                 memory_probe=memory_available_mb,cpu_probe=cpu_times,gpu_probe=bounded_gpu_probe,
                 popen=subprocess.Popen):
        self.budget=budget;self.record=record;self.calls=0
        self.guard=guard or ResourceGuard()
        self.clock=clock;self.sleep=sleep;self.memory_probe=memory_probe
        self.cpu_probe=cpu_probe;self.gpu_probe=gpu_probe;self.popen=popen

    def _record(self,event):
        with self.record.open('a',encoding='utf8') as f:
            f.write(canonical(event)+'\n');f.flush();os.fsync(f.fileno())

    def _memory(self,minimum):
        available=self.memory_probe()
        if type(available) not in (int,float) or not math.isfinite(available) or available<minimum:
            raise RuntimeError('system memory unavailable or below local execution policy')
        return available

    def __call__(self,body):
        # Resource failures must remain visible even when no model is dispatched.
        try:
            resources=self.guard.check();available=self._memory(3072)
            previous_cpu=self.cpu_probe();self.sleep(.2);current_cpu=self.cpu_probe()
            initial_cpu=cpu_percent(previous_cpu,current_cpu)
            if initial_cpu>95:raise RuntimeError('CPU contention before local dispatch')
            previous_cpu=current_cpu
        except Exception as exc:
            self._record({'event':'local_blocked','reason_type':type(exc).__name__,
                          'telemetry_complete':False,'dispatched':False})
            raise
        self.calls+=1
        key=str(self.record)+':'+str(self.calls)
        timeout=min(60,float(self.budget.remaining))
        if timeout<5: raise RuntimeError('local allowance exhausted')
        request=canonical(body)
        if len(request.encode('utf8'))>1048576:raise ValueError('local request exceeds 1 MiB')
        request_path=self.record.parent/('local-worker-'+str(self.calls)+'.request.json')
        events_path=self.record.parent/('local-worker-'+str(self.calls)+'.events.jsonl')
        capture_path=self.record.parent/('local-worker-'+str(self.calls)+'.json')
        error_path=self.record.parent/('local-worker-'+str(self.calls)+'.stderr')
        write_once(request_path,body)
        self.budget.reserve(key,timeout)
        process=None;started=self.clock();capture=None;errors=None;reason=None
        telemetry_complete=False;high_cpu_since=None;killed=False
        try:
            capture=capture_path.open('x',encoding='utf8');errors=error_path.open('x',encoding='utf8')
            self._record({'event':'local_resource_preflight','key':key,'gpu':resources,
                          'system_memory_available_mb':available,'cpu_utilization_percent':initial_cpu,
                          'reserved_seconds':timeout,'keep_alive':0})
            child_env={k:v for k,v in os.environ.items() if k.upper() in
                       {'SYSTEMROOT','WINDIR','TEMP','TMP','PATH','PATHEXT'}}
            process=self.popen([sys.executable,'-B','-s','-E',str(Path(__file__).with_name('local_worker.py')),
                               str(request_path),str(events_path)],
                stdin=subprocess.DEVNULL,stdout=capture,stderr=errors,text=True,env=child_env,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            while process.poll() is None:
                remaining=timeout-(self.clock()-started)
                if remaining<=1:
                    raise TimeoutError('owned local request exceeded hard deadline')
                available=self._memory(1536)
                current_cpu=self.cpu_probe();cpu=cpu_percent(previous_cpu,current_cpu);previous_cpu=current_cpu
                now=self.clock()
                if cpu>95:
                    if high_cpu_since is None:high_cpu_since=now
                    if now-high_cpu_since>=2:raise RuntimeError('sustained CPU contention during local request')
                else:high_cpu_since=None
                # Own inference may saturate compute; memory pressure is a stop signal.
                gpu=self.gpu_probe(min(.5,remaining-1))
                ResourceGuard(max_utilization_percent=100,min_free_mib=512,probe=lambda:gpu).check()
                self._record({'event':'local_resource_sample','key':key,'elapsed_seconds':self.clock()-started,
                              'gpu':gpu,'system_memory_available_mb':available,'cpu_utilization_percent':cpu})
                self.sleep(min(.2,max(0,timeout-(self.clock()-started)-1)))
            process.wait();capture.flush();errors.flush()
            if process.returncode:
                raise RuntimeError('owned local worker failed; no automatic retry')
            value=strict_json(capture_path.read_text(encoding='utf8'))
            usage=[e for e in value['records'] if e.get('event')=='local_usage']
            if len(usage)!=1:raise ValueError('one complete local usage record required')
            u=usage[0]
            for name in ('prompt_eval_count','eval_count','load_duration','prompt_eval_duration','eval_duration','total_duration'):
                if type(u.get(name)) is not int or u[name]<0:raise ValueError('missing or invalid local usage')
            if type(u.get('cold_observed')) is not bool:raise ValueError('cold observation missing')
            for event in value['records']:self._record({'key':key,**event})
            telemetry_complete=True
            measured={'input_tokens':u['prompt_eval_count'],'output_tokens':u['eval_count'],
                'load_duration_ns':u['load_duration'],'prompt_eval_duration_ns':u['prompt_eval_duration'],
                'eval_duration_ns':u['eval_duration'],'total_duration_ns':u['total_duration'],
                'cold_observed':u['cold_observed'],'reported_usd':None,'estimated_usd':None,
                'accounting_usd':'0','cost_scope':'cloud only; local electricity/hardware unmeasured'}
            return {'status':200,'body':canonical(value['response']),'usage':measured}
        except BaseException as exc:
            reason=type(exc).__name__
            raise
        finally:
            try:
                if process is not None and process.poll() is None:
                    killed=True;process.kill();process.wait(timeout=.5)
            finally:
                try:
                    if capture is not None:capture.close()
                    if errors is not None:errors.close()
                    self._record({'event':'local_outcome','key':key,'reason_type':reason,
                                  'telemetry_complete':telemetry_complete,'owned_worker_killed':killed,
                                  'server_completion_confirmed':telemetry_complete,
                                  'worker_events_path':events_path.name,
                                  'elapsed_seconds':self.clock()-started})
                finally:
                    if process is not None and not telemetry_complete:
                        # Killing an HTTP client does not prove server cancellation.
                        # Keep the full reservation and stop, even after worker failure.
                        self.budget.halt('local_server_completion_or_telemetry_unconfirmed')
                    else:self.budget.complete(key)


def credentials(path):
    """Read only the two allowlisted credentials, never log file contents."""
    names=('TYPESAFE_API_KEY','OPENROUTER_API_KEY')
    found={n:os.environ.get(n) for n in names}
    if path:
        for line in Path(path).read_text(encoding='utf8').splitlines():
            k,sep,v=line.partition('=');k=k.strip()
            if sep and k in names and not found[k]:
                found[k]=v.strip().strip('\"').strip("'")
    return found


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute',action='store_true')
    p.add_argument('--approval-reference')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--campaign',type=Path,required=True)
    p.add_argument('--local-budget',type=Path,required=True)
    p.add_argument('--create-budgets',action='store_true')
    p.add_argument('--credentials-file',type=Path)
    p.add_argument('--arms',nargs='+',choices=['local','jev','chat'],default=['local','jev','chat'])
    p.add_argument('--limit',type=int)
    p.add_argument('--trials',type=int,choices=[1,3],default=1)
    p.add_argument('--policy',choices=['all_cases','deterministic_first'],default='all_cases')
    p.add_argument('--resolved-models',type=Path)
    p.add_argument('--dataset',type=Path,help='Versioned development file; no calibration/test accepted')
    p.add_argument("--prompt-version",choices=["v1","v2"],default="v1")
    p.add_argument("--phase",choices=["development","calibration","test"],default="development")
    a=p.parse_args()
    if not a.execute:
        print(json.dumps({'mode':'plan-only','cloud_cap_usd':2,'local_cap_seconds':3600,
                          'arms':a.arms,'limit':a.limit,'calls':0}));return
    if not a.approval_reference:p.error('explicit approval reference required')
    if a.dataset:
        raw=a.dataset.read_bytes();cases=strict_json(raw.decode());dataset_hash=hashlib.sha256(raw).hexdigest()
    else:cases,dataset_hash=load_development()
    keys=credentials(a.credentials_file)
    by_arm={'jev':keys['TYPESAFE_API_KEY'],'chat':keys['OPENROUTER_API_KEY']}
    if any(not by_arm[x] for x in a.arms if x!='local'):
        p.error('required credentials missing; values withheld')
    models={arm:MODELS[arm] for arm in a.arms}
    if a.resolved_models:
        resolved=strict_json(a.resolved_models.read_text());models={arm:resolved[arm] for arm in a.arms}
    # Each ledger is created once and reused, including preflight, retries and iterations.
    with CampaignBudget(a.campaign,'2',create=a.create_budgets) as campaign, \
         LocalBudget(a.local_budget,3600,create=a.create_budgets) as local:
        transports={arm:CloudTransport(arm,by_arm[arm],authorized=True) for arm in a.arms if arm!='local'}
        if 'local' in a.arms:
            transports['local']=LocalTransport(local,a.output/'local-telemetry.jsonl')
        result=run(cases,a.output,transports,models,campaign,approved=True,
            dataset_hash=dataset_hash,secrets=tuple(keys.values()),limit=a.limit,trials=a.trials,policy=a.policy,
            prompt_version=a.prompt_version,phase=a.phase,
            resource_snapshot={'gpu':probe_nvidia_smi(),'system_memory_available_mb':memory_available_mb(),
                               'local_model_digest':LOCAL_DIGEST,'approval_reference':a.approval_reference})
        print(json.dumps({'complete':result['complete'],'stopped':result['stopped'],
            'observations':result['recorded_observations'],'cloud_reserved_usd':str(campaign.reserved),
            'local_charged_seconds':str(local.used),'output':str(a.output)}))


if __name__=='__main__':main()
