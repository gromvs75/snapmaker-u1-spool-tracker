"""Transactional adapters for the published inventory forms; no legacy Store."""
import json
import re
import time

from tracker_uid_accounting import AccountingConflict, mg
from tracker_uid_library import revision
from tracker_printer_capabilities import can_replace_stale_uid, manual_edit_available


def context(library, fleet):
    locations=library.catalog._reconcile(fleet)
    settings=library.settings()
    printers=settings['values'].get('printers',[])
    pid=settings['values'].get('selected_printer')
    if pid not in {p['id'] for p in printers}:pid=printers[0]['id'] if printers else ''
    # Include assignment versions and connection generations, not packet ages.
    connections={p:{k:s.get(k) for k in ('state','client_session','generation','epoch')}
                 for p,s in fleet.items()}
    value=dict(printer_id=pid,locations=locations,settings=settings,
               spools=library.snapshot()['spools'],connections=connections)
    return dict(value,revision=revision(value))


class DesktopInventory:
    def __init__(self,library):
        self.library=library;self.accounting=library.accounting;self.db=library.db

    def execute(self, action, data, expected_revision, request_id, confirmed, *, fleet):
        if (confirmed is not True or not isinstance(data,dict) or not isinstance(request_id,str)
                or not 1<=len(request_id)<=128 or not isinstance(expected_revision,str)):
            raise ValueError('Подтвердите изменение катушки или назначения.')
        payload=json.dumps(['desktop',action,data,expected_revision],sort_keys=True,allow_nan=False)
        with self.accounting.transaction():
            old=self.db.execute('SELECT * FROM uid_inventory_edits WHERE request_id=?',(request_id,)).fetchone()
            if old:
                if old['payload']!=payload:raise AccountingConflict('Повтор запроса содержит другое изменение.')
                return dict(json.loads(old['result']),status='duplicate')
            ctx=context(self.library,fleet)
            if expected_revision!=ctx['revision']:raise AccountingConflict('Катушки или назначения изменились. Изменение не сохранено.')
            if action=='spools/add':result=self.create(data,ctx,fleet)
            elif action=='slots':result=self.slots(data,ctx,fleet)
            elif action in ('spools/color','spools/update'):result=self.edit(action,data,ctx)
            elif action=='spools/delete':result=self.delete(data,ctx)
            elif action in ('spools/calibration','spools/archive'):result=self.parameters(action,data,ctx)
            else:raise ValueError('Неподдерживаемое действие библиотеки.')
            self.db.execute('INSERT INTO uid_inventory_edits VALUES(?,?,?,?)',
                            (request_id,payload,json.dumps(result),time.time()))
        return result

    def create(self,data,ctx,fleet):
        if set(data)-{'name','remaining_g','material','color','assign_slot','expected_slot'}:
            raise ValueError('Неверные параметры катушки.')
        color=data.get('color') or ''
        if color and (not isinstance(color,str) or not re.fullmatch('#[0-9a-fA-F]{6}',color)):
            raise ValueError('Неверный цвет.')
        if mg(data['remaining_g'])>100_000_000:raise ValueError('Остаток слишком велик.')
        assignment=None
        if 'assign_slot' in data:
            slot=data['assign_slot']
            if slot not in ('1','2','3','4'):raise ValueError('Выберите головку.')
            ch=str(int(slot)-1);pid=ctx['printer_id']
            current=self.db.execute('SELECT * FROM manual_assignments WHERE printer_id=? AND channel=?',(pid,ch)).fetchone()
            if data.get('expected_slot','')!=(current['spool_id'] if current else ''):
                raise AccountingConflict('Исходное назначение изменилось.')
            if current:self.accounting._unlock_guard(pid,current['spool_id'])
            assignment=dict(printer_id=pid,channel=ch,expected_version=current['version'] if current else '',confirmed=True)
        return self.library._create(data['name'],data['remaining_g'],fleet=fleet,
                details=dict(material=data.get('material',''),color=color),assignment=assignment)

    def edit(self,action,data,ctx):
        field='color' if action=='spools/color' else 'remaining_g'
        if set(data)!={'id',field}:raise ValueError('Неверные параметры катушки.')
        spool=next((s for s in ctx['spools'] if s['spool_id']==data['id']),None)
        if spool is None:raise ValueError('Катушка не найдена.')
        value=data[field];amount=mg(value) if field=='remaining_g' else None
        if amount is not None and amount>100_000_000:raise ValueError('Остаток слишком велик.')
        if field=='color' and value not in (None,'') and (not isinstance(value,str) or not re.fullmatch('#[0-9a-fA-F]{6}',value)):
            raise ValueError('Неверный цвет.')
        return self.library._edit_spool(data['id'],{field:value},spool['revision'],amount)

    def slots(self,data,ctx,fleet):
        if set(data)!={'1','2','3','4'} or any(not isinstance(v,str) for v in data.values()):
            raise ValueError('Неверные назначения головок.')
        selected=[v for v in data.values() if v]
        if len(selected)!=len(set(selected)):raise AccountingConflict('Одна катушка не может занимать две головки.')
        pid=ctx['printer_id'];locations=[r for r in ctx['locations'] if r['printer_id']==pid]
        manual={r['channel']:r for r in locations if r.get('identity_mode')=='manual'}
        tagged={r['channel']:r for r in locations if r.get('identity_mode')!='manual'}
        changed=[]
        for slot,target in data.items():
            ch=str(int(slot)-1)
            current=manual.get(ch)
            observed=tagged.get(ch)
            if observed:
                if current is None and target==(observed.get('spool') or {}).get('spool_id',''):
                    continue
                if not target or not can_replace_stale_uid(fleet.get(pid,{}), observed):
                    raise AccountingConflict('Назначение RFID изменяется только по наблюдённой метке.')
            if target!=(current['spool_id'] if current else '') or (current and not current['confirmed']):changed.append((ch,current,target))
        if changed:
            if not manual_edit_available(fleet.get(pid,{})):raise AccountingConflict('Нет связи с принтером или печать не завершена. Назначение не подтверждено.')
            if self.db.execute("SELECT 1 FROM uid_jobs WHERE state='active' AND printer_id=?",(pid,)).fetchone():
                raise AccountingConflict('Сначала завершите или разрешите активное задание.')
        # Release all changed manual slots first, so a same-printer swap is atomic.
        for ch,current,target in changed:
            if current:
                self.accounting._unlock_guard(pid,current['spool_id'])
                self.db.execute('DELETE FROM manual_assignments WHERE printer_id=? AND channel=?',(pid,ch))
        for ch,current,target in changed:
            if target:self.accounting._assign_manual(pid,ch,target,fleet,'')
        return dict(status='saved',printer_id=pid,changed=len(changed))

    def delete(self,data,ctx):
        if set(data)!={'id'}:raise ValueError('Неверная катушка.')
        sid=data['id'];spool=next((s for s in ctx['spools'] if s['spool_id']==sid),None)
        if spool is None:raise ValueError('Катушка не найдена.')
        # Deletion is only for unused local spools. Never erase ledger identities.
        if spool['remote'] or spool['uid'] or any((r.get('spool') or {}).get('spool_id')==sid for r in ctx['locations']):
            raise AccountingConflict('Нельзя удалить назначенную катушку, UID или связь Spoolman.')
        for table in ('uid_job_tools','uid_debits','uid_remote_outbox','manual_assignment_candidates','legacy_spools'):
            if self.db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone() and self.db.execute('SELECT 1 FROM '+table+' WHERE spool_id=?',(sid,)).fetchone():
                raise AccountingConflict('Катушка сохранена в истории. Удаление нарушит её целостность.')
        # Saved plans, replacements and audit records may refer to a spool only
        # inside JSON; retain it if any such evidence exists.
        for table in ('uid_export_plans','uid_replacement_events','uid_recovery_profiles','uid_history_decisions','uid_inventory_edits','manual_transfers'):
            if self.db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():
                columns={r['name'] for r in self.db.execute('PRAGMA table_info('+table+')')}
                for column in ('payload','profile'):
                    if column in columns and self.db.execute('SELECT 1 FROM '+table+' WHERE instr('+column+',?)>0',(sid,)).fetchone():
                        raise AccountingConflict('Катушка используется в сохранённом плане или журнале изменений.')
        self.db.execute('DELETE FROM spool_details WHERE spool_id=?',(sid,))
        self.db.execute('DELETE FROM uid_spools WHERE spool_id=?',(sid,))
        return dict(status='deleted',spool_id=sid)

    def parameters(self,action,data,ctx):
        field='calibration' if action=='spools/calibration' else 'archived'
        if set(data)!={'id',field}:raise ValueError('Неверные параметры катушки.')
        sid=data['id'];spool=next((s for s in ctx['spools'] if s['spool_id']==sid),None)
        if spool is None:raise ValueError('Катушка не найдена.')
        self.accounting._unlock_guard('',sid,starting=True)
        if self.db.execute("SELECT 1 FROM uid_job_tools JOIN uid_jobs USING(job_key) WHERE state='active' AND spool_id=?",(sid,)).fetchone():
            raise AccountingConflict('Сначала завершите или разрешите задание катушки.')
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='uid_replacement_events'").fetchone():
            for row in self.db.execute("SELECT payload FROM uid_replacement_events JOIN uid_jobs USING(job_key) WHERE state='active'"):
                event=json.loads(row[0])
                if sid in (event.get('old_spool_id'),event.get('new_spool_id')):
                    raise AccountingConflict('Катушка участвует в незавершённой замене.')
        details=dict(spool['details'])
        if field=='calibration':
            from spool_identity import calibration
            value=data[field]
            if not isinstance(value,dict) or set(value)!={'diameter_mm','density_g_cm3'}:
                raise ValueError('UID изменяется только через регистрацию наблюдённой метки.')
            clean=calibration(value)
            details[field]={k:clean[k] for k in value}
        else:
            if type(data[field]) is not bool:raise ValueError('Неверный признак архива.')
            if data[field]:
                if any((r.get('spool') or {}).get('spool_id')==sid for r in ctx['locations']):
                    raise AccountingConflict('Сначала снимите катушку со всех принтеров и подтвердите отсутствие метки.')
                if self.db.execute("SELECT 1 FROM uid_remote_outbox WHERE spool_id=? AND state NOT IN ('sent','resolved')",(sid,)).fetchone():
                    raise AccountingConflict('Сначала разрешите очередь Spoolman этой катушки.')
            details[field]=data[field]
        self.db.execute('INSERT OR REPLACE INTO spool_details VALUES(?,?)',(sid,json.dumps(details,allow_nan=False)))
        return dict(status='saved',spool_id=sid)
