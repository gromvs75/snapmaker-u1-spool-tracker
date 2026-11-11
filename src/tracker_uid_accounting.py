"""Transactional multi-printer accounting over the UID catalog.

Explicit cumulative per-tool usage evidence, not total print progress * plan.
No network, legacy DB autodiscovery, Spoolman sends or hardware commands.
"""
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import time
from tracker_uid_client import canonical_uid


class AccountingConflict(ValueError): pass


def mg(grams):
    if isinstance(grams, bool): raise ValueError('Invalid mass')
    try: n = Decimal(str(grams))
    except InvalidOperation as exc: raise ValueError('Invalid mass') from exc
    if not n.is_finite() or n < 0: raise ValueError('Invalid mass')
    return int((n * 1000).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def job_key(printer_id, job_id, started_at):
    if not all(isinstance(v,str) and v for v in (printer_id,job_id,started_at)):
        raise ValueError('Persistent printer ID, history job ID and start token required')
    return hashlib.sha256(json.dumps([printer_id,job_id,started_at]).encode()).hexdigest()


class UidAccounting:
    def __init__(self, catalog):
        self.catalog = catalog
        self.db = catalog.db
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA busy_timeout=5000')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS manual_transfers (
                request_id TEXT PRIMARY KEY, payload TEXT NOT NULL, result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS uid_legacy_history (
                identity TEXT PRIMARY KEY, printer_id TEXT NOT NULL, job_id TEXT NOT NULL,
                start_time TEXT NOT NULL, legacy_key TEXT NOT NULL, status TEXT NOT NULL,
                payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS uid_jobs (
                job_key TEXT PRIMARY KEY, printer_id TEXT NOT NULL, job_id TEXT NOT NULL,
                started_at TEXT NOT NULL, state TEXT NOT NULL, source TEXT NOT NULL,
                last_sequence INTEGER NOT NULL DEFAULT -1, mapping_valid INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS uid_manual_resolutions (
                job_key TEXT PRIMARY KEY REFERENCES uid_jobs(job_key),
                expected_version TEXT NOT NULL, resolved_at REAL NOT NULL,
                observation TEXT NOT NULL, decision TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS uid_unlock_windows (
                job_key TEXT PRIMARY KEY REFERENCES uid_jobs(job_key), mode TEXT NOT NULL,
                deadline REAL, completed INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS uid_unlock_attempts (
                job_key TEXT NOT NULL, version TEXT NOT NULL, mode TEXT NOT NULL, result TEXT NOT NULL,
                PRIMARY KEY(job_key,version));
            CREATE TABLE IF NOT EXISTS uid_job_manual (
                job_key TEXT NOT NULL REFERENCES uid_jobs(job_key), channel TEXT NOT NULL,
                assignment_version TEXT NOT NULL, PRIMARY KEY(job_key,channel));
            CREATE TABLE IF NOT EXISTS uid_job_connections (
                job_key TEXT PRIMARY KEY REFERENCES uid_jobs(job_key), token TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS uid_job_tools (
                job_key TEXT NOT NULL REFERENCES uid_jobs(job_key), channel TEXT NOT NULL,
                spool_id TEXT NOT NULL REFERENCES uid_spools(spool_id), uid TEXT NOT NULL,
                used_mg INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(job_key,channel));
            CREATE TABLE IF NOT EXISTS uid_usage_events (
                job_key TEXT NOT NULL REFERENCES uid_jobs(job_key), sequence INTEGER NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(job_key,sequence));
            CREATE TABLE IF NOT EXISTS uid_debits (
                job_key TEXT NOT NULL, sequence INTEGER NOT NULL, spool_id TEXT NOT NULL,
                delta_mg INTEGER NOT NULL, PRIMARY KEY(job_key,sequence,spool_id));
            CREATE TABLE IF NOT EXISTS uid_legacy_import (
                import_key TEXT PRIMARY KEY, payload TEXT NOT NULL);
        ''')

    @contextmanager
    def transaction(self):
        if self.db.in_transaction: raise RuntimeError('Nested accounting transaction')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def import_legacy_snapshot(self, snapshot, uid_bindings):
        """Explicit snapshot only; preserves IDs and fields. Empty target required.

        Not a live migration: unfinished runs and remote sending mode are rejected.
        Backup/rollout of the installed application remains a separate operation.
        """
        if snapshot.get('spoolman',{}).get('mode') == 'send':
            raise AccountingConflict('Remote send mode needs a separate outbox migration')
        if snapshot.get('runs'):
            raise AccountingConflict('Legacy history needs an explicit deduplication migration; only empty-history fixtures supported')
        payload = json.dumps(snapshot,sort_keys=True,allow_nan=False)
        combined = json.dumps([snapshot,uid_bindings],sort_keys=True,allow_nan=False)
        key = hashlib.sha256(combined.encode()).hexdigest()
        rows=[]
        for sid,s in snapshot['spools'].items():
            uid=canonical_uid(uid_bindings[sid])
            rows.append((sid,uid,s['name'],mg(s['remaining_g'])))
        if len({r[1] for r in rows}) != len(rows):raise AccountingConflict('Duplicate UID')
        with self.transaction():
            if self.db.execute('SELECT 1 FROM uid_legacy_import WHERE import_key=?',(key,)).fetchone():return
            if self.db.execute('SELECT 1 FROM uid_spools').fetchone():raise AccountingConflict('Migration target must be empty')
            self.db.executemany('INSERT INTO uid_spools VALUES(?,?,?,?)',rows)
            # Full source retains material/color/settings/history for future migration.
            self.db.execute('INSERT INTO uid_legacy_import VALUES(?,?)',(key,payload))

    def observe(self, fleet):
        with self.transaction():
            locations = self.catalog._reconcile(fleet)
            for j in self.db.execute("SELECT * FROM uid_jobs WHERE state='active'").fetchall():
                snapshot = fleet.get(j['printer_id'], {})
                token = json.dumps([snapshot.get(k) for k in ('client_session','generation','epoch')])
                saved = self.db.execute('SELECT token FROM uid_job_connections WHERE job_key=?',(j['job_key'],)).fetchone()
                connection_changed = saved is None or saved[0] != token
                for t in self.db.execute('SELECT * FROM uid_job_tools WHERE job_key=?',(j['job_key'],)):
                    obs = snapshot.get('channels', {}).get(t['channel'], {})
                    # Age alone does not rebind an already running job. A real
                    # disappearance/change or connection gap invalidates continuity.
                    invalid = connection_changed or snapshot.get('state') != 'ready' or obs.get('state') in ('absent','conflict','unreadable','unknown')
                    if obs.get('state') == 'present' and obs.get('uid') != t['uid']:
                        invalid = True
                    manual=self.db.execute('SELECT assignment_version FROM uid_job_manual WHERE job_key=? AND channel=?',(j['job_key'],t['channel'])).fetchone()
                    if manual:
                        assignment=self.db.execute('SELECT * FROM manual_assignments WHERE printer_id=? AND channel=?',(j['printer_id'],t['channel'])).fetchone()
                        invalid=(connection_changed or snapshot.get('state')!='ready' or assignment is None or not assignment['confirmed'] or assignment['version']!=manual[0] or assignment['spool_id']!=t['spool_id'])
                    if invalid:
                        self.db.execute('UPDATE uid_jobs SET mapping_valid=0 WHERE job_key=?',(j['job_key'],))
        return locations

    def assign_manual(self, printer_id, channel, spool_id, fleet, *, confirmed=False, expected_version=None):
        if confirmed is not True or not isinstance(printer_id,str) or not printer_id or channel not in ('0','1','2','3'):
            raise ValueError('Explicit physical assignment confirmation required')
        with self.transaction():
            self._unlock_guard(printer_id,spool_id)
            rows=self.catalog._reconcile(fleet)
            current=self.db.execute('SELECT * FROM manual_assignments WHERE printer_id=? AND channel=?',(printer_id,channel)).fetchone()
            if expected_version is not None and (current['version'] if current else '')!=expected_version:
                raise AccountingConflict('Назначение изменилось. Обновите экран.')
            spool=self.db.execute('SELECT * FROM uid_spools WHERE spool_id=?',(spool_id,)).fetchone()
            if not spool or spool['uid'] is not None: raise AccountingConflict('Manual assignment requires a local untagged spool')
            snapshot=fleet.get(printer_id,{})
            obs=snapshot.get('channels',{}).get(channel,{})
            if snapshot.get('state')!='ready' or obs.get('state') not in ('absent','unreadable','unknown'):
                raise AccountingConflict('Connection or tag evidence conflicts with manual assignment')
            if any(r['printer_id']==printer_id and r['channel']==channel and r.get('identity_mode')!='manual' for r in rows):
                raise AccountingConflict('Unresolved UID location on this channel')
            if self.db.execute("SELECT 1 FROM uid_job_tools t JOIN uid_jobs j USING(job_key) WHERE j.state='active' AND (t.spool_id=? OR (j.printer_id=? AND t.channel=?))",(spool_id,printer_id,channel)).fetchone():
                raise AccountingConflict('Spool or channel reserved by active job')
            other=self.db.execute('SELECT * FROM manual_assignments WHERE spool_id=?',(spool_id,)).fetchone()
            if other and (other['printer_id'],other['channel'])!=(printer_id,channel):
                raise AccountingConflict('Explicitly release the previous manual location first')
            import uuid
            version=uuid.uuid4().hex
            self.db.execute('INSERT INTO manual_assignments VALUES(?,?,?,?,?,1) ON CONFLICT(printer_id,channel) DO UPDATE SET spool_id=excluded.spool_id,version=excluded.version,token=excluded.token,confirmed=1',
                            (printer_id,channel,spool_id,version,self.catalog.connection_token(snapshot)))
            self._complete_unlocks()
            return {'spool_id':spool_id,'version':version,'identity_mode':'manual'}

    def transfer_manual(self, spool_id, source_printer, source_channel, target_printer, target_channel,
                        expected_version, request_id, fleet, *, confirmed=False):
        if confirmed is not True or not isinstance(request_id,str) or not request_id or len(request_id)>128:
            raise ValueError('Подтвердите физический перенос катушки.')
        if target_channel not in ('0','1','2','3') or not target_printer:
            raise ValueError('Выберите принтер и головку.')
        payload=json.dumps([spool_id,source_printer,source_channel,target_printer,target_channel,expected_version])
        with self.transaction():
            old=self.db.execute('SELECT * FROM manual_transfers WHERE request_id=?',(request_id,)).fetchone()
            if old:
                if old['payload']!=payload: raise AccountingConflict('Повтор запроса с другими параметрами.')
                return json.loads(old['result'])
            self._unlock_guard(source_printer,spool_id);self._unlock_guard(target_printer,spool_id)
            rows=self.catalog._reconcile(fleet)
            source=self.db.execute('SELECT * FROM manual_assignments WHERE printer_id=? AND channel=?',(source_printer,source_channel)).fetchone()
            if not source or source['spool_id']!=spool_id or source['version']!=expected_version:
                raise AccountingConflict('Исходное назначение изменилось. Обновите экран.')
            if (source_printer,source_channel)==(target_printer,target_channel):raise AccountingConflict('Выберите другое место.')
            if self.db.execute("SELECT 1 FROM uid_jobs WHERE state='active' AND printer_id IN (?,?)",(source_printer,target_printer)).fetchone():
                raise AccountingConflict('Печать активна — перенос недоступен.')
            if self.db.execute("SELECT 1 FROM uid_job_tools t JOIN uid_jobs j USING(job_key) WHERE j.state='active' AND (t.spool_id=? OR (j.printer_id=? AND t.channel=?) OR (j.printer_id=? AND t.channel=?))",(spool_id,source_printer,source_channel,target_printer,target_channel)).fetchone():
                raise AccountingConflict('Перенос заблокирован: катушка или головка участвует в задании.')
            if fleet.get(source_printer,{}).get('state')!='ready':raise AccountingConflict('Исходный принтер недоступен.')
            if any(r['printer_id']==source_printer and r['channel']==source_channel and r.get('identity_mode')!='manual' for r in rows):
                raise AccountingConflict('На исходной головке конфликт RFID. Перенос не выполнен.')
            target=fleet.get(target_printer,{})
            if target.get('state')!='ready' or target.get('channels',{}).get(target_channel,{}).get('state') not in ('absent','unknown','unreadable'):
                raise AccountingConflict('Целевой принтер недоступен или есть конфликт RFID.')
            if any(r['printer_id']==target_printer and r['channel']==target_channel for r in rows):
                raise AccountingConflict('Целевая головка уже занята. Назначение не изменено.')
            import uuid
            version=uuid.uuid4().hex
            self.db.execute('UPDATE manual_assignments SET printer_id=?,channel=?,version=?,token=?,confirmed=1 WHERE spool_id=?',
                            (target_printer,target_channel,version,self.catalog.connection_token(target),spool_id))
            result={'spool_id':spool_id,'printer_id':target_printer,'channel':target_channel,'version':version}
            self.db.execute('INSERT INTO manual_transfers VALUES(?,?,?)',(request_id,payload,json.dumps(result)))
            self._complete_unlocks()
            return result

    def release_manual(self, printer_id, channel):
        with self.transaction():
            self.db.execute("UPDATE uid_jobs SET mapping_valid=0 WHERE state='active' AND printer_id=? AND job_key IN (SELECT job_key FROM uid_job_manual WHERE channel=?)",(printer_id,channel))
            self.db.execute('DELETE FROM manual_assignments WHERE printer_id=? AND channel=?',(printer_id,channel))

    def legacy_history(self, printer_id, job_id, started_at):
        from tracker_uid_migration import history_identity
        try: identity = history_identity(printer_id, job_id, started_at)
        except (ValueError, ArithmeticError): return None
        row = self.db.execute('SELECT * FROM uid_legacy_history WHERE identity=?', (identity,)).fetchone()
        return dict(row) if row else None

    def begin(self, printer_id, job_id, started_at, channels, source, fleet):
        if self.legacy_history(printer_id,job_id,started_at):
            raise AccountingConflict('Legacy history fenced; no automatic replay')
        key=job_key(printer_id,job_id,started_at)
        channels=list(channels)
        if not source or not isinstance(source,str) or not channels or len(set(channels))!=len(channels) or any(c not in ('0','1','2','3') for c in channels):
            raise ValueError('Invalid job binding')
        with self.transaction():
            rows=self.catalog._reconcile(fleet)
            old=self.db.execute('SELECT * FROM uid_jobs WHERE job_key=?',(key,)).fetchone()
            if old:
                prior={r['channel'] for r in self.db.execute('SELECT channel FROM uid_job_tools WHERE job_key=?',(key,))}
                if prior!=set(channels) or old['source']!=source:raise AccountingConflict('Job identity reused with different evidence')
                return key
            if self.db.execute("SELECT 1 FROM uid_jobs WHERE printer_id=? AND state='active'",(printer_id,)).fetchone():
                raise AccountingConflict('Printer already has an active job')
            self._unlock_guard(printer_id,starting=True)
            bindings=[]
            manual_bindings=[]
            for ch in channels:
                row=next((r for r in rows if r['printer_id']==printer_id and r['channel']==ch and r['usable']),None)
                if row is None:raise AccountingConflict('No unique confirmed spool for tool')
                sid=row['spool']['spool_id']
                self._unlock_guard(printer_id,sid,starting=True)
                if self.db.execute("SELECT 1 FROM uid_job_tools t JOIN uid_jobs j USING(job_key) WHERE t.spool_id=? AND j.state='active'",(sid,)).fetchone():
                    raise AccountingConflict('Spool reserved by another active job')
                bindings.append((key,ch,sid,row['uid'] or ''))
                if row.get('identity_mode')=='manual':manual_bindings.append((key,ch,row['version']))
            self.db.execute('INSERT INTO uid_jobs(job_key,printer_id,job_id,started_at,state,source) VALUES(?,?,?,?,?,?)',(key,printer_id,job_id,started_at,'active',source))
            token = json.dumps([fleet[printer_id].get(k) for k in ('client_session','generation','epoch')])
            self.db.execute('INSERT INTO uid_job_connections VALUES(?,?)',(key,token))
            self.db.executemany('INSERT INTO uid_job_tools(job_key,channel,spool_id,uid) VALUES(?,?,?,?)',bindings)
            self.db.executemany('INSERT INTO uid_job_manual VALUES(?,?,?)',manual_bindings)
        return key

    def unlock_state(self, key):
        row=self.db.execute('SELECT * FROM uid_unlock_windows WHERE job_key=?',(key,)).fetchone()
        if not row:return None
        return dict(row, expired=not row['completed'] and row['deadline'] is not None and time.time()>=row['deadline'])

    def resolution_version(self, job):
        window=self.unlock_state(job['job_key'])
        return hashlib.sha256(json.dumps([job['job_key'],job['state'],job['mapping_valid'],job['last_sequence'],window]).encode()).hexdigest()

    def _unlock_guard(self, printer_id, spool_id=None, *, starting=False):
        for r in self.db.execute('SELECT w.*,j.printer_id FROM uid_unlock_windows w JOIN uid_jobs j USING(job_key) WHERE w.completed=0'):
            involved=r['printer_id']==printer_id or (spool_id and self.db.execute('SELECT 1 FROM uid_job_tools WHERE job_key=? AND spool_id=?',(r['job_key'],spool_id)).fetchone())
            if involved and (starting or (r['deadline'] is not None and time.time()>=r['deadline'])):
                raise AccountingConflict('Окно подтверждения истекло. Снимите блокировку заново.' if not starting else 'Сначала переподтвердите назначения прерванного задания.')

    def _complete_unlocks(self):
        for r in self.db.execute('SELECT * FROM uid_unlock_windows WHERE completed=0').fetchall():
            if r['deadline'] is not None and time.time()>=r['deadline']:continue
            required=self.db.execute('SELECT t.spool_id FROM uid_job_tools t JOIN uid_job_manual m USING(job_key,channel) WHERE t.job_key=?',(r['job_key'],)).fetchall()
            if required and all(self.db.execute('SELECT 1 FROM manual_assignments WHERE spool_id=? AND confirmed=1',(x[0],)).fetchone() for x in required):
                self.db.execute('UPDATE uid_unlock_windows SET completed=1 WHERE job_key=?',(r['job_key'],))

    def resolve_interrupted(self, job_key, expected_version, observation, fleet, *, confirmed=False, accept_unaccounted=False, mode="until_assignment"):
        """Release a lost capture without inventing usage; permanently fence late usage.

        Observation is supplied by the trusted read-only transport, never the GUI
        payload. The user attests physical stop and accepts the unaccounted gap.
        """
        if confirmed is not True or accept_unaccounted is not True:
            raise AccountingConflict('Подтвердите остановку печати и неучтённый расход.')
        if mode not in ('15_minutes','until_assignment'):raise ValueError('Выберите режим разблокировки.')
        with self.transaction():
            attempt=self.db.execute('SELECT * FROM uid_unlock_attempts WHERE job_key=? AND version=?',(job_key,expected_version)).fetchone()
            if attempt:
                if attempt['mode']!=mode:raise AccountingConflict('Повтор запроса с другим режимом.')
                return json.loads(attempt['result'])
            old=self.db.execute('SELECT * FROM uid_manual_resolutions WHERE job_key=?',(job_key,)).fetchone()
            if old and not self.unlock_state(job_key):
                if old['expected_version']!=expected_version:raise AccountingConflict('Решение уже сохранено для другой версии задания.')
                return {'status':'resolved_without_debit','job_key':job_key}
            job=self.db.execute('SELECT * FROM uid_jobs WHERE job_key=?',(job_key,)).fetchone()
            if not job or self.resolution_version(job)!=expected_version:
                raise AccountingConflict('Задание изменилось. Обновите экран.')
            window=self.unlock_state(job_key)
            if not ((job['state']=='active' and not job['mapping_valid']) or (job['state']=='resolved' and window and window['expired'])):
                raise AccountingConflict('Разрешить можно только прерванное задание.')
            snapshot=fleet.get(job['printer_id'],{})
            if snapshot.get('state')!='ready':raise AccountingConflict('Принтер недоступен. Восстановите соединение.')
            if observation.get('state') not in ('standby','complete','cancelled','error'):
                raise AccountingConflict('Принтер печатает или приостановлен. Сначала остановите печать.')
            checked=observation.get('checked_at')
            if type(checked) not in (int,float) or not 0<=time.monotonic()-checked<=3:
                raise AccountingConflict('Проверка состояния устарела. Повторите проверку.')
            if observation.get('connection_token')!=self.catalog.connection_token(snapshot):
                raise AccountingConflict('Соединение изменилось. Повторите проверку.')
            self.db.execute('INSERT OR IGNORE INTO uid_manual_resolutions VALUES(?,?,?,?,?)',
                            (job_key,expected_version,time.time(),json.dumps(observation,sort_keys=True),'closed_without_additional_debit'))
            self.db.execute("UPDATE uid_jobs SET state='resolved',mapping_valid=0 WHERE job_key=?",(job_key,))
            # A released reservation is not renewed trust in the physical spool.
            self.db.execute('UPDATE manual_assignments SET confirmed=0 WHERE printer_id=? OR spool_id IN (SELECT spool_id FROM uid_job_tools WHERE job_key=?)',(job['printer_id'],job_key))
            deadline=time.time()+900 if mode=='15_minutes' else None
            revision=(window['revision'] if window else 0)+1
            completed=not self.db.execute('SELECT 1 FROM uid_job_manual WHERE job_key=?',(job_key,)).fetchone()
            self.db.execute('INSERT INTO uid_unlock_windows VALUES(?,?,?,?,?) ON CONFLICT(job_key) DO UPDATE SET mode=excluded.mode,deadline=excluded.deadline,completed=excluded.completed,revision=excluded.revision',(job_key,mode,deadline,int(completed),revision))
            result={'status':'resolved_without_debit','job_key':job_key,'mode':mode,'deadline':deadline}
            self.db.execute('INSERT INTO uid_unlock_attempts VALUES(?,?,?,?)',(job_key,expected_version,mode,json.dumps(result)))
            return result

    def apply(self, key, sequence, totals_mg, *, state, source, basis):
        """Atomic cumulative evidence. Cancellation requires executed usage.

        source identifies a stable capture/history evidence stream, not a socket.
        A reset/new source or invalidated identity needs explicit later review.
        """
        if type(sequence) is not int or sequence<0 or state not in ('active','completed','cancelled'):
            raise ValueError('Invalid event identity/state')
        if basis not in ('executed_gcode','motion_estimate','completed_gcode') or (basis=='completed_gcode' and state!='completed'):
            raise ValueError('Cancellation/progress require executed usage, not full plan')
        if not isinstance(totals_mg,dict) or any(type(v) is not int or v<0 for v in totals_mg.values()):
            raise ValueError('Expected cumulative integer milligrams per tool')
        payload=json.dumps([state,source,basis,totals_mg],sort_keys=True)
        with self.transaction():
            j=self.db.execute('SELECT * FROM uid_jobs WHERE job_key=?',(key,)).fetchone()
            if not j:raise AccountingConflict('No start-time spool binding')
            old=self.db.execute('SELECT payload FROM uid_usage_events WHERE job_key=? AND sequence=?',(key,sequence)).fetchone()
            if old:
                if old[0]!=payload:raise AccountingConflict('Event ID reused with different payload')
                return 'duplicate'
            tools=self.db.execute('SELECT * FROM uid_job_tools WHERE job_key=?',(key,)).fetchall()
            if set(totals_mg)!={t['channel'] for t in tools}:raise AccountingConflict('Missing or unexpected tool totals')
            if source!=j['source']:raise AccountingConflict('Usage source reset/changed')
            if sequence<j['last_sequence']:return 'out_of_order'
            if j['state']!='active':
                if j['state']==state and all(totals_mg[t['channel']]==t['used_mg'] for t in tools):return 'duplicate'
                raise AccountingConflict('Terminal job already accounted; review changed result')
            deltas={t['spool_id']:totals_mg[t['channel']]-t['used_mg'] for t in tools}
            if any(v<0 for v in deltas.values()):raise AccountingConflict('Cumulative counter decreased')
            if not j['mapping_valid'] and any(deltas.values()):raise AccountingConflict('Spool continuity lost; review additional consumption')
            for sid,amount in deltas.items():
                cur=self.db.execute('UPDATE uid_spools SET remaining_mg=remaining_mg-? WHERE spool_id=? AND remaining_mg>=?',(amount,sid,amount))
                if cur.rowcount!=1:raise AccountingConflict('Insufficient spool balance')
                self.db.execute('INSERT INTO uid_debits VALUES(?,?,?,?)',(key,sequence,sid,amount))
            for t in tools:
                self.db.execute('UPDATE uid_job_tools SET used_mg=? WHERE job_key=? AND channel=?',(totals_mg[t['channel']],key,t['channel']))
            self.db.execute('INSERT INTO uid_usage_events VALUES(?,?,?)',(key,sequence,payload))
            self.db.execute('UPDATE uid_jobs SET last_sequence=?,state=? WHERE job_key=?',(sequence,state,key))
        return 'applied'

    def job(self,key):
        row=self.db.execute('SELECT * FROM uid_jobs WHERE job_key=?',(key,)).fetchone()
        if not row:return None
        result=dict(row)
        result['tools']=[dict(r) for r in self.db.execute('SELECT * FROM uid_job_tools WHERE job_key=? ORDER BY channel',(key,))]
        return result


class TrackerUidService:
    """App integration boundary: one fleet and one catalog/accounting connection.

    Call on the controlling thread. Usage must come from the existing estimator
    or verified capture adapter; this class never invents grams from UID data.
    """
    def __init__(self, fleet, catalog):
        self.fleet=fleet
        self.accounting=UidAccounting(catalog)

    def begin(self, printer_id, job_id, started_at, channels, source):
        self.refresh()
        return self.accounting.begin(printer_id,job_id,started_at,channels,source,self.fleet.snapshot())

    def refresh(self):
        return self.accounting.observe(self.fleet.snapshot())

    def apply(self, key, sequence, totals_mg, **evidence):
        self.refresh()
        return self.accounting.apply(key,sequence,totals_mg,**evidence)


    def handle_event(self, printer_id, event):
        """Adapter for normalized events from a trusted per-printer usage producer.

        Raw print percentage or Moonraker total filament length is NOT sufficient
        for per-tool usage. Producer must supply executed cumulative tool totals.
        """
        key=job_key(printer_id,event['job_id'],event['started_at'])
        state=event['state']
        if state == 'started':
            if event['sequence'] != 0 or any(event['totals_mg'].values()):
                raise AccountingConflict('Start must be observed before consumption')
            key=self.begin(printer_id,event['job_id'],event['started_at'],list(event['totals_mg']),event['source'])
            state='active'
        return self.apply(key,event['sequence'],event['totals_mg'],state=state,source=event['source'],basis=event['basis'])
