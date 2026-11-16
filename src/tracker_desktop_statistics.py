"""Read actual local debits, including partial jobs; remote delivery is not usage."""
import json
from datetime import datetime, timezone


def statistics(library):
    db=library.db;values=library.settings()['values'];pid=values.get('selected_printer')
    printers=values.get('printers',[])
    if pid not in {p['id'] for p in printers}:pid=printers[0]['id'] if printers else ''
    result=dict(printer_id=pid,counts={},total_mg=0,by_spool={},by_month={},by_basis={},head_mg=[0]*4,unattributed_mg=0)
    jobs={r['job_key']:dict(r) for r in db.execute('SELECT * FROM uid_jobs WHERE printer_id=?',(pid,))}
    for job in jobs.values():
        state=job['state']
        if state=='active' and not job['mapping_valid']:state='review'
        result['counts'][state]=result['counts'].get(state,0)+1
    for row in db.execute('SELECT d.*, e.payload FROM uid_debits d LEFT JOIN uid_usage_events e USING(job_key,sequence) JOIN uid_jobs j USING(job_key) WHERE j.printer_id=?',(pid,)):
        job=jobs[row['job_key']];amount=row['delta_mg'];sid=row['spool_id']
        event=json.loads(row['payload']) if row['payload'] else None
        basis=event[2] if isinstance(event,list) and len(event)==4 else event.get('estimate_source','unknown') if isinstance(event,dict) else 'unknown'
        result['total_mg']+=amount
        result['by_spool'][sid]=result['by_spool'].get(sid,0)+amount
        result['by_basis'][basis]=result['by_basis'].get(basis,0)+amount
        try:month=datetime.fromtimestamp(float(job['started_at']),timezone.utc).strftime('%Y-%m')
        except (ValueError,OverflowError,OSError):month='unknown'
        result['by_month'][month]=result['by_month'].get(month,0)+amount
        # A per-spool manual allocation or a replacement does not establish a head.
        heads=[r[0] for r in db.execute('SELECT channel FROM uid_job_tools WHERE job_key=? AND spool_id=?',(row['job_key'],sid))]
        replacement=db.execute('SELECT 1 FROM uid_replacement_events WHERE job_key=?',(row['job_key'],)).fetchone()
        if len(heads)==1 and not replacement and basis in ('motion_estimate','executed_gcode','completed_gcode','calculated_history'):
            result['head_mg'][int(heads[0])]+=amount
        else:result['unattributed_mg']+=amount
    result['spool_names']={r['spool_id']:r['name'] for r in db.execute('SELECT spool_id,name FROM uid_spools')}
    result['legacy_records']=db.execute('SELECT count(*) FROM uid_legacy_history WHERE printer_id=?',(pid,)).fetchone()[0]
    return result
