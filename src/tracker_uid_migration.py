"""Offline migration of explicitly marked BENCH databases only.

No discovery of user files, network, installed app updates, or outbox sending.
Legacy source is replaced with an unsupported-schema fence before new activation.
"""
from pathlib import Path
import hashlib
import json
import os
import sqlite3
from decimal import Decimal
from filelock import FileLock
from tracker_uid_catalog import UidCatalog
from tracker_uid_accounting import UidAccounting, mg
from tracker_uid_client import canonical_uid


def encode(value): return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
def digest(raw): return hashlib.sha256(raw).hexdigest()
def history_identity(printer_id, job_id, start):
    value = Decimal(str(start))
    if isinstance(start, bool) or not value.is_finite() or value <= 0 or not printer_id or not job_id:
        raise ValueError('Invalid legacy history identity')
    return digest(encode([printer_id, job_id, str(value.normalize())]))


def atomic(path, raw):
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('wb') as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    if os.name == 'nt':
        # Windows cannot open directories through os.open for POSIX fsync.
        # Flush the file above, then request a write-through same-volume move.
        import ctypes
        from ctypes import wintypes
        move = ctypes.WinDLL('kernel32', use_last_error=True).MoveFileExW
        move.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
        move.restype = wintypes.BOOL
        if not move(str(tmp), str(path), 0x1 | 0x8):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.replace(tmp, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)


