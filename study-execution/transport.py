"""Bounded cloud HTTP transport. Importing constructs no client or request."""
import datetime
import email.utils
import time
import urllib.request
import urllib.error
from decimal import Decimal, InvalidOperation
from adapters import ENDPOINTS,MODELS,canonical,strict_json


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def retry_seconds(value,now=None):
    if value is None:return 1.0
    try:return max(0,float(value))
    except (ValueError,TypeError):pass
    try:
        dt=email.utils.parsedate_to_datetime(value)
        if dt.tzinfo is None:dt=dt.replace(tzinfo=datetime.timezone.utc)
        return max(0,(dt-(now or datetime.datetime.now(datetime.timezone.utc))).total_seconds())
    except (TypeError,ValueError,OverflowError):return 31.0 # journal declines unbounded retry


class CloudTransport:
    def __init__(self,arm,key,*,authorized=False,opener=None):
        if authorized is not True:raise PermissionError('explicit session authorization required')
        if arm not in ENDPOINTS:raise ValueError('unknown cloud arm')
        if not isinstance(key,str) or not key.strip() or '\r' in key or '\n' in key:
            raise ValueError('invalid credential')
        self.arm=arm;self.key=key
        self.opener=opener or urllib.request.build_opener(NoRedirect())

    def __call__(self,body):
        encoded=canonical(body).encode('utf8')
        if len(encoded)>4000 or body.get('model')!=MODELS[self.arm]:
            raise ValueError('request outside frozen planning envelope')
        if self.arm=='chat' and body.get('max_tokens')!=512:
            raise ValueError('output limit changed')
        req=urllib.request.Request(ENDPOINTS[self.arm],data=encoded,
            headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'},method='POST')
        started=time.perf_counter()
        try:response=self.opener.open(req,timeout=30)
        except urllib.error.HTTPError as exc:response=exc
        with response:
            raw=response.read(65537)
            if len(raw)>65536:raise ValueError('response exceeds limit; billing uncertain')
            return {'status':response.code,'body':raw.decode('utf8'),
                'request_id':response.headers.get('x-request-id'),
                'retry_after':retry_seconds(response.headers.get('retry-after')),
                'elapsed_ms':round((time.perf_counter()-started)*1000,3)}


def usage(raw,arm):
    """Preserve reported spend separately from rate-based estimates; reject gaps."""
    obj=strict_json(raw)
    if not isinstance(obj,dict):raise ValueError('response is not an object')
    u=obj.get('usage')
    if not isinstance(u,dict):raise ValueError('usage missing')
    fields=('prompt_tokens','completion_tokens') if arm=='chat' else ('input_tokens','output_tokens')
    inp,out=(u.get(f) for f in fields)
    if any(type(v) is not int or v<0 for v in (inp,out)):
        raise ValueError('invalid or missing token usage')
    if inp>5000 or (arm=='chat' and out>512):raise ValueError('token planning envelope exceeded')
    if arm=='chat':estimated=(Decimal(inp)*Decimal('.40')+Decimal(out)*Decimal('1.60'))/1000000
    elif arm in ('jev','jev_openrouter'):estimated=Decimal(inp)*Decimal('.042')/1000000
    else:raise ValueError('unknown cloud arm')
    cost=u.get('cost');reported=None
    if cost is not None:
        if type(cost) not in (float,int,str):raise ValueError('invalid reported cost')
        try:reported=Decimal(str(cost))
        except InvalidOperation as exc:raise ValueError('invalid reported cost') from exc
        if not reported.is_finite() or reported<0:raise ValueError('invalid reported cost')
    return {'input_tokens':inp,'output_tokens':out,'estimated_usd':str(estimated),
            'reported_usd':str(reported) if reported is not None else None,
            'accounting_usd':str(max(estimated,reported) if reported is not None else estimated),
            'rate_snapshot':'2026-09-19; verify again before live execution'}
