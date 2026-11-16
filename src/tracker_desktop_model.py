"""Read model for the full 1.3.3 desktop, evaluated by the SQLite owner.

This translates presentation shapes only. It never creates a legacy Store,
reconciles historical usage, submits Spoolman requests or contacts devices.
"""
import json
from datetime import datetime,timezone
from urllib.parse import urlsplit


def snapshot(library, history_review, fleet):
    db=library.db
    catalog=library.snapshot();settings=catalog['settings']['values']
    printers=settings.get('printers',[])
    pid=settings.get('selected_printer')
    if pid not in {p['id'] for p in printers}:pid=printers[0]['id'] if printers else ''
    printer=next((p for p in printers if p['id']==pid),None)
    address=urlsplit(printer['url']) if printer else None
    locations=library.catalog.reconcile(fleet)
    slots={str(i+1):'' for i in range(4)};slot_status={}
    for row in locations:
        if row['printer_id']==pid and row.get('spool'):
            slot=str(int(row['channel'])+1)
            slots[slot]=row['spool']['spool_id'];slot_status[slot]=row['state']
    spools={}
    for s in catalog['spools']:
        value=dict(s['details'],name=s['name'],remaining_g=s['remaining_mg']/1000,
                   material=s['details'].get('material',''),uid=s['uid'],revision=s['revision'])
        value['assignments']=[dict(printer_id=r['printer_id'],channel=r['channel'],state=r['state'])
                              for r in locations if (r.get('spool') or {}).get('spool_id')==s['spool_id']]
        if s['remote']:value['spoolman']=dict(url=s['remote']['url'],id=s['remote']['remote_id'])
        spools[s['spool_id']]=value
    plans={};runs={};details={}
    for row in db.execute('SELECT * FROM uid_jobs WHERE printer_id=? ORDER BY started_at',(pid,)).fetchall():
        job=dict(row);key=job['job_key'];detail=history_review.detail(key);details[key]=detail
        profile=detail['plan_source'];history=detail['history'] or {}
        amounts={}
        for d in detail['debits']:amounts[d['spool_id']]=amounts.get(d['spool_id'],0)+d['delta_mg']/1000
        status=('committed' if job['state']=='completed' else 'cancelled' if job['state']=='cancelled'
                else 'active' if job['state']=='active' and job['mapping_valid'] else 'review')
        source=(detail['receipt'] or {}).get('estimate_source')
        run=dict(job_key=key,filename=detail['filename'] or job['job_id'],start_time=float(job['started_at']),
                 status=status,terminal_status=history.get('status') if history.get('status')!='in_progress' else None,
                 review_reason='; '.join(detail['reasons']),plan_id=key,accounted_g=detail['accounted_mg']/1000,
                 accounted_by_spool=amounts,manual_consumption=amounts if source=='manual_reconciliation' else {},
                 motion_consumption=amounts if source is None else {},
                 accounting_method='manual_review' if source=='manual_reconciliation' else 'motion_estimate' if source is None else 'history_estimate',
                 closed_without_deduction=job['state']=='resolved')
        if profile:
            plans[key]=dict(filename=profile['filename'],weights=profile['logical_weights'],
                            sha256=profile['file_sha256'],created_at=profile['started_at'],status='saved',
                            physical_plan=detail['plan'],quarantined=detail['quarantined'])
        runs[key]=run
    for p in catalog['export_plans']:
        if p['printer_id']==pid or not p['printer_id']:
            plans[p['plan_id']]=dict(filename=p['filename'],weights=p['weights'],sha256=p['file_sha256'],
                                    created_at=p['created_at'],status='exported',mapping_assumed=True)
    connected=fleet.get(pid,{}).get('state')=='ready'
    active=next((r for r in reversed(list(runs.values())) if r['status']=='active'),None)
    # RFID readiness alone does not establish printer idle/printing/paused status.
    monitor=dict(connected=connected,state='unknown' if connected else 'disabled',filename=active['filename'] if active else '',
                 error='',checked_at=0,active_job_key=active['job_key'] if active else None)
    last_preflight=None
    if catalog['export_plans']:
        p=next((p for p in catalog['export_plans'] if p['printer_id']==pid or not p['printer_id']),None)
        if p:
            rows=[dict(tool='T'+r['channel'],spool_id=(r['spool'] or {}).get('spool_id'),spool_name=(r['spool'] or {}).get('name'),
                       required_g=r['used'],remaining_g=r['remaining'],status={'ok':'ok','shortage':'insufficient','unknown':'unassigned','unused':'unused'}[r['status']]) for r in p['forecast']['rows']]
            last_preflight=dict(filename=p['filename'],source='export',rows=rows,summary='Export check: mapping unverified',
                time=datetime.fromtimestamp(p['created_at'],timezone.utc).isoformat(),reason='Mapping is provisional; export does not deduct filament.')
    return dict(language=settings.get('language','ru'),safety_margin_g=settings.get('safety_margin_g',5),
                slots=slots,slot_status=slot_status,spools=spools,plans=plans,runs=runs,last_preflight=last_preflight,last_guard=None,
                printer=dict(host=address.hostname if address else '',port=address.port or (443 if address.scheme=='https' else 80) if address else 7125,
                             enabled=connected,guard_mode='warn'),monitor=monitor,printers=printers,selected_printer=pid,
                settings_revision=catalog['settings']['revision'],saved_history=details)


def forecast_view(forecast,printer_id):
    """Use the new freshness/identity rules through the established forecast view."""
    entries=[]
    for e in forecast.get('printers',{}).get(printer_id,{}).get('entries',[]):
        # The original renderer only accepts complete entries. Pending/removed
        # entries must disappear, rather than retain a green outdated result.
        if e['state']!='ready':continue
        rows=[dict(tool='T'+r['channel'],spool_id=(r['spool'] or {}).get('spool_id'),
                   name=(r['spool'] or {}).get('name',''),used=r['used'],remaining=r['remaining'],
                   after=r['after'],enough=r['enough'],unknown=r['unknown']) for r in e['rows']]
        entries.append(dict(e,rows=rows,label='Plate '+str(e['plate'] or '?'),unknown=e['status']=='unknown',shortage=e['status']=='shortage'))
    value=dict(entries=entries,latest=forecast.get('latest'),safety_margin_g=forecast.get('safety_margin_g',5),
               project=forecast.get('project'),error=forecast.get('error',''),mapping=[0,1,2,3],mapping_assumed=True)
    from tracker_uid_library import revision
    value['revision']=revision(value)
    return value
