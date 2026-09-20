"""Durable attempt reservation and replay. Transport is injected; none is bundled."""
import json
import math
import os
import time
import random
from decimal import Decimal
from adapters import canonical, parse_response


class BudgetExceeded(RuntimeError):pass


def money(value):
    result=Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError('invalid monetary amount')
    return result


class Journal:
    """Single-writer, new-file-only journal; uncertain attempts retain reservation.

    Recovery is read-only. A future resume implementation must reconcile unfinished
    attempts, not silently send them again. No run authorizes itself via this class.
    """
    def __init__(self,path,cap_usd,secrets=(),*,campaign=None,scope=None):
        if campaign is not None and (not isinstance(scope,str) or not scope):
            raise ValueError('shared campaign requires a unique run scope')
        self.campaign=campaign
        self.scope=scope
        self.cap=money(cap_usd)
        self.reserved=Decimal(0)
        self.secrets=tuple(s for s in secrets if s)
        self.file=open(path,'x',encoding='utf8')
        self.attempts={}
        self.write({'event':'begin','cap_usd':str(self.cap),'schema':1})

    def write(self,event):
        text=canonical(event)
        # Redact before persistence, including quoted/escaped secret characters.
        for secret in self.secrets:
            escaped=json.dumps(secret,ensure_ascii=True)[1:-1]
            text=text.replace(escaped,'[REDACTED]')
        self.file.write(text+'\n')
        self.file.flush()
        os.fsync(self.file.fileno())

    def reserve(self,key,bound):
        bound=money(bound)
        if self.reserved+bound > self.cap:
            raise BudgetExceeded('reservation exceeds aggregate cap')
        attempt=self.attempts.get(key,0)+1
        if attempt>2:
            raise ValueError('maximum two attempts per logical request')
        if self.campaign is not None:
            # Reserve globally first. A crash before the local record retains the charge.
            self.campaign.reserve(canonical([self.scope,key,attempt]),bound)
        self.reserved+=bound
        self.attempts[key]=attempt
        self.write({'event':'reserved','key':key,'attempt':attempt,
                    'bound_usd':str(bound),'reserved_total_usd':str(self.reserved)})
        return attempt

    def close(self):self.file.close()


def execute_one(journal,key,arm,body,expected_model,bound,transport,*,sleep=time.sleep):
    """Record before dispatch; retry only explicit transient HTTP failure once.

    Transport receives body and returns status/body/request_id/elapsed_ms and optional
    retry_after seconds. It must not return auth headers. No timeout retry: billing
    is uncertain. Raw body is retained even when schema validation fails.
    """
    if key in journal.attempts:
        raise ValueError('logical request already attempted')
    while True:
        attempt=journal.reserve(key,bound)
        journal.write({'event':'request','key':key,'attempt':attempt,'arm':arm,
                       'body':body,'expected_model':expected_model})
        started=time.perf_counter()
        try:
            response=transport(body)
        except Exception as exc:
            journal.write({'event':'result','key':key,'attempt':attempt,
                'error_type':type(exc).__name__,'billing':'uncertain',
                'elapsed_ms':round((time.perf_counter()-started)*1000,3),
                'parsed':{'valid':False,'answer':None,'reason':'transport_failure'}})
            return None
        if (not isinstance(response,dict)
                or type(response.get('status')) is not int
                or not 100<=response['status']<=599
                or not isinstance(response.get('body'),str)
                or (response.get('request_id') is not None
                    and not isinstance(response['request_id'],str))):
            # A malformed transport envelope still represents a dispatched attempt.
            # Retain its reservation, record the failure, and never retry it blindly.
            event={'event':'result','key':key,'attempt':attempt,
                'error_type':'InvalidTransportEnvelope','billing':'uncertain',
                'envelope_type':type(response).__name__,
                'elapsed_ms':round((time.perf_counter()-started)*1000,3),
                'parsed':{'valid':False,'answer':None,'reason':'invalid_transport_envelope'}}
            if isinstance(response,dict) and isinstance(response.get('body'),str):
                event['body']=response['body']
            journal.write(event)
            return None
        status=response.get('status')
        parsed=parse_response(response.get('body',''),arm,expected_model) if status==200 else {
            'valid':False,'answer':None,'reason':'http_failure'}
        journal.write({'event':'result','key':key,'attempt':attempt,'status':status,
                       'body':response.get('body'),'request_id':response.get('request_id'),
                       'elapsed_ms':round((time.perf_counter()-started)*1000,3),
                       'parsed':parsed})
        if status==200 or attempt==2 or status not in (429,500,502,503,504,529):
            return parsed
        retry_after=response.get('retry_after',1.0)
        if type(retry_after) not in (int,float) or not math.isfinite(retry_after) or not 0<=retry_after<=30:
            journal.write({'event':'retry_declined','key':key,'reason':'unbounded_retry_after'})
            return parsed
        delay=max(retry_after, random.Random(key).uniform(0,2))
        journal.write({'event':'retry_delay','key':key,'seconds':delay})
        sleep(delay)


def replay(path):
    """Read-only final responses and unresolved reservations, with no network."""
    from adapters import strict_json
    pending=set(); results={}
    with open(path,encoding='utf8') as source:
        for line in source:
            e=strict_json(line)
            if e['event']=='reserved':pending.add((e['key'],e['attempt']))
            if e['event']=='result':
                pending.discard((e['key'],e['attempt']))
                results[e['key']]=e
    return {'results':results,'unfinished_attempts':sorted(pending)}
