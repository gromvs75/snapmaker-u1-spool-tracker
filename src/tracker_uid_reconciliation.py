"""Explicit local reconciliation. All reads and writes run on the SQLite owner."""
import hashlib
import json
import time


def encoded(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, ensure_ascii=False)


class Reconciliation:
    def __init__(self, recovery, accounting):
        self.recovery, self.accounting = recovery, accounting
        self.db = accounting.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS uid_recovery_decisions (
            request_id TEXT PRIMARY KEY, job_key TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL, result TEXT NOT NULL)''')
        self.db.commit()

    def preview(self, job_key, layer=None):
        p = self.recovery.preview(job_key, layer, manual=True)
        channels = list(p['ranges_mg'] or p['totals_mg'])
        if len(channels) != 1:
            raise ValueError('Ручная сверка нескольких инструментов пока недоступна.')
        if self.db.execute('SELECT 1 FROM uid_manual_resolutions WHERE job_key=?', (job_key,)).fetchone():
            raise ValueError('Задание уже закрыто вручную.')
        events = [json.loads(r[0]) for r in self.db.execute(
            'SELECT payload FROM uid_replacement_events WHERE job_key=? ORDER BY ordinal', (job_key,))]
        # Only spools actually bound to the job or observed in its replacement journal.
        ids = set(p['original_spools'].values())
        ids.update(e['new_spool_id'] for e in events if e.get('new_spool_id'))
        candidates = [dict(r) for r in self.db.execute('SELECT spool_id,uid,name,remaining_mg FROM uid_spools ORDER BY spool_id') if r['spool_id'] in ids]
        reservations = [dict(r) for r in self.db.execute(
            "SELECT t.spool_id,j.job_key FROM uid_job_tools t JOIN uid_jobs j USING(job_key) WHERE j.state='active' AND j.job_key<>? ORDER BY j.job_key,t.channel", (job_key,))]
        # Include spools newly observed by other active replacement journals, too.
        for r in self.db.execute("SELECT e.job_key,e.payload FROM uid_replacement_events e JOIN uid_jobs j USING(job_key) WHERE j.state='active' AND j.job_key<>? ORDER BY e.job_key,e.ordinal", (job_key,)):
            reservations.append(dict(job_key=r[0],spool_id=json.loads(r[1]).get('new_spool_id')))
        busy = {r['spool_id'] for r in reservations}
        for c in candidates:c['reserved'] = c['spool_id'] in busy
        p.update(channel=channels[0], candidates=candidates, replacements=events, layer=layer)
        p['revision'] = hashlib.sha256(encoded([p, reservations]).encode()).hexdigest()
        return p

    def apply(self, job_key, expected_revision, allocations_mg, note, request_id,
              confirmed=False, layer=None, *, observation, fleet):
        if confirmed is not True or not isinstance(note,str) or not 3 <= len(note.strip()) <= 2000:
            raise ValueError('Подтвердите распределение и укажите основание сверки.')
        if not isinstance(request_id,str) or not 8 <= len(request_id) <= 100:
            raise ValueError('Неверный идентификатор решения.')
        if not isinstance(allocations_mg,dict) or not allocations_mg or any(
                not isinstance(k,str) or type(v) is not int or not 0 <= v <= 100_000_000 for k,v in allocations_mg.items()):
            raise ValueError('Расход должен быть неотрицательным целым числом миллиграммов.')
        payload = encoded(dict(job_key=job_key,expected_revision=expected_revision,
            allocations_mg=allocations_mg,note=note,request_id=request_id,layer=layer))
        with self.accounting.transaction():
            old = self.db.execute('SELECT * FROM uid_recovery_decisions WHERE request_id=?',(request_id,)).fetchone()
            if old:
                if old['payload'] != payload:raise ValueError('Повтор решения с изменёнными данными.')
                return dict(json.loads(old['result']),status='duplicate')
            p = self.preview(job_key,layer)
            if p['revision'] != expected_revision:raise ValueError('Данные или остатки изменились. Откройте сверку заново.')
            candidates = {s['spool_id']:s for s in p['candidates']}
            if set(allocations_mg)-set(candidates):raise ValueError('Катушка не связана с этим заданием.')
            total = sum(allocations_mg.values())
            bounds = p['ranges_mg'][p['channel']] if p['ranges_mg'] else [sum(p['totals_mg'].values())]*2
            if not bounds[0] <= total <= bounds[1]:raise ValueError('Сумма распределения не совпадает с расчётом.')
            job = self.accounting.job(job_key)
            snapshot = fleet.get(job['printer_id'],{})
            if snapshot.get('state') != 'ready':raise ValueError('Восстановите соединение с принтером.')
            if observation.get('state') not in ('standby','complete','cancelled','error'):
                raise ValueError('Принтер печатает или на паузе. Дождитесь завершения.')
            checked = observation.get('checked_at')
            if type(checked) not in (int,float) or not 0 <= time.monotonic()-checked <= 3:
                raise ValueError('Проверка принтера устарела. Повторите сверку.')
            if observation.get('connection_token') != self.accounting.catalog.connection_token(snapshot):
                raise ValueError('Соединение изменилось. Повторите сверку.')
            receipt = dict(estimate_source='manual_reconciliation', underlying_source=p['basis'],
                history_status=p['history_status'], totals_by_spool_mg=allocations_mg,
                note=note.strip(), request_id=request_id, layer=layer, reviewed_at=time.time(),
                replacements=p['replacements'], observation=observation)
            for sid,amount in allocations_mg.items():
                if not amount:continue
                if candidates[sid]['reserved']:raise ValueError('Катушка используется другим незавершённым заданием.')
                changed = self.db.execute('UPDATE uid_spools SET remaining_mg=remaining_mg-? WHERE spool_id=? AND remaining_mg>=?', (amount,sid,amount))
                if changed.rowcount != 1:raise ValueError('Недостаточный остаток катушки. Списание отменено.')
                self.db.execute('INSERT INTO uid_debits VALUES(?,?,?,?)',(job_key,1,sid,amount))
                if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='uid_remote_links'").fetchone():
                    link = self.db.execute('SELECT * FROM uid_remote_links WHERE spool_id=?',(sid,)).fetchone()
                    if link:self.db.execute("INSERT INTO uid_remote_outbox VALUES(?,?,?,?,?,?,'held')", (job_key,1,sid,link['url'],link['remote_id'],amount))
            self.db.execute('UPDATE uid_job_tools SET used_mg=? WHERE job_key=? AND channel=?',(total,job_key,p['channel']))
            self.db.execute('INSERT INTO uid_usage_events VALUES(?,?,?)',(job_key,1,encoded(receipt)))
            self.db.execute('INSERT INTO uid_recovery_receipts VALUES(?,?)',(job_key,encoded(receipt)))
            state = 'completed' if p['history_status']=='completed' else 'cancelled'
            self.db.execute('UPDATE uid_jobs SET state=?,last_sequence=1,mapping_valid=0 WHERE job_key=?',(state,job_key))
            result = dict(status='applied',job_key=job_key,totals_by_spool_mg=allocations_mg)
            self.db.execute('INSERT INTO uid_recovery_decisions VALUES(?,?,?,?)',(request_id,job_key,payload,encoded(result)))
            return result