class BenchMigration:
    def __init__(self, root, *, validator):
        self.validator = validator
        self.root = Path(root).resolve()
        if (self.root / '.tracker-migration-bench').read_text().strip() != 'synthetic-only':
            raise ValueError('Explicit synthetic migration bench marker required')
        self.source = self.root / 'legacy' / 'spools_u1.json'
        self.target = self.root / 'tracker.sqlite'
        self.backup = self.root / 'legacy.backup.json'
        self.state = self.root / 'tracker.sqlite.migration-state.json'
        self.stage = self.root / 'migration.stage.sqlite'
        self.receipt = self.root / 'migration.receipt.json'
        for path in (self.source, self.target, self.backup, self.state, self.stage, self.receipt):
            if path.is_symlink() or path.parent.is_symlink(): raise ValueError('Symlink paths forbidden')
        self.target_lock = FileLock(str(self.target)+'.migration.lock', timeout=0)
        self.remote_lock = FileLock(str(self.source.parent/'spoolman-worker.lock'), timeout=0)
        self.legacy_lock = FileLock(str(self.source.parent/'spools_u1.lock'), timeout=0)

    def migrate(self, printer_ids, uid_bindings, *, fail=None):
        """Map explicit old host:port identities and explicit spool IDs to UIDs.

        Missing UID means a working manual spool with NULL UID, never an invented tag.
        All old runs get replay fences, including unresolved/noncommitted ones.
        """
        with self.target_lock, self.legacy_lock, self.remote_lock:
            options = digest(encode([printer_ids, uid_bindings]))
            if self.state.exists():
                state = json.loads(self.state.read_bytes())
                if state['mode'] == 'active' and state['options'] == options:
                    if self.source.read_bytes() != encode({'schema_version': 2000, 'migration': state['source_sha']}):
                        raise ValueError('Legacy write fence changed')
                    probe=sqlite3.connect(f'file:{self.target}?mode=ro',uri=True)
                    try:
                        if probe.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                            raise ValueError('Migration target corrupt')
                    finally: probe.close()
                    return json.loads(self.receipt.read_bytes())
                raise ValueError('Existing migration requires restore/review before retry')
            if self.target.exists() or self.backup.exists(): raise ValueError('Migration destination must be empty')
            raw = self.source.read_bytes()
            data = json.loads(raw)
            # Validate current fixed legacy schema without normalizing the saved bytes.
            self.validator(data)
            if data.get('schema_version') != 5: raise ValueError('Only validated schema 5 is supported')
            if set(uid_bindings) - set(data['spools']): raise ValueError('Unknown spool UID binding')
            bindings = {sid: canonical_uid(uid) for sid,uid in uid_bindings.items()}
            if len(set(bindings.values())) != len(bindings): raise ValueError('Duplicate UID binding')
            runs=[]
            for old_key, run in data.get('runs', {}).items():
                plan = data['plans'][run['plan_id']]
                cfg = plan['printer']; address = cfg['host'].casefold()+':'+str(cfg['port'])
                pid = printer_ids[address]
                key = history_identity(pid,run['job_id'],run['start_time'])
                runs.append((key,pid,run['job_id'],str(run['start_time']),old_key,run['status'],encode(run).decode()))
            if len({r[0] for r in runs}) != len(runs): raise ValueError('Duplicate canonical history identity')
            manual_slots={ch:sid for ch,sid in data.get('slots',{}).items() if sid and sid not in bindings and not data['spools'][sid].get('spoolman')}
            manual_pid=None
            if manual_slots:
                cfg=data['printer'];manual_pid=printer_ids[cfg['host'].casefold()+':'+str(cfg['port'])]
            atomic(self.backup,raw)
            state={'mode':'blocked','source_sha':digest(raw),'options':options}
            atomic(self.state,encode(state))
            if fail == 'backup': raise RuntimeError('Injected after backup')
            cat=UidCatalog(self.stage)
            try:
                accounting=UidAccounting(cat)
                cat.db.executescript('''
                    CREATE TABLE migration_source (payload BLOB NOT NULL, sha TEXT NOT NULL);
                    CREATE TABLE legacy_spools (spool_id TEXT PRIMARY KEY, payload TEXT NOT NULL, automatic INTEGER NOT NULL);
                    CREATE TABLE legacy_plans (plan_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                    CREATE TABLE legacy_outbox (operation_id TEXT PRIMARY KEY, original_state TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL);
                ''')
                with accounting.transaction():
                    cat.db.execute('INSERT INTO migration_source VALUES(?,?)',(raw,digest(raw)))
                    for sid, spool in data['spools'].items():
                        # Remote balances cannot be treated as a local debit ledger.
                        automatic = sid in bindings and not spool.get('spoolman')
                        cat.db.execute('INSERT INTO legacy_spools VALUES(?,?,?)',(sid,encode(spool).decode(),automatic))
                        if not spool.get('spoolman'):
                            cat.db.execute('INSERT INTO uid_spools VALUES(?,?,?,?)',(sid,bindings.get(sid),spool['name'],mg(spool['remaining_g'])))
                            cat.db.execute('INSERT INTO spool_details VALUES(?,?)',(sid,encode(spool).decode()))
                    for slot,sid in manual_slots.items():
                        channel=str(int(slot)-1)
                        ambiguous=list(manual_slots.values()).count(sid)>1
                        cat.db.execute('INSERT INTO manual_assignment_candidates VALUES(?,?,?,?)',(manual_pid,channel,sid,'duplicate legacy slot' if ambiguous else 'confirmation required'))
                        if not ambiguous:
                            cat.db.execute('INSERT INTO manual_assignments VALUES(?,?,?,?,?,0)',(manual_pid,channel,sid,'imported:'+slot,''))
                    cat.db.executemany('INSERT INTO legacy_plans VALUES(?,?)',[(k,encode(v).decode()) for k,v in data.get('plans',{}).items()])
                    cat.db.executemany('INSERT INTO uid_legacy_history VALUES(?,?,?,?,?,?,?)',runs)
                    for key, op in data.get('spoolman',{}).get('outbox',{}).items():
                        cat.db.execute('INSERT INTO legacy_outbox VALUES(?,?,?,?)',
                            (key,op['state'],'held' if op['state'] in ('pending','sending','uncertain') else op['state'],encode(op).decode()))
                    if fail == 'transaction': raise RuntimeError('Injected inside import transaction')
                assert cat.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
                assert not cat.db.execute('PRAGMA foreign_key_check').fetchall()
                receipt={'source_sha':digest(raw),'spools':len(data['spools']),'automatic_spools':cat.db.execute('SELECT count(*) FROM uid_spools WHERE uid IS NOT NULL').fetchone()[0], 'local_spools':cat.db.execute('SELECT count(*) FROM uid_spools').fetchone()[0],
                         'history_fences':len(runs),'plans':len(data.get('plans',{})),
                         'outbox':len(data.get('spoolman',{}).get('outbox',{})), 'mode':'active',
                         'inventory_sha':digest(encode([tuple(r) for r in cat.db.execute('SELECT * FROM uid_spools ORDER BY spool_id')]))}
            finally: cat.close()
            if fail == 'stage': raise RuntimeError('Injected after stage')
            atomic(self.receipt,encode(receipt))
            atomic(self.source,encode({'schema_version':2000,'migration':digest(raw)}))
            if fail == 'fence': raise RuntimeError('Injected after legacy fence')
            os.replace(self.stage,self.target)
            if fail == 'publish': raise RuntimeError('Injected before activation')
            state['mode']='active';atomic(self.state,encode(state))
            return receipt

    def restore_legacy(self):
        """Restore original bytes only before any new job/write in the new ledger.

        The migrated DB is retained for audit, deactivated before legacy is restored.
        A corrupt/used new DB requires reconciliation, never blind rollback.
        """
        with self.target_lock, self.legacy_lock, self.remote_lock:
            raw=self.backup.read_bytes()
            if not self.state.exists():
                if self.target.exists() or self.source.read_bytes()!=raw:
                    raise ValueError('Unjournaled backup requires review')
                atomic(self.state,encode({'mode':'restored','source_sha':digest(raw)}))
                return {'mode':'restored','source_sha':digest(raw)}
            state=json.loads(self.state.read_bytes())
            if digest(raw)!=state['source_sha']: raise ValueError('Backup checksum mismatch')
            if any(op['state'] in ('pending','sending','uncertain') for op in json.loads(raw).get('spoolman',{}).get('outbox',{}).values()):
                raise ValueError('Unresolved remote operations require reconciliation before legacy restore')
            if self.target.exists():
                db=sqlite3.connect(f'file:{self.target}?mode=ro',uri=True)
                try:
                    if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('Target corrupt; reconcile before rollback')
                    if db.execute('SELECT count(*) FROM uid_jobs').fetchone()[0] or db.execute('SELECT count(*) FROM uid_debits').fetchone()[0]:
                        raise ValueError('New accounting exists; reconcile before rollback')
                    # Also reject replenishment/registration changes after migration.
                    actual=[tuple(r) for r in db.execute('SELECT * FROM uid_spools ORDER BY spool_id')]
                    receipt=json.loads(self.receipt.read_bytes())
                    matches=digest(encode(actual))==receipt['inventory_sha']
                    if not matches and 'local_spools' not in receipt:
                        # Earlier archive-only targets may have gained their original
                        # untagged local rows when opened by the manual-aware model.
                        tagged=[r for r in actual if r[1] is not None]
                        original=json.loads(raw)['spools']
                        added=[r for r in actual if r[1] is None]
                        matches=(digest(encode(tagged))==receipt['inventory_sha'] and all(
                            sid in original and not original[sid].get('spoolman') and
                            name==original[sid]['name'] and amount==mg(original[sid]['remaining_g'])
                            for sid,uid,name,amount in added))
                    if not matches: raise ValueError('Inventory changed after migration')
                finally: db.close()
            state['mode']='restored';atomic(self.state,encode(state))
            atomic(self.source,raw)
            return {'mode':'restored','source_sha':digest(raw)}
