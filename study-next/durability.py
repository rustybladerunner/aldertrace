"""Versioned, locked recovery over the frozen schema-one attempt journal.

No transport, credential loading, budget creation, refund, or implicit retry.
The coordinator validates the immutable request plan and actual response bodies.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

from adapters import canonical, strict_json
from budget import CampaignBudget
from journal import BudgetExceeded, money


class RecoveryRequired(RuntimeError):
    """Evidence cannot safely authorize another attempt."""


TRANSIENT = {429, 500, 502, 503, 504, 529}


def _path(value):
    return os.path.normcase(str(Path(value).resolve()))


def _lock(file):
    file.seek(0)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(file):
    file.seek(0)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def _rows(file, label):
    file.seek(0)
    raw = file.read()
    if not raw or not raw.endswith(b'\n'):
        raise ValueError(f'{label} is empty or lacks a final newline; evidence unchanged')
    rows = [strict_json(line) for line in raw.decode('utf8').splitlines()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError(f'{label} contains a non-object record')
    return rows


def _append(file, event):
    payload = (canonical(event) + '\n').encode('utf8')
    file.seek(0, os.SEEK_END)
    if file.write(payload) != len(payload):
        raise OSError('short journal write')
    file.flush()
    os.fsync(file.fileno())


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError(f'nonempty bounded {label} required')
    return value


class RecoverableJournal:
    """Compatible with frozen execute_one, with explicit conservative recovery.

    Binding: ``<path>.binding.json``. Audit: ``<path>.recovery.jsonl`` unless
    explicitly supplied. Both are required when reopening. Audit paths are
    exclusively locked too, so do not share one between live journal instances.

    ``unresolved`` and ``orphans`` contain ``(key, attempt)`` tuples. Orphans are
    global reservations missing from the journal; ``attempts`` includes them.
    ``reserved`` includes their retained charge. Reconciliation only classifies
    pending attempts with a durable request. Requestless reservations and orphans
    remain blocking; neither can safely be turned into an invented request.
    """

    def __init__(self, path, cap_usd, *, campaign, scope, identity,
                 create=False, secrets=(), audit_path=None):
        if type(create) is not bool:
            raise ValueError('create must be explicit boolean')
        self.cap = money(cap_usd)
        self.campaign = campaign
        self.scope = _text(scope, 'scope')
        if not isinstance(identity, dict) or not identity:
            raise ValueError('nonempty immutable identity required')
        self.identity = strict_json(canonical(identity))
        self.path = Path(path).resolve()
        self.binding_path = Path(str(self.path) + '.binding.json')
        self.audit_path = Path(audit_path).resolve() if audit_path else Path(str(self.path) + '.recovery.jsonl')
        if len({_path(self.path), _path(self.binding_path), _path(self.audit_path)}) != 3:
            raise ValueError('journal, binding, and recovery audit paths must differ')
        self.secrets = tuple(s for s in secrets if isinstance(s, str) and s)
        self.file = None
        self._audit_file = None
        self._locked = self._audit_locked = self._poisoned = False
        self.attempts = {}
        self.unresolved = set()
        self.orphans = set()
        self._records = {}
        self._delayed = set()
        self._declined = set()
        self._audits = {}
        self._recorded_reserved = money(0)
        self.reserved = money(0)
        self._active_campaign()
        self._binding = {
            'schema': 1, 'journal': _path(self.path), 'scope': self.scope,
            'identity': self.identity, 'campaign': _path(campaign.file.name),
            'cap_usd': str(self.cap.normalize()), 'audit': _path(self.audit_path),
        }
        self._binding_hash = hashlib.sha256(canonical(self._binding).encode('utf8')).hexdigest()
        try:
            self.file = open(self.path, 'x+b' if create else 'r+b')
            _lock(self.file)
            self._locked = True
            if create:
                if self._campaign_reservations():
                    raise RecoveryRequired('scope already has campaign reservations; cannot create replacement journal')
                with self.binding_path.open('xb') as binding:
                    _append(binding, self._binding)
            else:
                with self.binding_path.open('rb') as binding:
                    rows = _rows(binding, 'journal binding')
                if rows != [self._binding]:
                    raise ValueError('journal identity, scope, campaign, or cap differs')
            self._audit_file = self.audit_path.open('x+b' if create else 'r+b')
            _lock(self._audit_file)
            self._audit_locked = True
            audit_header = {'event': 'recovery_audit', 'schema': 1,
                            'binding_sha256': self._binding_hash}
            if create:
                _append(self._audit_file, audit_header)
                _append(self.file, {'event': 'begin', 'cap_usd': str(self.cap), 'schema': 1})
            audit_rows = _rows(self._audit_file, 'recovery audit')
            if audit_rows[0] != audit_header:
                raise ValueError('recovery audit binding differs')
            for event in audit_rows[1:]:
                self._accept_audit(event)
            self._global_bounds = self._campaign_reservations()
            rows = _rows(self.file, 'attempt journal')
            if (set(rows[0]) != {'event', 'cap_usd', 'schema'}
                    or rows[0]['event'] != 'begin' or type(rows[0]['schema']) is not int
                    or rows[0]['schema'] != 1 or money(rows[0]['cap_usd']) != self.cap):
                raise ValueError('journal header or approved cap differs')
            for event in rows[1:]:
                self._accept(event, commit=True)
            self._sync_campaign()
        except BaseException:
            self.close()
            raise

    def _active_campaign(self):
        if (not isinstance(self.campaign, CampaignBudget)
                or self.campaign.file.closed or not self.campaign.locked
                or self.campaign.halted):
            raise BudgetExceeded('an open, locked, active campaign is required')
        if self.campaign.cap != self.cap:
            raise ValueError('journal cap must equal the existing approved campaign cap')

    def _usable(self):
        if self._poisoned or self.file is None or self.file.closed:
            raise RecoveryRequired('journal is closed or persistence failed; inspect before recovery')
        self._active_campaign()

    def _campaign_reservations(self):
        """Read under the caller-owned campaign lock; never create/refund entries."""
        current = self.campaign.file.tell()
        try:
            rows = _rows(self.campaign.file, 'campaign')
        finally:
            self.campaign.file.seek(current)
        bounds = {}
        for event in rows[1:]:
            if event.get('event') != 'reserved':
                continue
            encoded = event['key']
            try:
                value = strict_json(encoded)
            except (ValueError, TypeError):
                continue  # Existing unrelated historical reservation keys are valid.
            if not isinstance(value, list) or len(value) != 3 or value[0] != self.scope:
                continue
            key, attempt = value[1:]
            _text(key, 'logical request key')
            if type(attempt) is not int or attempt not in (1, 2) or encoded != canonical(value):
                raise ValueError('malformed reservation in this journal scope')
            pair = (key, attempt)
            if pair in bounds:
                raise ValueError('duplicate scoped campaign reservation')
            bounds[pair] = money(event['bound_usd'])
        return bounds

    def _sync_campaign(self):
        self._global_bounds = self._campaign_reservations()
        for pair, record in self._records.items():
            if self._global_bounds.get(pair) != money(record['reserved']['bound_usd']):
                raise ValueError('journal reservation missing or changed in campaign')
        self.orphans = set(self._global_bounds) - set(self._records)
        for key, attempt in self.orphans:
            self.attempts[key] = max(self.attempts.get(key, 0), attempt)
        self.reserved = self._recorded_reserved + sum(
            (self._global_bounds[p] for p in self.orphans), money(0))
        if self.reserved > self.cap:
            raise ValueError('journal scope exceeds campaign cap')

    def _accept_audit(self, event):
        required = {'event', 'key', 'attempt', 'reference', 'request_sha256', 'recovery_id'}
        if set(event) != required or event['event'] != 'reconcile_interrupted':
            raise ValueError('unknown recovery audit event')
        _text(event['reference'], 'reconciliation reference')
        _text(event['key'], 'logical request key')
        if type(event['attempt']) is not int or event['attempt'] not in (1, 2):
            raise ValueError('invalid recovery attempt')
        digest = event['request_sha256']
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('invalid audited request hash')
        expected = hashlib.sha256(canonical({k: v for k, v in event.items() if k != 'recovery_id'}).encode()).hexdigest()
        if event['recovery_id'] != expected or expected in self._audits:
            raise ValueError('invalid or duplicate recovery audit identity')
        self._audits[expected] = event

    def _accept(self, event, *, commit):
        if not isinstance(event, dict):
            raise ValueError('journal event must be an object')
        kind = event.get('event')
        key = _text(event.get('key'), 'logical request key')
        if kind in ('retry_delay', 'retry_declined'):
            attempt = self.attempts.get(key)
            pair = (key, attempt)
            previous = self._records.get(pair, {}).get('result', {})
            if (previous.get('status') not in TRANSIENT or attempt != 1
                    or pair in self._delayed or pair in self._declined):
                raise ValueError('retry metadata lacks a unique transient first attempt')
            if kind == 'retry_delay':
                value = event.get('seconds')
                if set(event) != {'event', 'key', 'seconds'} or type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 30:
                    raise ValueError('invalid retry delay')
                if commit:
                    self._delayed.add(pair)
            else:
                if set(event) != {'event', 'key', 'reason'}:
                    raise ValueError('invalid retry decline')
                _text(event['reason'], 'retry decline reason')
                if commit:
                    self._declined.add(pair)
            return
        attempt = event.get('attempt')
        if type(attempt) is not int or attempt not in (1, 2):
            raise ValueError('invalid attempt number')
        pair = (key, attempt)
        record = self._records.get(pair)
        if kind == 'reserved':
            if set(event) != {'event', 'key', 'attempt', 'bound_usd', 'reserved_total_usd'}:
                raise ValueError('invalid reservation fields')
            if record is not None or attempt != self.attempts.get(key, 0) + 1 or self.unresolved:
                raise ValueError('duplicate, unordered, or overlapping reservation')
            if attempt == 2 and (key, 1) not in self._delayed:
                raise ValueError('second attempt lacks explicit transient retry delay')
            bound = money(event['bound_usd'])
            total = self._recorded_reserved + bound
            if self._global_bounds.get(pair) != bound or money(event['reserved_total_usd']) != total or total > self.cap:
                raise ValueError('reservation differs from campaign or running total')
            if commit:
                self._records[pair] = {'reserved': event}
                self.attempts[key] = attempt
                self._recorded_reserved = total
                self.reserved = total
                self.unresolved.add(pair)
        elif kind == 'request':
            if set(event) != {'event', 'key', 'attempt', 'arm', 'body', 'expected_model'} or record is None or 'request' in record or 'result' in record:
                raise ValueError('request lacks a unique reservation')
            _text(event['arm'], 'arm')
            _text(event['expected_model'], 'expected model')
            if not isinstance(event['body'], dict):
                raise ValueError('request body must be an object')
            if commit:
                record['request'] = event
        elif kind == 'result':
            if record is None or 'request' not in record or 'result' in record:
                raise ValueError('result lacks a unique recorded request')
            elapsed = event.get('elapsed_ms')
            recovery = event.get('error_type') == 'InterruptedProcess'
            if recovery:
                audit = self._audits.get(event.get('recovery_id'))
                request_hash = hashlib.sha256(canonical(record['request']).encode()).hexdigest()
                if (elapsed is not None or event.get('billing') != 'uncertain' or 'status' in event
                        or audit is None or (audit['key'], audit['attempt']) != pair
                        or audit['request_sha256'] != request_hash):
                    raise ValueError('interrupted classification requires its audit and unknown timing')
            elif type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
                raise ValueError('recorded result requires valid elapsed time')
            if 'status' in event:
                if type(event['status']) is not int or not 100 <= event['status'] <= 599 or not isinstance(event.get('body'), str):
                    raise ValueError('invalid recorded response envelope')
            elif not isinstance(event.get('error_type'), str) or not event['error_type']:
                raise ValueError('result requires response status or error type')
            if commit:
                record['result'] = event
                self.unresolved.remove(pair)
        else:
            raise ValueError('unknown journal event')

    def write(self, event):
        self._usable()
        # Redact before both persistence and validation/state retention.
        encoded = canonical(event)
        for secret in self.secrets:
            encoded = encoded.replace(json.dumps(secret, ensure_ascii=True)[1:-1], '[REDACTED]')
        event = strict_json(encoded)
        self._accept(event, commit=False)
        try:
            _append(self.file, event)
        except BaseException:
            self._poisoned = True
            raise
        self._accept(event, commit=True)

    def reserve(self, key, bound):
        self._usable()
        self._sync_campaign()
        if self.unresolved or self.orphans:
            raise RecoveryRequired('unresolved or orphan reservation; no further dispatch')
        _text(key, 'logical request key')
        bound = money(bound)
        attempt = self.attempts.get(key, 0) + 1
        if attempt > 2 or (attempt == 2 and (key, 1) not in self._delayed):
            raise ValueError('logical request already attempted without a permitted retry')
        if self.reserved + bound > self.cap:
            raise BudgetExceeded('reservation exceeds aggregate cap')
        # Global charge survives every subsequent local persistence failure.
        self.campaign.reserve(canonical([self.scope, key, attempt]), bound)
        self._global_bounds[(key, attempt)] = bound
        try:
            self.write({'event': 'reserved', 'key': key, 'attempt': attempt,
                        'bound_usd': str(bound),
                        'reserved_total_usd': str(self._recorded_reserved + bound)})
        except BaseException:
            self._poisoned = True
            raise
        return attempt

    def reconcile(self, reference):
        """Explicitly classify durable in-flight requests; never resend or refund.

        Audit is fsynced before each classification. A crash after that audit is
        harmless: repeating the same reference reuses its audit identity. Unknown
        requestless/orphan reservations remain visible and block reserve().
        """
        self._usable()
        _text(reference, 'reconciliation reference')
        self._sync_campaign()
        reconciled = []
        for key, attempt in sorted(self.unresolved):
            record = self._records[(key, attempt)]
            if 'request' not in record:
                continue
            event = {'event': 'reconcile_interrupted', 'key': key, 'attempt': attempt,
                     'reference': reference,
                     'request_sha256': hashlib.sha256(canonical(record['request']).encode()).hexdigest()}
            event['recovery_id'] = hashlib.sha256(canonical(event).encode()).hexdigest()
            if event['recovery_id'] not in self._audits:
                try:
                    _append(self._audit_file, event)
                    self._accept_audit(event)
                except BaseException:
                    self._poisoned = True
                    raise
            self.write({'event': 'result', 'key': key, 'attempt': attempt,
                        'error_type': 'InterruptedProcess', 'billing': 'uncertain',
                        'elapsed_ms': None, 'recovery_id': event['recovery_id'],
                        'parsed': {'valid': False, 'answer': None, 'reason': 'interrupted_attempt'}})
            reconciled.append((key, attempt))
        return reconciled

    def close(self):
        first_error = None
        for attr, lock_attr in (('_audit_file', '_audit_locked'), ('file', '_locked')):
            file = getattr(self, attr, None)
            if file is not None and not file.closed:
                try:
                    if getattr(self, lock_attr, False):
                        _unlock(file)
                except OSError as exc:
                    first_error = first_error or exc
                finally:
                    file.close()
                    setattr(self, lock_attr, False)
        if first_error is not None:
            raise first_error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
