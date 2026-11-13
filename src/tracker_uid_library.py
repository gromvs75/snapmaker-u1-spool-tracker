"""Catalog commands executed only by AccountingOwner's SQLite thread.

External identity is (server URL, spool ID), never a display name. External
consumption starts held; explicit delivery approval is handled by Delivery.
"""
import hashlib
import json
import time
import uuid
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
        ''')

    def settings(self):
        data={r['key']:json.loads(r['payload']) for r in self.db.execute('SELECT * FROM uid_preferences')}
        return {'values':data, 'revision':revision(data)}

    def save_settings(self, values, expected_revision):
        if not isinstance(values,dict) or set(values)-{'printer_names','spoolman_url'}:
            raise ValueError('Неверные настройки.')
        names=values.get('printer_names',{})
        if not isinstance(names,dict) or any(not isinstance(k,str) or not isinstance(v,str) or not v.strip() or len(v)>100 for k,v in names.items()):
            raise ValueError('Неверное имя принтера.')
        if values.get('spoolman_url'):values=dict(values,spoolman_url=endpoint(values['spoolman_url']))
        with self.accounting.transaction():
            if self.settings()['revision']!=expected_revision:raise AccountingConflict('Настройки изменились. Обновите экран.')
            for k,v in values.items():self.db.execute('INSERT OR REPLACE INTO uid_preferences VALUES(?,?)',(k,json.dumps(v)))
        return self.settings()

    def cache_catalog(self, url, items=None):
        url=endpoint(url)
        if items is not None and (not isinstance(items,dict) or any(str(v['id'])!=k for k,v in items.items())):
            raise ValueError('Invalid remote catalog')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO uid_remote_catalog VALUES(?,?,?,?,?)',
                (url,uuid.uuid4().hex,time.time(),int(items is not None),json.dumps(items or {},allow_nan=False)))
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
        # Validate everything before INSERT, then create + assign in one transaction.
        if not isinstance(name,str) or not name.strip() or len(name)>100:raise ValueError('Укажите имя катушки.')
        amount=mg(remaining_g);details=dict(details or {})
        if set(details)-{'material','color'} or any(not isinstance(v,str) or len(v)>100 for v in details.values()):raise ValueError('Неверные параметры катушки.')
        sid=uuid.uuid4().hex
        with self.accounting.transaction():
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
            if fleet.get(printer_id,{}).get('state')!='ready' or self.db.execute("SELECT 1 FROM uid_jobs WHERE state='active' AND printer_id=?",(printer_id,)).fetchone():
                raise AccountingConflict('Снятие недоступно: нет связи или печать активна.')
            self.db.execute('DELETE FROM manual_assignments WHERE printer_id=? AND channel=?',(printer_id,channel))
        return {'status':'detached'}

    def snapshot(self):
        rows=[]
        for row in self.db.execute('SELECT * FROM uid_spools'):
            row=dict(row);detail=self.db.execute('SELECT payload FROM spool_details WHERE spool_id=?',(row['spool_id'],)).fetchone()
            row['details']=json.loads(detail[0]) if detail else {}
            link=self.db.execute('SELECT url,remote_id FROM uid_remote_links WHERE spool_id=?',(row['spool_id'],)).fetchone()
            row['remote']=dict(link) if link else None;rows.append(row)
        return {'spools':rows,'settings':self.settings(),
                'remote_outbox':[dict(r) for r in self.db.execute('SELECT * FROM uid_remote_outbox')]}
