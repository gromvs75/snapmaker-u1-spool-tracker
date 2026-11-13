"""Durable Spoolman delivery state. Only called on AccountingOwner's thread.

Every open quarantines nonterminal entries. This intentionally sacrifices
unattended resume so an old SQLite backup cannot silently replay a remote use.
HTTP has no exactly-once guarantee: uncertain writes require human evidence.
"""
import hashlib
import json
import uuid
from tracker_uid_accounting import AccountingConflict

KEYS = ('job_key', 'sequence', 'spool_id')


def operation_id(row):
    return hashlib.sha256(json.dumps([row[k] for k in KEYS]).encode()).hexdigest()


class Delivery:
    def __init__(self, accounting):
        self.accounting = accounting
        self.db = accounting.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS uid_delivery_meta (
                operation_id TEXT PRIMARY KEY, revision TEXT NOT NULL, attempt TEXT);
            CREATE TABLE IF NOT EXISTS uid_delivery_audit (
                id INTEGER PRIMARY KEY, operation_id TEXT NOT NULL, previous TEXT NOT NULL,
                state TEXT NOT NULL, note TEXT NOT NULL, attempt TEXT);
            CREATE TABLE IF NOT EXISTS uid_delivery_decisions (
                request_id TEXT PRIMARY KEY, payload TEXT NOT NULL, receipt TEXT NOT NULL);
        ''')
        with self.accounting.transaction():
            for row in self._rows():
                if row['state'] in ('held', 'pending', 'sending'):
                    self._transition(row, 'uncertain', 'Process reopened: reconcile before any send')

    def _rows(self):
        rows=[]
        for record in self.db.execute('SELECT * FROM uid_remote_outbox ORDER BY rowid').fetchall():
            row=dict(record);oid=operation_id(row)
            self.db.execute('INSERT OR IGNORE INTO uid_delivery_meta VALUES(?,?,NULL)',(oid,uuid.uuid4().hex))
            meta=self.db.execute('SELECT * FROM uid_delivery_meta WHERE operation_id=?',(oid,)).fetchone()
            row.update(dict(meta));rows.append(row)
        return rows

    def _transition(self, row, state, note, attempt=None):
        self.db.execute('UPDATE uid_remote_outbox SET state=? WHERE job_key=? AND sequence=? AND spool_id=?',
                        (state,*(row[k] for k in KEYS)))
        rev=uuid.uuid4().hex
        self.db.execute('UPDATE uid_delivery_meta SET revision=?,attempt=? WHERE operation_id=?',(rev,attempt,row['operation_id']))
        self.db.execute('INSERT INTO uid_delivery_audit(operation_id,previous,state,note,attempt) VALUES(?,?,?,?,?)',
                        (row['operation_id'],row['state'],state,note,attempt))
        return dict(row,state=state,revision=rev,attempt=attempt)

    def list(self):
        with self.accounting.transaction():return self._rows()

    def audit(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM uid_delivery_audit ORDER BY id')]

    def decide(self, operation_id, expected_revision, decision, note, request_id, confirmed=False):
        if (confirmed is not True or decision not in ('approve','applied','not_applied','cancel')
                or not isinstance(note,str) or not note.strip() or len(note)>1000
                or not isinstance(request_id,str) or not request_id or len(request_id)>128):
            raise ValueError('Explicit decision, confirmation and verification note required')
        payload=json.dumps([operation_id,expected_revision,decision,note],ensure_ascii=False)
        with self.accounting.transaction():
            old=self.db.execute('SELECT * FROM uid_delivery_decisions WHERE request_id=?',(request_id,)).fetchone()
            if old:
                if old['payload']!=payload:raise AccountingConflict('Decision request reused with different parameters')
                return json.loads(old['receipt'])
            row=next((r for r in self._rows() if r['operation_id']==operation_id),None)
            if not row or row['revision']!=expected_revision:raise AccountingConflict('Operation changed; refresh before resolving')
            allowed=('approve','cancel') if row['state']=='held' else ('applied','not_applied','cancel') if row['state']=='uncertain' else ()
            if decision not in allowed:raise AccountingConflict('This operation cannot be resolved in its current state')
            state={'approve':'pending','not_applied':'pending','applied':'sent','cancel':'resolved'}[decision]
            result=self._transition(row,state,'Manual '+decision+': '+note.strip())
            self.db.execute('INSERT INTO uid_delivery_decisions VALUES(?,?,?)',(request_id,payload,json.dumps(result)))
            return result

    def claim(self, operation_id, expected_revision):
        with self.accounting.transaction():
            rows=self._rows()
            if any(r['state'] in ('sending','uncertain') for r in rows):return None
            row=next((r for r in rows if r['operation_id']==operation_id),None)
            if not row or row['state']!='pending' or row['revision']!=expected_revision:return None
            debit=self.db.execute('SELECT delta_mg FROM uid_debits WHERE job_key=? AND sequence=? AND spool_id=?',tuple(row[k] for k in KEYS)).fetchone()
            link=self.db.execute('SELECT url,remote_id FROM uid_remote_links WHERE spool_id=?',(row['spool_id'],)).fetchone()
            if (not debit or debit[0]!=row['delta_mg'] or row['delta_mg']<=0 or not link
                    or tuple(link)!=(row['url'],row['remote_id'])):
                self._transition(row,'uncertain','Ledger or external identity mismatch');return None
            return self._transition(row,'sending','Durable claim before HTTP',uuid.uuid4().hex)

    def finish(self, operation_id, attempt, sent):
        if type(sent) is not bool:raise ValueError('Invalid completion')
        with self.accounting.transaction():
            row=next((r for r in self._rows() if r['operation_id']==operation_id),None)
            if not row or row['state']!='sending' or row['attempt']!=attempt:
                raise AccountingConflict('Stale delivery completion')
            return self._transition(row,'sent' if sent else 'uncertain',
                                    'Validated response' if sent else 'Write outcome unknown',attempt)
