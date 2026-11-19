"""Start checks and one-shot experimental pause, separate from consumption.

SQLite methods never contact a printer. A persisted attempt fences retries even
when the command response is lost. Transport checks the same job before acting.
"""
import json
import math
import time
import uuid
from datetime import datetime,timezone
from tracker_uid_accounting import job_key


class Guard:
    def __init__(self,library):
        self.library=library;self.db=library.db;self.live={};self.armed={}
        self.db.execute('CREATE TABLE IF NOT EXISTS uid_start_checks (identity TEXT PRIMARY KEY, printer_id TEXT NOT NULL, payload TEXT NOT NULL)');self.db.commit()

    def status(self,pid,status):
        stats=status.get('print_stats',{})
        if not isinstance(stats.get('state'),str) or not isinstance(stats.get('filename',''),str):
            raise ValueError('Invalid print status')
        extruder=status.get('toolhead',{}).get('extruder')
        heads={'extruder':0,'extruder1':1,'extruder2':2,'extruder3':3}
        self.live[pid]=dict(connected=True,error='',state=stats.get('state','unknown'),filename=stats.get('filename',''),checked_at=time.time(),active_head=heads.get(extruder))
        from tracker_dashboard import telemetry
        self.live[pid].update(telemetry(status))
        return self.live[pid]

    def snapshot(self,pid):
        row=self.db.execute('SELECT payload FROM uid_start_checks WHERE printer_id=? ORDER BY rowid DESC LIMIT 1',(pid,)).fetchone()
        return dict(monitor=self.live.get(pid),guard=json.loads(row[0]) if row else None)

    def save(self,value):
        value=dict(value,revision=uuid.uuid4().hex)
        self.db.execute('INSERT OR REPLACE INTO uid_start_checks VALUES(?,?,?)',(value['identity'],value['printer_id'],json.dumps(value,allow_nan=False)));self.db.commit()
        return value

    def check(self,pid,job,profile,*,fleet):
        identity=job_key(pid,job['job_id'],str(job['start_time']))
        old=self.db.execute('SELECT payload FROM uid_start_checks WHERE identity=?',(identity,)).fetchone()
        if old:return json.loads(old[0])
        settings=self.library.settings()['values'];mode=settings.get('guard_modes',{}).get(pid,'warn')
        if mode=='off':return None
        weights=profile['logical_weights'];mapping=profile['mapping']
        if (job.get('status')!='in_progress' or len(weights)!=4 or sorted(mapping)!=[0,1,2,3]
                or any(type(w) not in (int,float) or not math.isfinite(w) or w<0 for w in weights)):
            raise ValueError('Unverified start plan')
        inventory=self.library.forecast_inventory(fleet=fleet);printer=inventory['printers'].get(pid)
        if printer is None:return None
        rows=[];reasons=[];reserve=inventory['safety_margin_g']
        for ch in range(4):
            required=sum(w for i,w in enumerate(weights) if mapping[i]==ch)
            head=printer['heads'][ch];spool=head['spool'];remaining=spool['remaining_mg']/1000 if spool else None
            state='unused' if required==0 else 'unassigned' if not head['usable'] else 'insufficient' if remaining<required+reserve else 'ok'
            rows.append(dict(tool='T'+str(ch),spool_id=spool['spool_id'] if spool else None,spool_name=spool['name'] if spool else None,required_g=required,remaining_g=remaining,status=state))
            if state in ('unassigned','insufficient'):reasons.append('T'+str(ch)+': '+('assignment/balance unconfirmed' if state=='unassigned' else 'insufficient material including reserve'))
        # A late reconnect must never pause an already-running print retrospectively.
        age=time.time()-job['start_time']
        pause=bool(reasons and mode=='strict' and self.armed.get(pid,float('inf'))<=job['start_time'] and 0<=age<=60)
        from tracker_uid_migration import history_identity
        bound=self.db.execute('SELECT key FROM uid_motion_captures WHERE history_key=?',(history_identity(pid,job['job_id'],job['start_time']),)).fetchone()
        from material_guard import compare_materials
        material=compare_materials(profile.get('metadata'),weights,mapping,self.library.catalog.inventory_snapshot(pid,fleet))
        advisory=any(r['status']=='mismatch' for r in material)
        if advisory:reasons.append('Material mismatch: advisory only; check spool type')
        value=dict(identity=identity,job_key=bound[0] if bound else identity,printer_id=pid,job=dict(job),filename=job['filename'],file_sha256=profile['file_sha256'],
            mode=mode,state='pause_requested' if pause else 'warning' if reasons else 'ok',reason='; '.join(reasons),
            rows=rows,material_checks=material,summary='Print start: attention required' if reasons else 'Print start: OK',source='print_start',time=datetime.now(timezone.utc).isoformat(),attempt=uuid.uuid4().hex if pause else None,action='pause' if pause else None)
        if reasons and mode=='strict' and not pause:value['reason']+='; late observation: pause not requested'
        return self.save(value)

    def decision(self,pid,expected_revision,action,confirmed):
        value=self.snapshot(pid)['guard']
        if (confirmed is not True or action not in ('resume','cancel') or not value or
                value['revision']!=expected_revision or value['state']!='paused'):
            raise ValueError('Пауза или задание изменились. Обновите экран.')
        return self.save(dict(value,state=action+'_requested',action=action,attempt=uuid.uuid4().hex))

    def result(self,pid,attempt,state,reason=''):
        value=self.snapshot(pid)['guard']
        if not value or value.get('attempt')!=attempt:return None
        return self.save(dict(value,state=state,reason=value['reason']+('; '+reason if reason else '')))


def execute(owner,pid,client,ticket):
    """Exactly one attempt; caller owns admission and explicit URL policy."""
    from urllib.request import Request
    action=ticket['action']
    try:
        latest=owner.call('guard_snapshot',pid)['guard']
        if latest['attempt']!=ticket['attempt'] or not latest['state'].endswith('_requested'):raise ValueError('Command superseded')
        expected='printing' if action=='pause' else 'paused'
        status=client.status()['print_stats'];jobs=[j for j in client.history() if j.get('status')=='in_progress']
        job=ticket['job']
        if (status.get('state')!=expected or status.get('filename')!=job['filename'] or len(jobs)!=1 or
                any(jobs[0].get(k)!=job[k] for k in ('job_id','start_time','filename'))):
            raise ValueError('Current printer job/state differs')
        client.check_stop()
        # No retries or redirects. Only these three bounded Moonraker endpoints.
        with client.opener.open(Request(client.url+'/printer/print/'+action,data=b'{}',headers={'Content-Type':'application/json'},method='POST'),timeout=2) as response:
            value=json.loads(response.read(65536))
        if not isinstance(value,dict) or 'error' in value or 'result' not in value:raise ValueError('Command reply unknown')
        observed=client.status();owner.call('monitor_status',pid,observed)
        desired={'pause':'paused','resume':'printing','cancel':'cancelled'}[action]
        if observed['print_stats']['state']!=desired or observed['print_stats'].get('filename')!=job['filename']:raise ValueError('Command outcome unconfirmed')
        return owner.call('guard_result',pid,ticket['attempt'],{'pause':'paused','resume':'resumed','cancel':'cancelled'}[action])
    except Exception as exc:
        return owner.call('guard_result',pid,ticket['attempt'],'pause_failed' if action=='pause' else 'warning','Command not confirmed; no automatic retry: '+str(exc))
