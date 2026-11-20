"""Read model for the full 1.3.3 desktop, evaluated by the SQLite owner.

This translates presentation shapes only. It never creates a legacy Store,
reconciles historical usage, submits Spoolman requests or contacts devices.
"""
import json
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlsplit


def snapshot(library, history_review, fleet):
    db=library.db
    catalog=library.snapshot();settings=catalog['settings']['values']
    printers=[dict(p,name=settings.get('printer_names',{}).get(p['id'],p['name'])) for p in settings.get('printers',[])]
    pid=settings.get('selected_printer')
    if pid not in {p['id'] for p in printers}:pid=printers[0]['id'] if printers else ''
    printer=next((p for p in printers if p['id']==pid),None)
    address=urlsplit(printer['url']) if printer else None
    from tracker_desktop_inventory import context
    with library.accounting.transaction():inventory=context(library,fleet)
    locations=inventory['locations']
    slots={str(i+1):'' for i in range(4)};slot_status={}
    for row in locations:
        if row['printer_id']==pid and row.get('spool'):
            slot=str(int(row['channel'])+1)
            slots[slot]=row['spool']['spool_id'];slot_status[slot]=row['state']
    spools={}
    for s in catalog['spools']:
        value=dict(s['details'],name=s['name'],remaining_g=s['remaining_mg']/1000,
                   material=s['details'].get('material',''),uid=s['uid'],revision=s['revision'])
        value['calibration']=dict(s['details'].get('calibration') or {},uid=s['uid'] or '',identity_mode='tag' if s['uid'] else 'unverified')
        value['assignments']=[dict(printer_id=r['printer_id'],printer_name=settings.get('printer_names',{}).get(r['printer_id'],next((p['name'] for p in printers if p['id']==r['printer_id']),r['printer_id'])),channel=r['channel'],state=r['state'])
                              for r in locations if (r.get('spool') or {}).get('spool_id')==s['spool_id']]
        if s['remote']:value['spoolman']=dict(url=s['remote']['url'],id=s['remote']['remote_id'])
        value['pending_deliveries']=db.execute("SELECT COUNT(*) FROM uid_remote_outbox WHERE spool_id=? AND state NOT IN ('sent','resolved')",(s['spool_id'],)).fetchone()[0]
        spools[s['spool_id']]=value
    plans={};runs={};details={}
    for row in db.execute('SELECT * FROM uid_jobs WHERE printer_id=? ORDER BY started_at',(pid,)).fetchall():
        job=dict(row);key=job['job_key'];detail=history_review.detail(key);details[key]=detail
        profile=detail['plan_source'];history=detail['history'] or {}
        amounts={}
        for d in detail['debits']:amounts[d['spool_id']]=amounts.get(d['spool_id'],0)+d['delta_mg']/1000
        status=('committed' if job['state']=='completed' else 'cancelled' if job['state']=='cancelled'
                else 'active' if detail['review_block']=='observing' else 'review')
        source=(detail['receipt'] or {}).get('estimate_source')
        if source is None and job['source']=='legacy_import':source='legacy_import'
        run=dict(job_key=key,filename=detail['filename'] or job['job_id'],start_time=float(job['started_at']),
                 status=status,terminal_status=history.get('status') if history.get('status')!='in_progress' else None,
                 review_reason='; '.join(detail['reasons']),plan_id=key,accounted_g=detail['accounted_mg']/1000,
                 accounted_by_spool=amounts,manual_consumption=amounts if source=='manual_reconciliation' else {},
                 motion_consumption=amounts if source is None else {},
                 accounting_method='manual_review' if source=='manual_reconciliation' else 'motion_estimate' if source is None else 'legacy_import' if source=='legacy_import' else 'history_estimate',
                 closed_without_deduction=job['state']=='resolved',unlock=library.accounting.unlock_state(key))
        if profile:
            plans[key]=dict(filename=profile['filename'],weights=profile['logical_weights'],
                            sha256=profile['file_sha256'],created_at=profile['started_at'],status='saved',
                            physical_plan=detail['plan'],quarantined=detail['quarantined'])
        runs[key]=run
    # This record carries no spool binding, debit or authorization. A later
    # bound capture takes its place in the read model under the real job key.
    for observed in history_review.unaccounted_history(pid):
        key = 'printer-history:' + observed['history_key']
        runs[key] = dict(job_key=key, filename=observed['filename'], start_time=observed['started_at'],
                         status='printer_history', terminal_status=observed['status'],
                         accounted_g=0, accounted_by_spool={}, closed_without_deduction=False)
    for p in catalog['export_plans']:
        if p['printer_id']==pid or not p['printer_id']:
            plans[p['plan_id']]=dict(filename=p['filename'],weights=p['weights'],sha256=p['file_sha256'],
                                    created_at=p['created_at'],status='exported',mapping_assumed=False)
    connected=False
    active=next((r for r in reversed(list(runs.values())) if r['status']=='active'),None)
    # Only the independent, fresh Moonraker monitor can establish print status.
    monitor=dict(connected=connected,state='unknown' if connected else 'disabled',filename=active['filename'] if active else '',
                 error='',checked_at=0,active_job_key=active['job_key'] if active else None)
    last_preflight=None
    remote_url=settings.get('spoolman_url','')
    remote_mode=settings.get('spoolman_mode','read' if remote_url else 'off')
    remote_row=db.execute('SELECT checked_at,available FROM uid_remote_catalog WHERE url=?',(remote_url,)).fetchone()
    remote_state=('unconfigured' if not remote_url else 'disabled' if remote_mode=='off' else
                  'unchecked' if not remote_row else 'unavailable' if not remote_row['available'] else
                  'current' if library.remote_catalog(remote_url)['available'] else 'stale')
    sources=dict(spoolman=dict(state=remote_state,mode=remote_mode,
        checked_at=remote_row['checked_at'] if remote_row else None,
        linked=sum(1 for s in spools.values() if s.get('spoolman',{}).get('url')==remote_url),
        pending=sum(s['pending_deliveries'] for s in spools.values() if s.get('spoolman',{}).get('url')==remote_url)))
    if catalog['export_plans']:
        p=next((p for p in catalog['export_plans'] if p['printer_id']==pid or not p['printer_id']),None)
        if p:
            last_preflight=dict(filename=p['filename'],source='export',rows=[],summary='Export saved',
                time=datetime.fromtimestamp(p['created_at'],timezone.utc).isoformat(),
                reason='Material-to-head mapping is available at print start.')
    return dict(language=settings.get('language','ru'),safety_margin_g=settings.get('safety_margin_g',5),
                slots=slots,slot_status=slot_status,spools=spools,plans=plans,runs=runs,last_preflight=last_preflight,last_guard=None,
                printer=dict(host=address.hostname if address else '',port=address.port or (443 if address.scheme=='https' else 80) if address else 7125,
                             enabled=connected,guard_mode=settings.get('guard_modes',{}).get(pid,'warn')),monitor=monitor,printers=printers,selected_printer=pid,
                settings_revision=catalog['settings']['revision'],inventory_revision=inventory['revision'],saved_history=details,
                observations=locations,guard_modes=settings.get('guard_modes',{}),data_sources=sources,
                uid_channels={p['id']:dict(state=fleet.get(p['id'],{}).get('state','stopped'),
                    channels=fleet.get(p['id'],{}).get('channels',{})) for p in printers})


