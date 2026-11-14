"""Durable UID replacement segments; only observed paused boundaries are usable.

No balance writes here. Unknown/gapped changes are retained for manual review.
"""
import json
import math


class Replacements:
    def __init__(self,db):
        self.db=db
        db.executescript('''
          CREATE TABLE IF NOT EXISTS uid_replacement_state(job_key TEXT PRIMARY KEY,payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS uid_replacement_events(job_key TEXT NOT NULL,ordinal INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(job_key,ordinal));
        ''')

    def gap(self,printer_id):
        with self.db:
            for r in self.db.execute("SELECT s.* FROM uid_replacement_state s JOIN uid_jobs j USING(job_key) WHERE j.printer_id=? AND j.state='active'",(printer_id,)).fetchall():
                p=json.loads(r['payload']);p['gap']=True
                self.db.execute('UPDATE uid_replacement_state SET payload=? WHERE job_key=?',(json.dumps(p),r['job_key']))

    def observe(self,key,status,fleet):
        job=self.db.execute('SELECT * FROM uid_jobs WHERE job_key=?',(key,)).fetchone()
        if not job or job['state']!='active':return
        profile=self.db.execute('SELECT p.* FROM uid_recovery_profiles p JOIN uid_motion_captures c USING(history_key) WHERE c.key=?',(key,)).fetchone()
        if profile is None or profile['quarantined']:return
        plan=json.loads(profile['profile']);used=[i for i,w in enumerate(plan['logical_weights']) if w>0]
        if len(used)!=1:return
        channel=str(plan['mapping'][used[0]]);stats=status.get('print_stats',{});task=status.get('print_task_config',{})
        # This journal is for a physical spool change in the same head, not an
        # automatic head transition. Other mapping evidence is handled separately.
        if task.get('extruders_replenished')!=[0,1,2,3] or task.get('extruder_map_table')!=plan['mapping']:return
        if stats.get('filename')!=plan['filename']:return
        snap=fleet.get(job['printer_id'],{})
        if snap.get('state')!='ready':return
        counter=stats.get('filament_used');phase=stats.get('state')
        if type(counter) not in (int,float) or not math.isfinite(counter) or counter<0:return
        original=self.db.execute('SELECT * FROM uid_job_tools WHERE job_key=? AND channel=?',(key,channel)).fetchone()
        if original is None or not original['uid']:return
        stored=self.db.execute('SELECT payload FROM uid_replacement_state WHERE job_key=?',(key,)).fetchone()
        p=json.loads(stored[0]) if stored else dict(uid=original['uid'],spool_id=original['spool_id'],phase=None,counter=0,epoch=snap.get('epoch'),gap=False,blocked=False,next=0)
        obs=snap.get('channels',{}).get(channel,{})
        uid=obs.get('uid') if obs.get('state')=='present' else None
        if counter<p['counter']:p['blocked']=True
        event=None
        if uid and uid!=p['uid']:
            spool=self.db.execute('SELECT * FROM uid_spools WHERE uid=?',(uid,)).fetchone()
            proven=(not p['gap'] and not p['blocked'] and p['phase']=='paused' and phase=='paused'
                    and sum(o.get('uid')==uid and o.get('state')=='present' for printer in fleet.values() for o in printer.get('channels',{}).values())==1
                    and counter==p['counter'] and bool(p['epoch']) and snap.get('epoch')==p['epoch'] and spool is not None)
            event=dict(channel=channel,old_uid=p['uid'],old_spool_id=p['spool_id'],new_uid=uid,
                       new_spool_id=spool['spool_id'] if spool else None,counter_mm=counter,
                       new_remaining_mg=spool['remaining_mg'] if spool else None,
                       proven=proven,reason='Observed UID change at stable paused counter' if proven else 'Replacement boundary or identity unproven')
            p.update(uid=uid,spool_id=event['new_spool_id'],blocked=p['blocked'] or not proven,next=p['next']+1)
        # Missing tag during a paused removal is not a new spool. Keep the last
        # UID while still checking the counter. A gap remains until same UID seen.
        if uid==p['uid'] and not p['blocked']:p['gap']=False
        p.update(phase=phase,counter=counter,epoch=snap.get('epoch'))
        with self.db:
            if event is not None:
                self.db.execute('INSERT INTO uid_replacement_events VALUES(?,?,?)',(key,p['next']-1,json.dumps(event,sort_keys=True)))
                self.db.execute('UPDATE uid_jobs SET mapping_valid=0 WHERE job_key=?',(key,))
            self.db.execute('INSERT OR REPLACE INTO uid_replacement_state VALUES(?,?)',(key,json.dumps(p,sort_keys=True)))

    def events(self,key):
        return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM uid_replacement_events WHERE job_key=? ORDER BY ordinal',(key,))]
