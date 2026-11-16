"""Published Spoolman view shapes and guarded catalogue assignments."""
import json
import time

from tracker_desktop_inventory import context
from tracker_uid_accounting import AccountingConflict
from tracker_uid_library import revision


def configuration_revision(values):
    url=values.get('spoolman_url','')
    return revision([url,values.get('spoolman_mode','read' if url else 'off')])


def configure(library,values,expected_revision):
    current=library.settings()
    if configuration_revision(current['values'])!=expected_revision:raise AccountingConflict('Настройки Spoolman изменились. Откройте экран заново.')
    return library.save_settings(values,current['revision'])


def status(library,fleet):
    settings=library.settings();v=settings['values'];url=v.get('spoolman_url','')
    cached=library.remote_catalog(url);locations=library.catalog.reconcile(fleet)
    pid=v.get('selected_printer') or next(iter(v.get('printers',[])),{}).get('id','')
    row=library.db.execute('SELECT checked_at FROM uid_remote_catalog WHERE url=?',(url,)).fetchone()
    linked=[]
    for s in library.snapshot()['spools']:
        if s['remote'] and s['remote']['url']==url:
            linked.append(dict(id=s['spool_id'],remote_id=s['remote']['remote_id'],name=s['name'],
                slots=[int(r['channel']) for r in locations if r['printer_id']==pid and (r.get('spool') or {}).get('spool_id')==s['spool_id']]))
    with library.accounting.transaction():inventory=context(library,fleet)
    return dict(state=dict(url=url,mode=v.get('spoolman_mode','read' if url else 'off'),
        catalog={str(i['id']):i for i in cached['items']} if cached['available'] else {},outbox={},
        checked_at=row[0] if row else None,error='' if cached['available'] or not url else 'Каталог недоступен или устарел.'),
        linked=linked,catalog_revision=cached['revision'],inventory_revision=inventory['revision'],settings_revision=settings['revision'],configuration_revision=configuration_revision(v))


def comparison(library):
    rows=[]
    for s in library.snapshot()['spools']:
        if not s['remote']:continue
        try:
            c=library.compare_name(s['spool_id'])
            rows.append(dict(id=s['spool_id'],canonical_name=c['remote_name'],matches=not c['different'],available=True,revision=c['revision']))
        except ValueError:rows.append(dict(id=s['spool_id'],canonical_name='',matches=False,available=False,revision=''))
    return dict(rows=rows)


def change(library,action,data,expected_revision,request_id,confirmed,*,fleet):
    if confirmed is not True or not isinstance(request_id,str) or not 1<=len(request_id)<=128:raise ValueError('Explicit confirmation required')
    db=library.db;a=library.accounting
    payload=json.dumps(['desktop_spoolman',action,data,expected_revision],sort_keys=True)
    with a.transaction():
        old=db.execute('SELECT * FROM uid_inventory_edits WHERE request_id=?',(request_id,)).fetchone()
        if old:
            if old['payload']!=payload:raise AccountingConflict('Decision changed after submission')
            return json.loads(old['result'])
        ctx=context(library,fleet)
        if ctx['revision']!=expected_revision:raise AccountingConflict('Катушки или назначения изменились. Обновите экран.')
        if action=='attach':
            if set(data)!={'id','slot','catalog_revision'} or type(data['slot']) is not int or data['slot'] not in range(4):raise ValueError('Invalid selection')
            url=ctx['settings']['values'].get('spoolman_url','');item=library.remote_item(url,data['id'],data['catalog_revision'])
            pid=ctx['printer_id'];ch=str(data['slot']);current=db.execute('SELECT * FROM manual_assignments WHERE printer_id=? AND channel=?',(pid,ch)).fetchone()
            if current:a._unlock_guard(pid,current['spool_id'])
            link=db.execute('SELECT spool_id FROM uid_remote_links WHERE url=? AND remote_id=?',(url,data['id'])).fetchone()
            if link:
                result=a._assign_manual(pid,ch,link[0],fleet,current['version'] if current else '')
            else:
                result=library._create(item['name'],item['remaining_g'],fleet=fleet,remote=dict(url=url,id=data['id'],revision=data['catalog_revision']),
                   assignment=dict(printer_id=pid,channel=ch,expected_version=current['version'] if current else '',confirmed=True))
        elif action=='detach':
            if set(data)!={'id'}:raise ValueError('Invalid spool')
            sid=data['id'];spool=next((s for s in ctx['spools'] if s['spool_id']==sid),None)
            if not spool or not spool['remote']:raise ValueError('No remote link')
            a._unlock_guard('',sid,starting=True)
            if db.execute("SELECT 1 FROM uid_jobs j JOIN uid_job_tools t USING(job_key) WHERE j.state='active' AND t.spool_id=?",(sid,)).fetchone():raise AccountingConflict('Катушка участвует в активном задании.')
            if db.execute("SELECT 1 FROM uid_remote_outbox WHERE spool_id=? AND state NOT IN ('sent','resolved')",(sid,)).fetchone():raise AccountingConflict('Сначала разрешите операции Spoolman этой катушки.')
            if db.execute('SELECT 1 FROM sqlite_master WHERE name=?',('uid_replacement_events',)).fetchone():
                if db.execute("SELECT 1 FROM uid_replacement_events e JOIN uid_jobs j USING(job_key) WHERE j.state='active' AND instr(e.payload,?)>0",(sid,)).fetchone():raise AccountingConflict('Катушка участвует в замене активного задания.')
            db.execute('DELETE FROM uid_remote_links WHERE spool_id=?',(sid,));result=dict(status='local',spool_id=sid)
        else:raise ValueError('Unsupported Spoolman operation')
        db.execute('INSERT INTO uid_inventory_edits VALUES(?,?,?,?)',(request_id,payload,json.dumps(result),time.time()))
    return result
