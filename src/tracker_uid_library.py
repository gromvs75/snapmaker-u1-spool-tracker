"""Catalog commands executed only by AccountingOwner's SQLite thread.

External identity is (server URL, spool ID), never a display name. External
consumption starts held; explicit delivery approval is handled by Delivery.
"""
import hashlib
import json
import time
import uuid
import math
import re
from tracker_uid_accounting import AccountingConflict, mg
from tracker_uid_spoolman import endpoint


def revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def search_items(items, query):
    terms = str(query).casefold().split()
    return [item for item in items if all(term in ' '.join(str(item.get(k) or '') for k in
        ('id', 'name', 'manufacturer', 'filament_name', 'material')).casefold() for term in terms)]


class Library:
    def __init__(self, accounting):
        self.accounting = accounting
        self.catalog = accounting.catalog
        self.db = accounting.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS uid_preferences (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS uid_remote_catalog (url TEXT PRIMARY KEY, revision TEXT NOT NULL,
                checked_at REAL NOT NULL, available INTEGER NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS uid_remote_links (spool_id TEXT PRIMARY KEY REFERENCES uid_spools(spool_id),
                url TEXT NOT NULL, remote_id INTEGER NOT NULL, UNIQUE(url,remote_id));
            CREATE TABLE IF NOT EXISTS uid_remote_outbox (job_key TEXT NOT NULL, sequence INTEGER NOT NULL,
                spool_id TEXT NOT NULL, url TEXT NOT NULL, remote_id INTEGER NOT NULL,
                delta_mg INTEGER NOT NULL, state TEXT NOT NULL,
                PRIMARY KEY(job_key,sequence,spool_id));
            CREATE TABLE IF NOT EXISTS uid_export_plans (plan_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL, created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS uid_inventory_edits (request_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL, result TEXT NOT NULL, created_at REAL NOT NULL);
        ''')

    def settings(self):
        data={r['key']:json.loads(r['payload']) for r in self.db.execute('SELECT * FROM uid_preferences')}
        return {'values':data, 'revision':revision(data)}

    def save_settings(self, values, expected_revision):
        if not isinstance(values,dict) or set(values)-{'printer_names','spoolman_url','spoolman_mode','printers','slice_root','safety_margin_g','selected_printer','language','guard_modes','rfid'}:
            raise ValueError('Неверные настройки.')
        if 'rfid' in values:
            from tracker_rfid_metadata import validate_config
            validate_config(values['rfid'])
        if 'guard_modes' in values and (not isinstance(values['guard_modes'],dict) or any(not isinstance(k,str) or v not in ('off','warn','strict') for k,v in values['guard_modes'].items())):raise ValueError('Invalid guard modes')
        if 'language' in values and values['language'] not in ('en','ru','de','uk','es'):
            raise ValueError('Unsupported language')
        if 'spoolman_mode' in values and values['spoolman_mode'] not in ('off','read','send'):raise ValueError('Invalid Spoolman mode')
        if 'safety_margin_g' in values:
            # Same input precision as inventory; display rounding is not storage rounding.
            values=dict(values,safety_margin_g=mg(values['safety_margin_g'])/1000)
        if 'selected_printer' in values:
            printers=values.get('printers',self.settings()['values'].get('printers',[]))
            if values['selected_printer'] not in {p['id'] for p in printers}:
                raise ValueError('Выберите сохранённый принтер.')
        if 'slice_root' in values and (not isinstance(values['slice_root'],str) or len(values['slice_root'])>4096):
            raise ValueError('Неверный каталог нарезки.')
        if 'printers' in values:
            from tracker_uid_settings import validate_printers
            values=dict(values,printers=validate_printers(values['printers']))
        names=values.get('printer_names',{})
        if not isinstance(names,dict) or any(not isinstance(k,str) or not isinstance(v,str) or not v.strip() or len(v)>100 for k,v in names.items()):
            raise ValueError('Неверное имя принтера.')
        if values.get('spoolman_url'):values=dict(values,spoolman_url=endpoint(values['spoolman_url']))
        with self.accounting.transaction():
            if self.settings()['revision']!=expected_revision:raise AccountingConflict('Настройки изменились. Обновите экран.')
            if 'printers' in values:
                endpoints = {p['id']: p['url'] for p in values['printers']}
                for previous in self.settings()['values'].get('printers', []):
                    if endpoints.get(previous['id']) != previous['url']:
                        self.db.execute("UPDATE manual_assignments SET confirmed=0,token='revoked' WHERE printer_id=?",
                                        (previous['id'],))
            for k,v in values.items():self.db.execute('INSERT OR REPLACE INTO uid_preferences VALUES(?,?)',(k,json.dumps(v)))
        return self.settings()

    def forecast_inventory(self, *, fleet):
        """One owner-thread snapshot for all forecast consumers; no balance writes."""
        settings=self.settings()['values']
        locations=self.catalog.reconcile(fleet)
        spools={s['spool_id']:s for s in self.snapshot()['spools']}
        uncertain={r[0] for r in self.db.execute("SELECT spool_id FROM uid_remote_outbox WHERE state IN ('sending','uncertain')")}
        printers={}
        for p in settings.get('printers',[]):
            heads=[]
            for ch in range(4):
                matches=[r for r in locations if r['printer_id']==p['id'] and r['channel']==str(ch)]
                row=matches[0] if len(matches)==1 else None
                spool=spools.get((row.get('spool') or {}).get('spool_id')) if row else None
                heads.append(dict(channel=str(ch),spool=spool,
                    usable=bool(row and row['usable'] and spool and spool['spool_id'] not in uncertain),
                    # Saved positions support a provisional forecast, never accounting.
                    forecast_usable=bool(row and row['state'] in ('recognized','manual_confirmed','manual_unconfirmed','uncertain')
                                         and spool and not spool['details'].get('archived') and spool['spool_id'] not in uncertain),
                    reason=('Отправка Spoolman требует сверки' if spool and spool['spool_id'] in uncertain
                            else '' if row and row['usable'] else 'Назначение не подтверждено' if row else 'Катушка не назначена')))
            printers[p['id']]=dict(id=p['id'],name=settings.get('printer_names',{}).get(p['id'],p['name']),heads=heads)
        accounted={}
        for row in self.db.execute("SELECT p.profile FROM uid_recovery_profiles p JOIN uid_motion_captures c ON c.history_key=p.history_key JOIN uid_jobs j ON j.job_key=c.key WHERE j.state='completed'"):
            profile=json.loads(row[0]);digest=profile.get('file_sha256')
            if digest:accounted[digest]=max(accounted.get(digest,0),profile.get('started_at',0))
        return dict(printers=printers,selected_printer=settings.get('selected_printer'),
                    safety_margin_g=settings.get('safety_margin_g',5),accounted=accounted)

    def export_preview(self, plan, *, fleet):
        from tracker_uid_forecast import forecast_entry
        if (not isinstance(plan,dict) or set(plan)!={'filename','file_sha256','weights','source','completed_at_ns'}
                or not isinstance(plan['filename'],str) or not 0<len(plan['filename'])<=500
                or not isinstance(plan['source'],str) or len(plan['source'])>4096
                or not isinstance(plan['file_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',plan['file_sha256'])
                or type(plan['completed_at_ns']) is not int or plan['completed_at_ns']<=0
                or not isinstance(plan['weights'],list) or len(plan['weights'])!=4
                or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=100000 for v in plan['weights'])):
            raise ValueError('Неверный план экспорта.')
        inventory=self.forecast_inventory(fleet=fleet)
        pid=inventory['selected_printer']
        if pid not in inventory['printers']:pid=next(iter(inventory['printers']),'')
        forecast=forecast_entry(dict(plan,state='ready'))
        context=dict(printer_id=pid,forecast=forecast,reserve=inventory['safety_margin_g'])
        return dict(context,revision=revision([plan,context]))

    def export_save(self, plan, expected_revision, confirmed, *, fleet):
        if confirmed is not True:raise ValueError('Подтвердите экспорт.')
        with self.accounting.transaction():
            preview=self.export_preview(plan,fleet=fleet)
            if preview['revision']!=expected_revision:
                raise AccountingConflict('Назначение или остаток изменились. Повторите экспорт.')
            payload=dict(plan,**preview,mapping_assumed=False)
            key=revision(payload)
            old=self.db.execute('SELECT 1 FROM uid_export_plans WHERE plan_id=?',(key,)).fetchone()
            self.db.execute('INSERT OR IGNORE INTO uid_export_plans VALUES(?,?,?)',(key,json.dumps(payload),time.time()))
        return dict(plan_id=key,status='duplicate' if old else 'saved')

    def update_spool(self, spool_id, changes, expected_revision, request_id, confirmed, note):
        """Restore local weight/color editing; retain identity and accounting ledger."""
        if (confirmed is not True or not isinstance(changes,dict) or not changes
                or set(changes)-{'remaining_g','color'} or not isinstance(request_id,str)
                or not 1<=len(request_id)<=128 or not isinstance(note,str) or not 3<=len(note.strip())<=2000):
            raise ValueError('Подтвердите изменение и укажите основание.')
        if 'color' in changes and changes['color'] not in (None,'') and (not isinstance(changes['color'],str) or not re.fullmatch('#[0-9a-fA-F]{6}',changes['color'])):
            raise ValueError('Неверный цвет.')
        amount=mg(changes['remaining_g']) if 'remaining_g' in changes else None
        if amount is not None and amount>100_000_000:raise ValueError('Остаток слишком велик.')
        payload=json.dumps([spool_id,changes,expected_revision,note],sort_keys=True,allow_nan=False)
        with self.accounting.transaction():
            old=self.db.execute('SELECT payload,result FROM uid_inventory_edits WHERE request_id=?',(request_id,)).fetchone()
            if old:
                if old['payload']!=payload:raise AccountingConflict('Повтор запроса содержит другое изменение.')
                return dict(json.loads(old['result']),status='duplicate')
            result=self._edit_spool(spool_id,changes,expected_revision,amount)
            self.db.execute('INSERT INTO uid_inventory_edits VALUES(?,?,?,?)',(request_id,payload,json.dumps(result),time.time()))
        return result

    def _edit_spool(self, spool_id, changes, expected_revision, amount):
        # Internal: caller owns the SQLite transaction and validates the inputs.
        spool=next((s for s in self.snapshot()['spools'] if s['spool_id']==spool_id),None)
        if spool is None or spool['revision']!=expected_revision:raise AccountingConflict('Катушка изменилась. Откройте её заново.')
        if spool['remote']:raise AccountingConflict('Остаток и цвет этой катушки изменяются в Spoolman.')
        if amount is not None:
            self.accounting._unlock_guard('',spool_id,starting=True)
            active=self.db.execute("SELECT 1 FROM uid_jobs j JOIN uid_job_tools t USING(job_key) WHERE j.state='active' AND t.spool_id=?",(spool_id,)).fetchone()
            if not active and self.db.execute("SELECT 1 FROM sqlite_master WHERE name='uid_replacement_events'").fetchone():
                active=any(spool_id in (e.get('old_spool_id'),e.get('new_spool_id')) for e in
                    (json.loads(r[0]) for r in self.db.execute("SELECT e.payload FROM uid_replacement_events e JOIN uid_jobs j USING(job_key) WHERE j.state='active'")))
            if active:raise AccountingConflict('Сначала завершите или разрешите задание этой катушки.')
            self.db.execute('UPDATE uid_spools SET remaining_mg=? WHERE spool_id=?',(amount,spool_id))
        if 'color' in changes:
            details=dict(spool['details'],color=changes['color'])
            self.db.execute('INSERT OR REPLACE INTO spool_details VALUES(?,?)',(spool_id,json.dumps(details)))
        result=dict(spool_id=spool_id,previous_mg=spool['remaining_mg'],remaining_mg=amount if amount is not None else spool['remaining_mg'],status='saved')
        return result

    def catalog_refresh_context(self, url):
        url = endpoint(url)
        cached = self.db.execute('SELECT revision FROM uid_remote_catalog WHERE url=?', (url,)).fetchone()
        settings = self.settings()['values']
        targets = {}
        if url == settings.get('spoolman_url') and settings.get('spoolman_mode', 'read') != 'off':
            active_replacements = set()
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='uid_replacement_events'").fetchone():
                for row in self.db.execute("""SELECT e.payload FROM uid_replacement_events e JOIN uid_jobs j USING(job_key)
                                              WHERE j.state='active'"""):
                    event = json.loads(row[0])
                    active_replacements.update((event.get('old_spool_id'), event.get('new_spool_id')))
            for row in self.db.execute("""
                SELECT s.spool_id, s.remaining_mg, l.remote_id,
                       (SELECT COUNT(*) FROM uid_remote_outbox o WHERE o.spool_id=s.spool_id) AS deliveries
                FROM uid_remote_links l JOIN uid_spools s USING(spool_id)
                WHERE l.url=?
                AND NOT EXISTS (
                    SELECT 1 FROM uid_remote_outbox o WHERE o.spool_id=s.spool_id AND o.state<>'sent'
                )
                AND NOT EXISTS (
                    SELECT 1 FROM uid_job_tools t JOIN uid_jobs j USING(job_key)
                    WHERE t.spool_id=s.spool_id AND j.state='active'
                )
            """, (url,)):
                if row['spool_id'] not in active_replacements:
                    targets[row['spool_id']] = (row['remote_id'], row['remaining_mg'], row['deliveries'])
        return (cached[0] if cached else '', targets)

    def cache_catalog(self, url, items=None, *, refresh_context=None):
        url=endpoint(url)
        if items is not None and (not isinstance(items,dict) or any(str(v['id'])!=k for k,v in items.items())):
            raise ValueError('Invalid remote catalog')
        with self.accounting.transaction():
            cached_revision, targets = self.catalog_refresh_context(url)
            expected_revision, original_targets = refresh_context if refresh_context is not None else (cached_revision, targets)
            if cached_revision == expected_revision:
                self.db.execute('INSERT OR REPLACE INTO uid_remote_catalog VALUES(?,?,?,?,?)',
                    (url,uuid.uuid4().hex,time.time(),int(items is not None),json.dumps(items or {},allow_nan=False)))
                for sid, target in targets.items():
                    # A read in flight can overlap a debit, delivery or assignment.
                    # Only rebase spools that were eligible throughout this refresh.
                    if target != original_targets.get(sid):
                        continue
                    remote_id, remaining_mg, _ = target
                    item = (items or {}).get(str(remote_id))
                    if item and not item['archived'] and item['remaining_g'] is not None:
                        amount = mg(item['remaining_g'])
                        if amount != remaining_mg:
                            self.db.execute('UPDATE uid_spools SET remaining_mg=? WHERE spool_id=?', (amount, sid))
        return self.remote_catalog(url)

    def remote_catalog(self, url, query=''):
        row=self.db.execute('SELECT * FROM uid_remote_catalog WHERE url=?',(url,)).fetchone()
        if not row:return {'available':False,'revision':'','items':[]}
        return {'available':bool(row['available']) and 0<=time.time()-row['checked_at']<300,
                'revision':row['revision'],'items':search_items(list(json.loads(row['payload']).values()),query)}

    def remote_item(self, url, remote_id, expected_revision):
        if type(remote_id) is not int or remote_id<=0:raise ValueError('Выберите катушку Spoolman.')
        catalog=self.remote_catalog(url)
        if not catalog['available'] or catalog['revision']!=expected_revision:
            raise AccountingConflict('Каталог недоступен или устарел. Обновите Spoolman.')
        item=next((i for i in catalog['items'] if i['id']==remote_id),None)
        if item is None or item['archived']:raise AccountingConflict('Катушка недоступна.')
        return item

    def compare_name(self, spool_id):
        link=self.db.execute('SELECT * FROM uid_remote_links WHERE spool_id=?',(spool_id,)).fetchone()
        if not link:raise ValueError('Нет связи Spoolman.')
        spool=dict(self.db.execute('SELECT * FROM uid_spools WHERE spool_id=?',(spool_id,)).fetchone())
        catalog=self.remote_catalog(link['url'])
        item=self.remote_item(link['url'],link['remote_id'],catalog['revision'])
        return {'spool_id':spool_id,'local_name':spool['name'],'remote_name':item['name'],
                'different':spool['name']!=item['name'],
                'revision':revision([spool['name'],dict(link),catalog['revision']])}

    def rename_from_remote(self, spool_id, expected_revision, confirmed):
        if confirmed is not True:raise ValueError('Подтвердите обновление имени.')
        with self.accounting.transaction():
            comparison=self.compare_name(spool_id)
            if comparison['revision']!=expected_revision:raise AccountingConflict('Имя или каталог изменились. Обновите сравнение.')
            self.db.execute('UPDATE uid_spools SET name=? WHERE spool_id=?',(comparison['remote_name'],spool_id))
        return {'name':comparison['remote_name']}

    def create(self, name, remaining_g, *, fleet, details=None, assignment=None, remote=None):
        with self.accounting.transaction():
            return self._create(name,remaining_g,fleet=fleet,details=details,assignment=assignment,remote=remote)

    def _create(self, name, remaining_g, *, fleet, details=None, assignment=None, remote=None):
        # Validate everything before INSERT, then create + assign in one transaction.
        if not isinstance(name,str) or not name.strip() or len(name)>100:raise ValueError('Укажите имя катушки.')
        amount=mg(remaining_g);details=dict(details or {})
        if set(details)-{'material','color'} or any(not isinstance(v,str) or len(v)>100 for v in details.values()):raise ValueError('Неверные параметры катушки.')
        sid=uuid.uuid4().hex
        if remote:
            item=self.remote_item(remote['url'],remote['id'],remote['revision'])
            if item['remaining_g'] is None:raise ValueError('Остаток Spoolman неизвестен.')
            name=item['name'];amount=mg(item['remaining_g']);details.update(material=item['material'],color=item['color'] or '')
            if self.db.execute('SELECT 1 FROM uid_remote_links WHERE url=? AND remote_id=?',(remote['url'],remote['id'])).fetchone():
                raise AccountingConflict('Эта катушка Spoolman уже есть в библиотеке.')
        self.db.execute('INSERT INTO uid_spools VALUES(?,NULL,?,?)',(sid,name.strip(),amount))
        self.db.execute('INSERT INTO spool_details VALUES(?,?)',(sid,json.dumps(details)))
        if remote:self.db.execute('INSERT INTO uid_remote_links VALUES(?,?,?)',(sid,remote['url'],remote['id']))
        result={'spool_id':sid}
        if assignment:
            if set(assignment)!={'printer_id','channel','expected_version','confirmed'} or not isinstance(assignment['expected_version'],str) or assignment['confirmed'] is not True or assignment['channel'] not in ('0','1','2','3'):
                raise ValueError('Подтвердите физическое назначение.')
            result.update(self.accounting._assign_manual(assignment['printer_id'],assignment['channel'],sid,fleet,assignment['expected_version']))
        return result

    def detach(self, printer_id, channel, expected_version, confirmed, *, fleet):
        if confirmed is not True:raise ValueError('Подтвердите снятие катушки.')
        with self.accounting.transaction():
            row=self.db.execute('SELECT * FROM manual_assignments WHERE printer_id=? AND channel=?',(printer_id,channel)).fetchone()
            if not row or row['version']!=expected_version:raise AccountingConflict('Назначение изменилось.')
            self.accounting._unlock_guard(printer_id,row['spool_id'])
            from tracker_printer_capabilities import manual_edit_available
            if not manual_edit_available(fleet.get(printer_id,{})) or self.db.execute("SELECT 1 FROM uid_jobs WHERE state='active' AND printer_id=?",(printer_id,)).fetchone():
                raise AccountingConflict('Снятие недоступно: нет связи или печать активна.')
            self.db.execute('DELETE FROM manual_assignments WHERE printer_id=? AND channel=?',(printer_id,channel))
        return {'status':'detached'}

    def snapshot(self):
        rows=[]
        for row in self.db.execute('SELECT * FROM uid_spools'):
            row=dict(row);detail=self.db.execute('SELECT payload FROM spool_details WHERE spool_id=?',(row['spool_id'],)).fetchone()
            row['details']=json.loads(detail[0]) if detail else {}
            link=self.db.execute('SELECT url,remote_id FROM uid_remote_links WHERE spool_id=?',(row['spool_id'],)).fetchone()
            row['remote']=dict(link) if link else None;row['revision']=revision(row);rows.append(row)
        return {'spools':rows,'settings':self.settings(),
                'export_plans':[dict(plan_id=r['plan_id'],created_at=r['created_at'],**json.loads(r['payload'])) for r in self.db.execute('SELECT * FROM uid_export_plans ORDER BY created_at DESC LIMIT 20')],
                'remote_outbox':[dict(r) for r in self.db.execute('SELECT * FROM uid_remote_outbox')]}
