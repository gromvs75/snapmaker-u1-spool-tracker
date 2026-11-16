"""Offline conversion of an explicitly selected 1.x export into a disposable 2.0 DB.

Never opens legacy application paths. The complete original export is retained
for audit; historical debits describe prior accounting and NEVER change balances.
"""
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

from backup import BACKUP_FORMAT, MAX_BACKUP_BYTES, parse_backup
from storage import StorageError
from tracker_uid_accounting import mg
from tracker_uid_migration import history_identity
from tracker_uid_settings import validate_printers


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def recognizes(package):
    return isinstance(package, dict) and package.get('backup_format') == BACKUP_FORMAT


def convert(package, live):
    """Use the shipping 1.3 validator and trusted local schema, not input SQL."""
    from tracker_uid_backup import export, schema
    raw = encoded(package).encode()
    if len(raw) > MAX_BACKUP_BYTES:
        raise ValueError('Резервная копия 1.x слишком велика.')
    with tempfile.TemporaryDirectory(prefix='tracker-legacy-import-') as folder:
        path = Path(folder)/'selected.json'
        path.write_bytes(raw)
        try:
            data = parse_backup(path)
        except StorageError as exc:
            raise ValueError('Некорректная копия 1.x: '+str(exc)) from exc
        db = sqlite3.connect(Path(folder)/'converted.sqlite')
        try:
            # Start empty. Only DDL from the running owner's schema is executable.
            definitions = schema(live)
            for kind, name, table, sql in sorted(definitions, key=lambda r: r[0] != 'table'):
                db.execute(sql)
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                summary = populate(db, data, package)
            return export(db), dict(summary, source_format='legacy', source_version=package['app_version'],
                                    source_sha256=hashlib.sha256(raw).hexdigest())
        except sqlite3.IntegrityError as exc:
            raise ValueError('Копия содержит конфликтующие идентификаторы или связи.') from exc
        finally:
            db.close()


