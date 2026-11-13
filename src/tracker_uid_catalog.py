"""Small standalone UID catalog adapter for Tracker 2.0 integration.

Explicit database path only. Observation updates never modify spool balance.
Not a replacement for the application's accounting engine or inventory schema.
"""
import sqlite3
import json
from pathlib import Path
from filelock import FileLock, Timeout
import uuid
from collections import Counter
from tracker_uid_client import canonical_uid


class UidCatalog:
    def __init__(self, path):
        self._migration_lock = None
        self._writer_lock = FileLock(str(Path(path).resolve())+".writer.lock", timeout=0)
        try:
            self._writer_lock.acquire()
        except Timeout as exc:
            raise ValueError("База занята другим Tracker. Закройте второй экземпляр.") from exc
        state = Path(str(path)+'.migration-state.json')
        if state.exists():
            lock = FileLock(str(path)+'.migration.lock', timeout=0)
            try:
                lock.acquire()
            except BaseException:
                self._writer_lock.release()
                raise
            try:
                if json.loads(state.read_bytes())['mode'] != 'active':
                    raise ValueError('Migrated database is not active')
            except BaseException:
                lock.release()
                self._writer_lock.release()
                raise
            self._migration_lock = lock
        try:
            self._open(path)
        except BaseException:
            if hasattr(self, 'db'): self.db.close()
            if self._migration_lock is not None: self._migration_lock.release()
            self._writer_lock.release()
            raise

    def _open(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS uid_spools (
                spool_id TEXT PRIMARY KEY, uid TEXT UNIQUE,
                name TEXT NOT NULL, remaining_mg INTEGER NOT NULL CHECK(remaining_mg >= 0));
            CREATE TABLE IF NOT EXISTS uid_locations (
                printer_id TEXT NOT NULL, channel TEXT NOT NULL, uid TEXT NOT NULL,
                confirmed INTEGER NOT NULL, PRIMARY KEY(printer_id,channel));
        ''')
        # Upgrade the old NOT NULL UID column without changing spool IDs or FKs.
        uid_column = next(r for r in self.db.execute('PRAGMA table_info(uid_spools)') if r['name']=='uid')
        if uid_column['notnull']:
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                self.db.execute('CREATE TABLE uid_spools_v2 (spool_id TEXT PRIMARY KEY, uid TEXT UNIQUE, name TEXT NOT NULL, remaining_mg INTEGER NOT NULL CHECK(remaining_mg>=0))')
                self.db.execute('INSERT INTO uid_spools_v2 SELECT * FROM uid_spools')
                self.db.execute('DROP TABLE uid_spools')
                self.db.execute('ALTER TABLE uid_spools_v2 RENAME TO uid_spools')
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS manual_assignments (
                printer_id TEXT NOT NULL, channel TEXT NOT NULL, spool_id TEXT NOT NULL UNIQUE REFERENCES uid_spools(spool_id),
                version TEXT NOT NULL, token TEXT NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(printer_id,channel));
            CREATE TABLE IF NOT EXISTS manual_assignment_candidates (
                printer_id TEXT NOT NULL, channel TEXT NOT NULL, spool_id TEXT NOT NULL, reason TEXT NOT NULL,
                PRIMARY KEY(printer_id,channel));
            CREATE TABLE IF NOT EXISTS spool_details (spool_id TEXT PRIMARY KEY REFERENCES uid_spools(spool_id), payload TEXT NOT NULL);
        """)
        # Promote local untagged spools from earlier archive-only migrations.
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='legacy_spools'").fetchone():
            with self.db:
                for row in self.db.execute('SELECT * FROM legacy_spools').fetchall():
                    detail = json.loads(row['payload'])
                    if not detail.get('spoolman'):
                        self.db.execute('INSERT OR IGNORE INTO spool_details VALUES(?,?)',(row['spool_id'],row['payload']))
                    if not row['automatic'] and not detail.get('spoolman'):
                        from tracker_uid_accounting import mg
                        self.db.execute('INSERT OR IGNORE INTO uid_spools VALUES(?,NULL,?,?)',(row['spool_id'],detail['name'],mg(detail['remaining_g'])))
        with self.db: self.db.execute('UPDATE manual_assignments SET confirmed=0')
        # A new client process cannot trust persisted observations from an old one.
        with self.db: self.db.execute('UPDATE uid_locations SET confirmed=0')

    def close(self):
        self.db.close()
        self._writer_lock.release()
        if self._migration_lock is not None:
            self._migration_lock.release()
            self._migration_lock = None

    def register(self, uid, name, remaining_mg):
        uid = canonical_uid(uid)
        if type(remaining_mg) is not int or remaining_mg < 0:
            raise ValueError('Balance must be a nonnegative integer in milligrams')
        existing = self.spool(uid)
        if existing:
            return existing # Re-registration must not reset a known spool's balance.
        with self.db:
            self.db.execute('INSERT INTO uid_spools VALUES(?,?,?,?)',
                            (uuid.uuid4().hex, uid, name, remaining_mg))
        return self.spool(uid)

    def spool(self, uid):
        row = self.db.execute('SELECT * FROM uid_spools WHERE uid=?', (canonical_uid(uid),)).fetchone()
        return dict(row) if row else None

    def reconcile(self, fleet):
        with self.db:
            return self._reconcile(fleet)

    def _reconcile(self, fleet):
        """Only fresh present/absent evidence replaces an old location claim.

        Offline, stale, unreadable, or a new epoch's unknown channels retain an
        uncertain claim. No automatic reassignment if its prior holder is offline.
        """
        self.db.execute('UPDATE uid_locations SET confirmed=0')
        for pid, snapshot in fleet.items():
            if pid != snapshot['printer_id']:
                raise ValueError('Printer identity mismatch')
            if snapshot['state'] != 'ready': continue
            for ch, observation in snapshot['channels'].items():
                if ch not in ('0', '1', '2', '3'): raise ValueError('Invalid channel')
                if observation['state'] == 'absent':
                    self.db.execute('DELETE FROM uid_locations WHERE printer_id=? AND channel=?',(pid,ch))
                elif observation['state'] == 'present':
                    uid = canonical_uid(observation['uid'])
                    self.db.execute('INSERT INTO uid_locations VALUES(?,?,?,1) ON CONFLICT(printer_id,channel) DO UPDATE SET uid=excluded.uid,confirmed=1',(pid,ch,uid))
        rows = [dict(r) for r in self.db.execute('SELECT * FROM uid_locations ORDER BY printer_id,channel')]
        counts = Counter(r['uid'] for r in rows)
        for row in rows:
            spool = self.spool(row['uid'])
            row['state'] = ('conflict' if counts[row['uid']] > 1 else
                            'uncertain' if not row['confirmed'] else
                            'recognized' if spool else 'needs_registration')
            row['spool'] = spool
            row['usable'] = row['state'] == 'recognized'
        return rows + self._manual_locations(fleet, rows)

    def register_manual(self, name, remaining_mg, *, spool_id=None, details=None):
        if not isinstance(name,str) or not name.strip() or type(remaining_mg) is not int or remaining_mg<0:
            raise ValueError('Invalid manual spool')
        sid = spool_id or uuid.uuid4().hex
        if not isinstance(sid,str) or not sid: raise ValueError('Invalid spool ID')
        old = self.db.execute('SELECT * FROM uid_spools WHERE spool_id=?',(sid,)).fetchone()
        if old:
            if old['uid'] is not None: raise ValueError('Spool ID already has a UID')
            return dict(old)
        details = dict(details or {})
        if 'calibration' in details:
            from spool_identity import calibration
            details['calibration']=calibration(details['calibration'])
            if details['calibration'].get('uid'): raise ValueError('Manual spool cannot claim a UID')
        payload=json.dumps(details,allow_nan=False)
        with self.db:
            self.db.execute('INSERT INTO uid_spools VALUES(?,NULL,?,?)',(sid,name,remaining_mg))
            self.db.execute('INSERT INTO spool_details VALUES(?,?)',(sid,payload))
        return dict(self.db.execute('SELECT * FROM uid_spools WHERE spool_id=?',(sid,)).fetchone())

    @staticmethod
    def connection_token(snapshot):
        return json.dumps([snapshot.get(k) for k in ('client_session','generation','epoch')])

    def _manual_locations(self, fleet, tagged):
        rows=[]
        for assignment in self.db.execute('SELECT * FROM manual_assignments').fetchall():
            row=dict(assignment); snapshot=fleet.get(row['printer_id'],{})
            obs=snapshot.get('channels',{}).get(row['channel'],{})
            conflict=any(r['printer_id']==row['printer_id'] and r['channel']==row['channel'] for r in tagged)
            if conflict:
                for tagged_row in tagged:
                    if tagged_row['printer_id']==row['printer_id'] and tagged_row['channel']==row['channel']:
                        tagged_row.update(usable=False,state='conflict')
            valid=(snapshot.get('state')=='ready' and row['token']==self.connection_token(snapshot)
                   and not conflict and obs.get('state') in ('absent','unreadable','unknown'))
            if not valid:
                self.db.execute('UPDATE manual_assignments SET confirmed=0 WHERE printer_id=? AND channel=?',(row['printer_id'],row['channel']))
                row['confirmed']=0
            row.update(uid=None,identity_mode='manual',state='manual_confirmed' if row['confirmed'] else 'manual_unconfirmed',usable=bool(row['confirmed']))
            row['spool']=dict(self.db.execute('SELECT * FROM uid_spools WHERE spool_id=?',(row['spool_id'],)).fetchone())
            rows.append(row)
        return rows

    def inventory_snapshot(self, printer_id, fleet):
        locations=self.reconcile(fleet)
        slots={str(i+1):'' for i in range(4)}
        for row in locations:
            if row['printer_id']==printer_id and row['usable']:
                slots[str(int(row['channel'])+1)]=row['spool']['spool_id']
        spools={}
        for row in self.db.execute('SELECT * FROM uid_spools'):
            detail=self.db.execute('SELECT payload FROM spool_details WHERE spool_id=?',(row['spool_id'],)).fetchone()
            value=json.loads(detail[0]) if detail else {}
            value.update(name=row['name'],remaining_g=row['remaining_mg']/1000,uid=row['uid'])
            spools[row['spool_id']]=value
        return {'slots':slots,'spools':spools,'runs':{}}
