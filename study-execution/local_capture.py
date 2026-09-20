"""Instrumented backend for the unchanged logitpick engine; no import-time calls."""
import time
import math
import urllib.request
from adapters import MODELS,LOCAL_DIGEST,canonical,strict_json
from transport import NoRedirect
from logitpick.ollama import NextToken,TokenAlt,TOP_K


class RecordingBackend:
    def __init__(self,record,*,authorized=False,opener=None,clock=time.monotonic):
        if authorized is not True:raise PermissionError('explicit local-model approval required')
        self.record=record;self.clock=clock;self.started=clock();self.calls=0
        self.opener=opener or urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())

    def _read(self,path,body=None,timeout=10):
        req=urllib.request.Request('http://127.0.0.1:11434'+path,
            data=canonical(body).encode() if body is not None else None,
            headers={'Content-Type':'application/json'})
        with self.opener.open(req,timeout=timeout) as response:
            raw=response.read(1048577)
            if len(raw)>1048576:raise ValueError('local response exceeds 1 MiB')
            return raw.decode('utf8')

    def next_token(self,prompt,*,model):
        if model!=MODELS['local']:raise ValueError('local model differs from declared arm')
        remaining=3600-(self.clock()-self.started)
        if self.calls>=290 or remaining<=20:raise ValueError('local run resource envelope exhausted')
        started=self.clock()
        tags=strict_json(self._read('/api/tags'))
        models=[m for m in tags.get('models',[]) if m.get('name')==model]
        if len(models)!=1 or models[0].get('digest')!=LOCAL_DIGEST:
            raise ValueError('installed model digest changed or missing')
        running=strict_json(self._read('/api/ps')).get('models',[])
        if any(m.get('name')!=model for m in running):
            raise ValueError('another model is loaded; do not evict it')
        if any(m.get('digest')!=LOCAL_DIGEST for m in running):raise ValueError('loaded model digest mismatch')
        cold=not running
        body={'model':model,'prompt':prompt,'stream':False,'logprobs':True,'top_logprobs':TOP_K,
              'keep_alive':'5m','options':{'num_predict':1,'temperature':0,'seed':1}}
        self.calls+=1
        self.record({'event':'local_request','call':self.calls,'cold_observed':cold,
            'model_digest':LOCAL_DIGEST,'body':body})
        # Bound the generation by remaining approved time. No retries or downloads.
        remaining=3600-(self.clock()-self.started)
        if remaining<=0:raise ValueError('deadline reached before dispatch')
        raw=self._read('/api/generate',body,timeout=min(180,remaining))
        data=strict_json(raw)
        self.record({'event':'local_response','call':self.calls,'body':raw,
            'cold_observed':cold,'total_elapsed_ms':round((self.clock()-started)*1000,3)})
        if data.get('model')!=model or data.get('done') is not True:
            raise ValueError('local model mismatch or incomplete response')
        generated=data.get('response');rows=data.get('logprobs')
        if not isinstance(generated,str) or not isinstance(rows,list) or not rows:
            raise ValueError('missing local response/logprobs')
        top=rows[0].get('top_logprobs')
        if not isinstance(top,list) or not top:raise ValueError('missing top logprobs')
        alts=[]
        for item in top:
            token=item.get('token');lp=item.get('logprob')
            if not isinstance(token,str) or type(lp) not in (int,float) or not math.isfinite(lp):
                raise ValueError('invalid local alternative')
            alts.append(TokenAlt(token,float(lp)))
        for name in ('prompt_eval_count','eval_count','load_duration','prompt_eval_duration','eval_duration','total_duration'):
            value=data.get(name)
            if type(value) is not int or value<0:raise ValueError('missing local telemetry: '+name)
        self.record({'event':'local_usage','call':self.calls,'cold_observed':cold,
            **{name:data[name] for name in ('prompt_eval_count','eval_count','load_duration',
                                          'prompt_eval_duration','eval_duration','total_duration')}})
        return NextToken(generated,tuple(alts),data['eval_count'],data['eval_duration'])