def populate(db, data, original):
    source_hash = hashlib.sha256(encoded(original).encode()).hexdigest()
    db.execute('INSERT INTO uid_legacy_import VALUES(?,?)', (source_hash, encoded(original)))
    printers = {}
    def printer(cfg):
        host = cfg['host'].casefold()
        authority = ('['+host+']') if ':' in host else host
        url = f"http://{authority}:{cfg['port']}"
        pid = 'legacy-'+hashlib.sha256(url.encode()).hexdigest()[:16]
        printers.setdefault(pid, dict(id=pid, name='U1' if not printers else host, url=url))
        return pid
    selected = printer(data['printer'])
    for plan in data['plans'].values():
        if 'printer_id' not in plan:  # data is the validated disposable snapshot
            plan['printer_id'] = printer(plan['printer'])
    preferences = dict(printers=validate_printers(list(printers.values())), selected_printer=selected,
        language=data['language'], safety_margin_g=data['safety_margin_g'], spoolman_mode='off',
        guard_modes={pid:'warn' for pid in printers})
    if data.get('spoolman',{}).get('url'):
        preferences['spoolman_url'] = data['spoolman']['url']
    db.executemany('INSERT INTO uid_preferences VALUES(?,?)', [(k,encoded(v)) for k,v in preferences.items()])
    for sid, spool in data['spools'].items():
        # Calibration/tag hints in 1.x are not a verified RFID registration.
        detail = dict(spool)
        if detail.get('calibration'):
            detail['calibration'] = {k:v for k,v in detail['calibration'].items() if k in ('diameter_mm','density_g_cm3')}
        db.execute('INSERT INTO uid_spools VALUES(?,NULL,?,?)', (sid,spool['name'],mg(spool['remaining_g'])))
        db.execute('INSERT INTO spool_details VALUES(?,?)', (sid,encoded(detail)))
        if spool.get('spoolman'):
            ref = spool['spoolman']
            db.execute('INSERT INTO uid_remote_links VALUES(?,?,?)', (sid,ref['url'],ref['id']))
    slots = data['slots']
    for slot, sid in slots.items():
        if not sid: continue
        ch = str(int(slot)-1)
        duplicate = list(slots.values()).count(sid)>1
        db.execute('INSERT INTO manual_assignment_candidates VALUES(?,?,?,?)',
                   (selected,ch,sid,'duplicate legacy slot' if duplicate else 'confirmation required'))
        if not duplicate:
            db.execute('INSERT INTO manual_assignments VALUES(?,?,?,?,?,0)', (selected,ch,sid,'imported:'+slot,''))
    jobs = {}
    for old_key, run in data['runs'].items():
        plan = data['plans'][run['plan_id']]
        pid = plan['printer_id']
        identity = history_identity(pid,run['job_id'],run['start_time'])
        key = 'legacy:'+identity
        jobs[old_key] = key
        db.execute('INSERT INTO uid_legacy_history VALUES(?,?,?,?,?,?,?)',
                   (identity,pid,run['job_id'],str(run['start_time']),old_key,run['status'],encoded(run)))
        committed = run['status']=='committed'
        db.execute('INSERT INTO uid_jobs VALUES(?,?,?,?,?,?,?,0)',
                   (key,pid,run['job_id'],str(run['start_time']),'completed' if committed else 'review','legacy_import',0 if committed else -1))
        physical = 'physical_spool_ids' in run
        ids = run.get('physical_spool_ids',plan['spool_ids'])
        weights = run.get('physical_weights',plan['weights'])
        profile = dict(filename=plan['filename'],file_sha256=plan['sha256'],started_at=run['start_time'],
                       logical_weights=weights,mapping=list(range(4)),legacy_import=True,
                       legacy_spool_ids=ids,legacy_mapping_verified=physical,original_plan=plan)
        db.execute('INSERT INTO uid_recovery_profiles VALUES(?,?,1)', (identity,encoded(profile)))
        history = dict(job_id=run['job_id'],start_time=run['start_time'],filename=plan['filename'],
                       status=run.get('terminal_status','completed' if committed else 'interrupted'))
        db.execute('INSERT INTO uid_motion_captures VALUES(?,?,?,?,?,?,?,NULL,?)',
                   (key,pid,key,run['start_time'],plan['filename'],identity,encoded(history),'legacy'))
        for ch,sid in enumerate(ids):
            if sid in data['spools'] and weights[ch]>0:
                db.execute('INSERT INTO uid_job_tools VALUES(?,?,?,?,0)', (key,str(ch),sid,''))
        amounts = {}
        if committed:
            if run.get('accounting_method')=='manual_review': amounts = run['manual_consumption']
            elif run.get('accounting_method')=='motion_estimate': amounts = run['motion_consumption']
            elif physical:
                for sid,grams in zip(ids,weights):
                    if sid and grams: amounts[sid] = amounts.get(sid,0)+grams
        # Missing historical spools stay historical IDs, not fabricated inventory.
        for sid, grams in amounts.items():
            db.execute('INSERT INTO uid_debits VALUES(?,?,?,?)', (key,0,sid,mg(grams)))
        if amounts:
            db.execute('INSERT INTO uid_usage_events VALUES(?,?,?)',
                       (key,0,encoded(dict(estimate_source='legacy_import',original_method=run.get('accounting_method','completed_gcode')))))
        reason = run.get('review_reason') or 'legacy_import_review'
        db.execute('INSERT INTO uid_motion_review(job_key,reason) VALUES(?,?)', (key,reason))
    for op_id, op in data.get('spoolman',{}).get('outbox',{}).items():
        key = jobs.get(op['job'],'legacy-operation:'+hashlib.sha256(op_id.encode()).hexdigest())
        state = 'uncertain' if op['state'] in ('pending','sending','uncertain') else 'sent' if op['state']=='sent' else 'resolved'
        db.execute('INSERT INTO uid_remote_outbox VALUES(?,?,?,?,?,?,?)',
                   (key,0,op['local_id'],op['url'],op['spool_id'],mg(op['grams']),state))
    return dict(legacy_plans=len(data['plans']),history_fences=len(jobs),
                unconfirmed_assignments=sum(bool(s) for s in slots.values()),
                unregistered_tags=sum(bool(s.get('calibration',{}).get('uid')) for s in data['spools'].values()))
