"""Offline history inspection and explicit user-attested additional accounting.

This is not an automatic recovery rule. All operations execute on the SQLite
owner. A final manual decision fences late motion/history for this job.
"""
import hashlib
import json
import math
import time
from tracker_uid_reconciliation import encoded


class HistoryReview:
    def __init__(self, accounting):
        self.accounting = accounting
        self.db = accounting.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS uid_history_decisions (
            request_id TEXT PRIMARY KEY, job_key TEXT NOT NULL, action TEXT NOT NULL,
            payload TEXT NOT NULL, result TEXT NOT NULL, created_at REAL NOT NULL)''')
        self.db.commit()

    def detail(self, job_key):
        row = self.db.execute('SELECT * FROM uid_jobs WHERE job_key=?',(job_key,)).fetchone()
        if row is None: raise ValueError('Задание не найдено.')
        job = dict(row)
        capture = self.db.execute('SELECT * FROM uid_motion_captures WHERE key=?',(job_key,)).fetchone()
        capture = dict(capture) if capture else {}
        saved = self.db.execute('SELECT * FROM uid_recovery_profiles WHERE history_key=?',(capture.get('history_key'),)).fetchone()
        profile = json.loads(saved['profile']) if saved else None
        tools = [dict(r) for r in self.db.execute('SELECT * FROM uid_job_tools WHERE job_key=? ORDER BY channel',(job_key,))]
        debits = [dict(r) for r in self.db.execute('SELECT * FROM uid_debits WHERE job_key=? ORDER BY sequence,spool_id',(job_key,))]
        events = [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM uid_replacement_events WHERE job_key=? ORDER BY ordinal',(job_key,))]
        reasons = [r[0] for r in self.db.execute('SELECT reason FROM uid_motion_review WHERE job_key=?',(job_key,))]
        amounts = {}
        for d in debits: amounts[d['spool_id']] = amounts.get(d['spool_id'],0)+d['delta_mg']
        plan = []
        if profile:
            weights, mapping = profile.get('logical_weights',[]),profile.get('mapping',[])
            for i,weight in enumerate(weights):
                if type(weight) not in (int,float) or not math.isfinite(weight) or weight<=0 or i>=len(mapping): continue
                channel = str(mapping[i]); tool = next((t for t in tools if t['channel']==channel),{})
                sid = profile['legacy_spool_ids'][i] if profile.get('legacy_import') else tool.get('spool_id')
                plan.append(dict(logical_tool=i,channel=channel,spool_id=sid,planned_mg=round(weight*1000)))
                if profile.get('legacy_import'):
                    plan[-1]['mapping_verified'] = profile['legacy_mapping_verified']
        ids = {t['spool_id'] for t in tools}
        ids.update(e['new_spool_id'] for e in events if e.get('new_spool_id'))
        candidates = [dict(r) for r in self.db.execute('SELECT spool_id,name,uid,remaining_mg FROM uid_spools ORDER BY spool_id') if r['spool_id'] in ids]
        reservations = {r[0] for r in self.db.execute("SELECT t.spool_id FROM uid_job_tools t JOIN uid_jobs j USING(job_key) WHERE j.state='active' AND j.job_key<>?",(job_key,))}
        for r in self.db.execute("SELECT e.payload FROM uid_replacement_events e JOIN uid_jobs j USING(job_key) WHERE j.state='active' AND j.job_key<>?",(job_key,)):
            reservations.add(json.loads(r[0]).get('new_spool_id'))
        for s in candidates:
            s['accounted_mg'] = amounts.get(s['spool_id'],0)
            s['reserved'] = s['spool_id'] in reservations
            planned = sum(p['planned_mg'] for p in plan if p['spool_id']==s['spool_id'])
            # Never assign the full plan to the original spool across a swap.
            s['suggested_additional_mg'] = None if events or not plan or (profile or {}).get('legacy_import') else max(0,planned-s['accounted_mg'])
        remote = []
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='uid_remote_outbox'").fetchone():
            remote = [dict(r) for r in self.db.execute('SELECT * FROM uid_remote_outbox WHERE job_key=?',(job_key,))]
        decisions = [dict(r) for r in self.db.execute('SELECT * FROM uid_history_decisions WHERE job_key=? ORDER BY created_at',(job_key,))]
        receipt = self.db.execute('SELECT payload FROM uid_recovery_receipts WHERE job_key=?',(job_key,)).fetchone()
        value = dict(job=job,filename=capture.get('filename'),history=json.loads(capture['history']) if capture.get('history') else None,
            plan=plan,plan_source=profile,quarantined=bool(saved and saved['quarantined']),candidates=candidates,
            accounted_mg=sum(amounts.values()),debits=debits,replacements=events,reasons=reasons,remote_operations=remote,
            decisions=decisions,receipt=json.loads(receipt[0]) if receipt else None,
            uncertain=any(r['state'] in ('sending','uncertain') for r in remote))
        # Closing without a debit fences automatic replay, but does not prevent
        # a later explicit correction. A final accounting receipt is immutable.
        value['can_review'] = bool(not value['receipt'] and (
            job['state'] in ('resolved','cancelled') or
            job['state']=='active' and not job['mapping_valid'] or
            job['state']=='review' and job['source']=='legacy_import'))
        value['review_block'] = ('already_accounted' if value['receipt'] or job['state']=='completed'
                                else 'observing' if job['state']=='active' and job['mapping_valid']
                                else '' if value['can_review'] else 'unavailable')
        value['revision'] = hashlib.sha256(encoded(value).encode()).hexdigest()
        return value

    def decide(self, job_key, action, expected_revision, request_id, confirmed=False,
               allocations_mg=None, note='', completed=None, *, fleet, observation=None):
        if action not in ('defer','close','account'): raise ValueError('Неизвестное решение.')
        if not isinstance(request_id,str) or not 8<=len(request_id)<=100: raise ValueError('Неверный ID решения.')
        payload = encoded(dict(job_key=job_key,action=action,expected_revision=expected_revision,request_id=request_id,
            confirmed=confirmed,allocations_mg=allocations_mg,note=note,completed=completed))
        with self.accounting.transaction():
            old = self.db.execute('SELECT * FROM uid_history_decisions WHERE request_id=?',(request_id,)).fetchone()
            if old:
                if old['payload']!=payload: raise ValueError('Повтор решения с изменёнными данными.')
                return dict(json.loads(old['result']),status='duplicate')
            detail = self.detail(job_key)
            if detail['revision']!=expected_revision: raise ValueError('Данные изменились. Откройте задание заново.')
            if not detail['can_review']:
                raise ValueError('Задание уже закрыто или учтено.')
            if action!='defer':
                if confirmed is not True: raise ValueError('Подтвердите завершение задания и выбранное действие.')
                if detail['job']['state']=='active' and detail['job']['mapping_valid']: raise ValueError('Наблюдение продолжается. Сначала дождитесь завершения задания.')
                # Live collector evidence wins over a stale UI confirmation.
                snapshot=fleet.get(detail['job']['printer_id'],{})
                from tracker_printer_capabilities import printer_available
                if printer_available(snapshot):
                    observation=observation or {}
                    checked=observation.get('checked_at')
                    if (observation.get('state') not in ('standby','complete','cancelled','error')
                            or type(checked) not in (float,int) or not 0<=time.monotonic()-checked<=3
                            or observation.get('connection_token')!=self.accounting.catalog.connection_token(snapshot)):
                        raise ValueError('Принтер печатает, на паузе или проверка состояния устарела. Повторите после завершения.')
            if action=='account':
                if completed is not True: raise ValueError('Подтвердите: печать завершилась, продолжения не будет.')
                if not isinstance(note,str) or not 3<=len(note.strip())<=2000: raise ValueError('Укажите основание и исправления расхода.')
                if detail['uncertain']: raise ValueError('Сначала сверьте неопределённые отправки этого задания в Spoolman. Они уже включены в локальный расход.')
                if not isinstance(allocations_mg,dict) or not allocations_mg or any(type(v) is not int or not 0<=v<=100_000_000 for v in allocations_mg.values()):
                    raise ValueError('Укажите дополнительный расход в целых миллиграммах.')
                candidates = {s['spool_id']:s for s in detail['candidates']}
                if set(allocations_mg)-set(candidates): raise ValueError('Катушка не связана с заданием.')
                sequence = max([detail['job']['last_sequence']]+[d['sequence'] for d in detail['debits']])+1
                for sid,amount in allocations_mg.items():
                    if not amount: continue
                    if candidates[sid]['reserved']: raise ValueError('Катушка занята другим незавершённым заданием.')
                    changed=self.db.execute('UPDATE uid_spools SET remaining_mg=remaining_mg-? WHERE spool_id=? AND remaining_mg>=?',(amount,sid,amount))
                    if changed.rowcount!=1: raise ValueError('Недостаточный остаток. Все изменения отменены.')
                    self.db.execute('INSERT INTO uid_debits VALUES(?,?,?,?)',(job_key,sequence,sid,amount))
                    if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='uid_remote_links'").fetchone():
                        link=self.db.execute('SELECT * FROM uid_remote_links WHERE spool_id=?',(sid,)).fetchone()
                        if link:self.db.execute("INSERT INTO uid_remote_outbox VALUES(?,?,?,?,?,?,'held')",(job_key,sequence,sid,link['url'],link['remote_id'],amount))
                receipt=dict(estimate_source='manual_reconciliation',underlying_source='user_attested_saved_plan',
                    totals_by_spool_mg=allocations_mg,previously_accounted_mg=detail['accounted_mg'],note=note.strip(),
                    request_id=request_id,reviewed_at=time.time(),user_confirmed_completed=True,replacements=detail['replacements'])
                self.db.execute('INSERT INTO uid_usage_events VALUES(?,?,?)',(job_key,sequence,encoded(receipt)))
                self.db.execute('INSERT INTO uid_recovery_receipts VALUES(?,?)',(job_key,encoded(receipt)))
                self.db.execute("UPDATE uid_jobs SET state='completed',mapping_valid=0,last_sequence=? WHERE job_key=?",(sequence,job_key))
            elif action=='close':
                self.db.execute("UPDATE uid_jobs SET state='resolved',mapping_valid=0 WHERE job_key=?",(job_key,))
            result=dict(status='saved',action=action,job_key=job_key,additional_mg=sum((allocations_mg or {}).values()))
            self.db.execute('INSERT INTO uid_history_decisions VALUES(?,?,?,?,?,?)',(request_id,job_key,action,payload,encoded(result),time.time()))
            return result