def forecast_view(forecast,printer_id):
    """Use the new freshness/identity rules through the established forecast view."""
    entries=[]
    for e in forecast.get('printers',{}).get(printer_id,{}).get('entries',forecast.get('entries',[])):
        # The original renderer only accepts complete entries. Pending/removed
        # entries must disappear, rather than retain a green outdated result.
        if e['state']!='ready':continue
        rows=[dict(tool='T'+r['channel'],spool_id=(r['spool'] or {}).get('spool_id'),
                   name=(r['spool'] or {}).get('name',''),used=r['used'],remaining=r['remaining'],
                   after=r['after'],enough=r['enough'],unknown=r['unknown'],provisional=r.get('provisional',False)) for r in e['rows']]
        source=Path(e['source'])
        entries.append(dict(e,rows=rows,label='Plate '+str(e['plate'] or '?'),source_label=source.parent.parent.name+' · '+source.name,
                            observed_at=e.get('completed_at_ns',0)/1e9 or e.get('observed_at',0),
                            unknown=e['status']=='unknown',shortage=e['status']=='shortage'))
    value=dict(entries=entries,printer_id=printer_id,latest=forecast.get('latest'),safety_margin_g=forecast.get('safety_margin_g',5),
               project=forecast.get('project'),error=forecast.get('error',''),mapping=None,mapping_assumed=False)
    from tracker_uid_library import revision
    value['revision']=revision(value)
    # Inventory changes update the forecast but are not a newly completed slice.
    value['slice_revision']=revision([value['latest'],[(e['source'],e.get('sha256'),e.get('completed_at_ns')) for e in entries]])
    return value
