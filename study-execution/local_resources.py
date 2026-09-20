"""Durable aggregate local time accounting and read-only GPU contention probes.

No import-time probes, model calls, downloads, process termination, or retries.
The caller must enforce the reserved timeout and stop its own request on contention.
"""
import csv
import io
import json
import math
import os
import shutil
import subprocess
import time
from decimal import Decimal, InvalidOperation


class LocalBudgetExceeded(RuntimeError):
    pass


class ResourceContention(RuntimeError):
    pass


class ResourceProbeUnavailable(RuntimeError):
    pass


def _seconds(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError('seconds must be finite numeric values')
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('invalid seconds') from exc
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError('seconds must be finite and nonnegative')
    return result


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate ledger field')
        result[key] = value
    return result


def _strict_json(line):
    def bad(value):
        raise ValueError('nonfinite ledger value: ' + value)
    value = json.loads(line, object_pairs_hook=_pairs, parse_constant=bad)
    if not isinstance(value, dict):
        raise ValueError('ledger record must be an object')
    return value


class LocalBudget:
    """One-writer, append-only seconds ledger shared by all local model runs.

    Pending calls cost the full reserved duration. Completed calls cost at least
    observed monotonic elapsed time. Reopening never refunds pending calls, and
    a new process cannot complete an old reservation. A timeout overrun is charged
    in full and permanently halts the ledger. Missing/corrupt state is not repaired.
    This is local cooperative accounting, not protection against ledger deletion.
    """
    def __init__(self, path, cap_seconds=3600, *, create=False, clock=time.monotonic):
        self.cap = _seconds(cap_seconds, positive=True)
        if self.cap > 3600:
            raise ValueError('local approval permits at most 3600 seconds')
        self.clock = clock
        self.used = Decimal(0)
        self.pending = {}
        self.keys = set()
        self.started = {}
        self.halted = False
        self.locked = False
        self.file = open(path, 'x+b' if create else 'r+b')
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.locked = True
            if create:
                self._append({'event': 'local_budget', 'schema': 1,
                              'cap_seconds': str(self.cap)})
            self._read()
        except BaseException:
            self.close()
            raise

    @property
    def remaining(self):
        return max(Decimal(0), self.cap - self.used)

    def _read(self):
        self.file.seek(0)
        raw = self.file.read()
        if not raw.endswith(b'\n'):
            raise ValueError('incomplete local budget ledger; manual review required')
        records = [_strict_json(line) for line in raw.decode('utf8').splitlines()]
        if not records or type(records[0].get('schema')) is not int or records[0] != {'event': 'local_budget', 'schema': 1,
                                        'cap_seconds': str(self.cap)}:
            raise ValueError('local budget header or approved cap differs')
        for event in records[1:]:
            if self.halted:
                raise ValueError('records follow a halted local budget')
            kind = event.get('event')
            if kind == 'reserve' and set(event) == {'event', 'key', 'timeout_seconds', 'used_seconds'}:
                key = event['key']
                self._validate_key(key)
                bound = _seconds(event['timeout_seconds'], positive=True)
                self.used += bound
                if self.used > self.cap:
                    raise ValueError('local reservation exceeds approved cap')
                self.keys.add(key)
                self.pending[key] = bound
            elif kind == 'complete' and set(event) == {'event', 'key', 'elapsed_seconds', 'used_seconds', 'halted'}:
                key = event['key']
                if not isinstance(key, str) or key not in self.pending:
                    raise ValueError('completion lacks a pending reservation')
                elapsed = _seconds(event['elapsed_seconds'])
                bound = self.pending.pop(key)
                self.used += elapsed - bound
                halted = elapsed > bound or self.used > self.cap
                if type(event['halted']) is not bool or event['halted'] != halted:
                    raise ValueError('invalid overrun status')
                self.halted = halted
            elif kind == 'halt' and set(event) == {'event', 'reason'}:
                if not isinstance(event['reason'], str) or not event['reason']:
                    raise ValueError('invalid halt reason')
                self.halted = True
                continue
            else:
                raise ValueError('unknown local budget record')
            if _seconds(event['used_seconds']) != self.used:
                raise ValueError('local budget totals differ')

    def _validate_key(self, key):
        if not isinstance(key, str) or not key or len(key) > 512 or key in self.keys:
            raise ValueError('invalid or already reserved local request key')

    def _append(self, event):
        try:
            self.file.seek(0, os.SEEK_END)
            self.file.write((json.dumps(event, sort_keys=True, allow_nan=False,
                                        separators=(',', ':')) + '\n').encode('utf8'))
            self.file.flush()
            os.fsync(self.file.fileno())
        except BaseException:
            self.halted = True
            raise

    def reserve(self, key, timeout_seconds):
        if self.halted or self.file.closed:
            raise LocalBudgetExceeded('local budget halted or closed')
        self._validate_key(key)
        bound = _seconds(timeout_seconds, positive=True)
        if self.used + bound > self.cap:
            raise LocalBudgetExceeded('aggregate local time cap exhausted')
        started = self.clock()
        if type(started) not in (int, float) or not math.isfinite(started):
            raise ValueError('invalid monotonic clock')
        total = self.used + bound
        self._append({'event': 'reserve', 'key': key, 'timeout_seconds': str(bound),
                      'used_seconds': str(total)})
        self.used = total
        self.keys.add(key)
        self.pending[key] = bound
        self.started[key] = started

    def complete(self, key, elapsed_seconds=None):
        if self.halted or self.file.closed:
            raise LocalBudgetExceeded('local budget halted or closed')
        if key not in self.started or key not in self.pending:
            raise ValueError('completion requires a reservation from this open session')
        measured = _seconds(self.clock() - self.started[key])
        elapsed = measured if elapsed_seconds is None else max(measured, _seconds(elapsed_seconds))
        bound = self.pending[key]
        total = self.used - bound + elapsed
        halted = elapsed > bound or total > self.cap
        self._append({'event': 'complete', 'key': key, 'elapsed_seconds': str(elapsed),
                      'used_seconds': str(total), 'halted': halted})
        self.used = total
        self.pending.pop(key)
        self.started.pop(key)
        self.halted = halted
        if halted:
            raise LocalBudgetExceeded('local request exceeded reserved duration; ledger halted')
        return elapsed

    def halt(self, reason='resource_contention'):
        if self.file.closed:
            raise LocalBudgetExceeded('local budget is closed')
        if not isinstance(reason, str) or not reason or len(reason) > 512:
            raise ValueError('nonempty bounded halt reason required')
        if not self.halted:
            self._append({'event': 'halt', 'reason': reason})
            self.halted = True

    def close(self):
        if self.file.closed:
            return
        try:
            if self.locked:
                self.file.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        finally:
            self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def probe_nvidia_smi(*, run=subprocess.run, which=shutil.which):
    """Return per-GPU utilization and MiB; fail closed on missing/unknown values."""
    executable = which('nvidia-smi')
    if not executable:
        raise ResourceProbeUnavailable('nvidia-smi is unavailable')
    try:
        result = run([executable, '--query-gpu=index,uuid,utilization.gpu,memory.used,memory.total',
                      '--format=csv,noheader,nounits'], check=True, capture_output=True,
                     text=True, timeout=5, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        rows = list(csv.reader(io.StringIO(result.stdout)))
        samples = []
        indices = set()
        uuids = set()
        for row in rows:
            if len(row) != 5:
                raise ValueError('unexpected GPU field count')
            index, uuid, utilization, used, total = [value.strip() for value in row]
            index, utilization, used, total = int(index), float(utilization), float(used), float(total)
            if (index < 0 or index in indices or not uuid.startswith('GPU-') or uuid in uuids
                    or not all(math.isfinite(v) for v in (utilization, used, total))
                    or not 0 <= utilization <= 100 or not 0 <= used <= total or total <= 0):
                raise ValueError('invalid GPU measurements')
            samples.append({'index': index, 'uuid': uuid, 'utilization_percent': utilization,
                            'memory_used_mib': used, 'memory_total_mib': total,
                            'memory_free_mib': total - used})
            indices.add(index)
            uuids.add(uuid)
        if not samples:
            raise ValueError('no GPU measurements')
        return samples
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError) as exc:
        raise ResourceProbeUnavailable('GPU resource measurements unavailable or invalid') from exc


class ResourceGuard:
    """Pre-dispatch idle-GPU guard; own in-flight utilization is not contention proof.

    With keep_alive=0, cold calls use the default 3 GiB free requirement. A driver
    using a resident model must choose and record a justified memory requirement.
    This does not measure CPU or identify GPU process ownership; log that limit.
    """
    def __init__(self, *, max_utilization_percent=25, min_free_mib=3072,
                 probe=probe_nvidia_smi):
        values = (max_utilization_percent, min_free_mib)
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError('resource thresholds must be finite')
        if not 0 <= max_utilization_percent <= 100 or min_free_mib < 0:
            raise ValueError('invalid resource thresholds')
        self.max_utilization_percent = max_utilization_percent
        self.min_free_mib = min_free_mib
        self.probe = probe

    def check(self):
        samples = self.probe()
        if not isinstance(samples, list) or not samples:
            raise ResourceProbeUnavailable('no GPU resource measurements')
        for sample in samples:
            try:
                utilization = sample['utilization_percent']
                free = sample['memory_free_mib']
                if any(type(v) not in (int, float) or not math.isfinite(v) for v in (utilization, free)):
                    raise ValueError('nonfinite GPU resource value')
                if not 0 <= utilization <= 100 or free < 0:
                    raise ValueError('invalid GPU resource value')
            except (KeyError, TypeError, ValueError) as exc:
                raise ResourceProbeUnavailable('invalid GPU resource measurements') from exc
            if utilization > self.max_utilization_percent or free < self.min_free_mib:
                raise ResourceContention('GPU utilization or available memory violates pre-dispatch policy')
        return samples
