"""Owned subprocess: one synthetic local recommendation, no cloud credentials."""
import sys
import os
from pathlib import Path
from adapters import canonical, strict_json
from local_capture import RecordingBackend
from logitpick.schema import parse_request
from logitpick.engine import pick


class ImmediateReleaseBackend(RecordingBackend):
    def _read(self,path,body=None,timeout=10):
        if path=='/api/generate':
            body=dict(body,keep_alive=0)
        return super()._read(path,body,timeout=min(timeout,50))


def main():
    if len(sys.argv)!=3:raise ValueError('owned request and telemetry paths required')
    path=Path(sys.argv[1])
    if path.stat().st_size>1048576:raise ValueError('local request exceeds 1 MiB')
    body=strict_json(path.read_text(encoding='utf8')); records=[]
    request=parse_request(body)
    if len(request.questions)!=1:raise ValueError('exactly one local question per timed worker required')
    with Path(sys.argv[2]).open('x',encoding='utf8') as telemetry:
        def record(event):
            if event['event']=='local_request':
                event={**event,'body':dict(event['body'],keep_alive=0)}
            telemetry.write(canonical(event)+'\n');telemetry.flush();os.fsync(telemetry.fileno())
            records.append(event)
        backend=ImmediateReleaseBackend(record,authorized=True)
        try:
            response=pick(request,backend)
        except BaseException as exc:
            record({'event':'local_worker_failure','reason_type':type(exc).__name__,
                    'telemetry_complete':any(e['event']=='local_usage' for e in records)})
            raise
        print(canonical({'response':response,'records':records}))


if __name__=='__main__':main()
