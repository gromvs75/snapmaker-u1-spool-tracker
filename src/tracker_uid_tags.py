"""Observed RFID registration, serialized with accounting on the SQLite owner."""
import json
import time
import uuid
from tracker_uid_client import canonical_uid
from tracker_uid_library import revision
from tracker_uid_accounting import AccountingConflict,mg


class Tags:
    def __init__(self,accounting):
        self.accounting=accounting;self.catalog=accounting.catalog;self.db=accounting.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS uid_tag_registrations (
            request_id TEXT PRIMARY KEY, payload TEXT NOT NULL, receipt TEXT NOT NULL,
            registered_at REAL NOT NULL)''')
        self.db.commit()
    def _observed(self,printer_id,channel,uid,fleet,observation):
        uid=canonical_uid(uid)
        s=fleet.get(printer_id,{})
        if channel not in ('0','1','2','3') or s.get('state')!='ready':raise AccountingConflict('Нет свежей связи с принтером.')
        ch=s.get('channels',{}).get(channel,{})
        if ch.get('state')!='present' or ch.get('uid')!=uid:raise AccountingConflict('Метка изменилась или больше не читается.')
        checked=observation.get('checked_at')
        if (observation.get('state') not in ('standby','complete','cancelled','error') or type(checked) not in (int,float)
                or not 0<=time.monotonic()-checked<=3 or observation.get('connection_token')!=self.catalog.connection_token(s)):
            raise AccountingConflict('Нужна свежая проверка: печать остановлена, соединение не изменилось.')
        rows=self.catalog._reconcile(fleet)
        matches=[r for r in rows if r.get('uid')==uid]
        if len(matches)!=1 or matches[0].get('spool') or not matches[0].get('confirmed'):raise AccountingConflict('UID уже зарегистрирован, конфликтует или не подтверждён.')
        self._guard(printer_id)
        return uid,revision([printer_id,channel,uid,self.catalog.connection_token(s),ch.get('sequence')])
    def _guard(self,printer_id,spool_id=None):
        if self.db.execute("SELECT 1 FROM uid_jobs WHERE state='active' AND (printer_id=? OR job_key IN (SELECT job_key FROM uid_job_tools WHERE spool_id=?))",(printer_id,spool_id)).fetchone():
            raise AccountingConflict('Печать или прерванное задание блокирует регистрацию.')
        if self.db.execute('''SELECT 1 FROM uid_unlock_windows w JOIN uid_jobs j USING(job_key)
                WHERE w.completed=0 AND (j.printer_id=? OR j.job_key IN (SELECT job_key FROM uid_job_tools WHERE spool_id=?))''',(printer_id,spool_id)).fetchone():
            raise AccountingConflict('Сначала завершите подтверждение назначений прерванного задания.')
    def _candidate(self,row,printer_id,channel):
        if row['uid'] is not None:raise AccountingConflict('Катушка уже связана с другой меткой.')
        sid=row['spool_id'];self._guard(printer_id,sid)
        assignment=self.db.execute('SELECT * FROM manual_assignments WHERE spool_id=?',(sid,)).fetchone()
        if assignment and (assignment['printer_id'],assignment['channel'])!=(printer_id,channel):
            raise AccountingConflict('Сначала снимите прежнее ручное назначение этой катушки.')
        occupied=self.db.execute('SELECT spool_id FROM manual_assignments WHERE printer_id=? AND channel=?',(printer_id,channel)).fetchone()
        if occupied and occupied[0]!=sid:raise AccountingConflict('На головке вручную назначена другая катушка.')
        details=self.db.execute('SELECT payload FROM spool_details WHERE spool_id=?',(sid,)).fetchone()
        remote=self.db.execute('SELECT * FROM uid_remote_links WHERE spool_id=?',(sid,)).fetchone()
        return dict(row,revision=revision([dict(row),dict(assignment) if assignment else None,details[0] if details else None,dict(remote) if remote else None]))
    def preview(self,printer_id,channel,uid,*,fleet,observation):
        with self.accounting.transaction():
            uid,version=self._observed(printer_id,channel,uid,fleet,observation)
            candidates=[]
            for row in self.db.execute('SELECT * FROM uid_spools WHERE uid IS NULL ORDER BY name').fetchall():
                try:candidates.append(self._candidate(dict(row),printer_id,channel))
                except AccountingConflict:pass
            occupied=self.db.execute('SELECT 1 FROM manual_assignments WHERE printer_id=? AND channel=?',(printer_id,channel)).fetchone()
            return dict(uid=uid,printer_id=printer_id,channel=channel,observation_revision=version,candidates=candidates,can_create=not occupied)
    def register(self,printer_id,channel,uid,expected_observation,request_id,*,fleet,observation,
                 confirmed=False,spool_id=None,expected_spool=None,name=None,remaining_g=None,material=None):
        if confirmed is not True or not isinstance(request_id,str) or not 1<=len(request_id)<=128:raise ValueError('Подтвердите физическую метку на катушке.')
        payload=json.dumps([printer_id,channel,uid,expected_observation,spool_id,expected_spool,name,remaining_g,material],ensure_ascii=False,allow_nan=False)
        with self.accounting.transaction():
            old=self.db.execute('SELECT * FROM uid_tag_registrations WHERE request_id=?',(request_id,)).fetchone()
            if old:
                if old['payload']!=payload:raise AccountingConflict('Повтор запроса содержит другое решение.')
                return json.loads(old['receipt'])
            uid,version=self._observed(printer_id,channel,uid,fleet,observation)
            if version!=expected_observation:raise AccountingConflict('Сканирование или соединение изменилось. Откройте регистрацию заново.')
            if spool_id is not None:
                if any(v is not None for v in (name,remaining_g,material)):raise ValueError('Привязка не изменяет параметры и остаток существующей катушки.')
                row=self.db.execute('SELECT * FROM uid_spools WHERE spool_id=?',(spool_id,)).fetchone()
                if not row:raise AccountingConflict('Катушка больше не существует.')
                candidate=self._candidate(dict(row),printer_id,channel)
                if candidate['revision']!=expected_spool:raise AccountingConflict('Катушка или назначение изменились. Обновите выбор.')
                self.db.execute('UPDATE uid_spools SET uid=? WHERE spool_id=?',(uid,spool_id))
                self.db.execute('DELETE FROM manual_assignments WHERE spool_id=?',(spool_id,))
            else:
                if expected_spool is not None:raise ValueError('Неверный режим регистрации.')
                if self.db.execute('SELECT 1 FROM manual_assignments WHERE printer_id=? AND channel=?',(printer_id,channel)).fetchone():
                    raise AccountingConflict('На головке уже назначена катушка. Выберите её или снимите назначение.')
                if not isinstance(name,str) or not name.strip() or len(name)>100 or not isinstance(material,str) or not material.strip() or len(material)>100:
                    raise ValueError('Укажите название и материал катушки.')
                if remaining_g is None or remaining_g=='':raise ValueError('Укажите остаток в граммах.')
                spool_id=uuid.uuid4().hex
                self.db.execute('INSERT INTO uid_spools VALUES(?,?,?,?)',(spool_id,uid,name.strip(),mg(remaining_g)))
                self.db.execute('INSERT INTO spool_details VALUES(?,?)',(spool_id,json.dumps({'material':material.strip()})))
            row=dict(self.db.execute('SELECT * FROM uid_spools WHERE spool_id=?',(spool_id,)).fetchone())
            result=dict(row,status='registered',printer_id=printer_id,channel=channel)
            self.db.execute('INSERT INTO uid_tag_registrations VALUES(?,?,?,?)',(request_id,payload,json.dumps(result),time.time()))
            return result
