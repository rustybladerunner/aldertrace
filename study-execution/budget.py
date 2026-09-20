"""Single-writer campaign reservations shared by all phases; never authorizes calls."""
import os
from decimal import Decimal
from adapters import canonical, strict_json
from journal import money, BudgetExceeded


class CampaignBudget:
    """Hold an OS lock until close; crashes release the lock, never reservations.

    Append-only, fsynced before dispatch. Reopening requires the same approved cap.
    Partial/corrupt records fail closed. No refunds or automatic uncertain retries.
    Protecting against deliberate ledger deletion is outside this local tool's scope.
    """
    def __init__(self, path, cap_usd, *, create=False):
        self.cap = money(cap_usd)
        self.reserved = Decimal(0)
        self.keys = set()
        self.halted = False
        self.file = open(path, 'x+b' if create else 'r+b')
        self.locked = False
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.locked = True
            if create:
                self._append({'event':'campaign', 'schema':1, 'cap_usd':str(self.cap)})
            self._read()
        except BaseException:
            self.close()
            raise

    def _read(self):
        self.file.seek(0)
        raw = self.file.read()
        if not raw.endswith(b'\n'):
            raise ValueError('incomplete campaign ledger; reconcile before continuing')
        events = [strict_json(line) for line in raw.decode('utf8').splitlines()]
        if not events or events[0] != {'event':'campaign','schema':1,'cap_usd':str(self.cap)}:
            raise ValueError('campaign header or approved cap differs')
        for event in events[1:]:
            if self.halted:
                raise ValueError('events after campaign halt')
            if event.get('event') == 'halt':
                self.halted = True
                continue
            if set(event) != {'event','key','bound_usd','reserved_total_usd'} or event['event'] != 'reserved':
                raise ValueError('unknown campaign event')
            key = event['key']
            if not isinstance(key,str) or not key or key in self.keys:
                raise ValueError('invalid or duplicate reservation')
            self.reserved += money(event['bound_usd'])
            if self.reserved > self.cap or money(event['reserved_total_usd']) != self.reserved:
                raise ValueError('campaign totals invalid')
            self.keys.add(key)

    def _append(self, event):
        self.file.seek(0, os.SEEK_END)
        self.file.write((canonical(event)+'\n').encode('utf8'))
        self.file.flush()
        os.fsync(self.file.fileno())

    def reserve(self, key, bound):
        if self.halted or self.file.closed:
            raise BudgetExceeded('campaign halted or closed')
        if not isinstance(key,str) or not key or key in self.keys:
            raise ValueError('request already reserved or invalid key')
        bound = money(bound)
        if self.reserved + bound > self.cap:
            raise BudgetExceeded('campaign aggregate cap exhausted')
        total = self.reserved + bound
        # If persistence fails, this object becomes unusable; reopen for reconciliation.
        try:
            self._append({'event':'reserved','key':key,'bound_usd':str(bound),
                          'reserved_total_usd':str(total)})
        except BaseException:
            self.halted = True
            raise
        self.reserved = total
        self.keys.add(key)

    def halt(self):
        if not self.halted:
            self.halted = True
            self._append({'event':'halt','reason':'usage_or_response_requires_review'})

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

    def __enter__(self): return self
    def __exit__(self, *args): self.close()
