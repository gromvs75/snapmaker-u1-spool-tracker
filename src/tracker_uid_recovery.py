"""Read-only recovery proposals. No mutation of balances or accounting validity.

Persist the verified active-job plan through the SQLite owner, before a gap.
Completion/status is supplied by Moonraker, never inferred from the slicer.
"""
import hashlib
import json
import math

TERMINAL={'completed','cancelled','error','klippy_shutdown','klippy_disconnect','interrupted'}


def mass(length,parameter):
    diameter=parameter['diameter_mm'];density=parameter['density_g_cm3']
    if any(type(v) not in (float,int) or not math.isfinite(v) or v<=0 for v in (diameter,density)):
        raise ValueError('Material parameters unavailable')
    return round(length*math.pi*(diameter/2)**2*density) # mm³ × g/cm³ = mg


class Recovery:
    def __init__(self,db):
        self.db=db
        db.execute('''CREATE TABLE IF NOT EXISTS uid_recovery_profiles (
          history_key TEXT PRIMARY KEY, profile TEXT NOT NULL, quarantined INTEGER NOT NULL DEFAULT 0)''')
        db.execute('CREATE TABLE IF NOT EXISTS uid_recovery_receipts (job_key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        db.commit()

    def remember(self,history_key,profile):
        digest=profile.get('file_sha256')
        if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Verified G-code hash required')
        payload=json.dumps(profile,sort_keys=True,allow_nan=False)
        old=self.db.execute('SELECT profile,quarantined FROM uid_recovery_profiles WHERE history_key=?',(history_key,)).fetchone()
        if old:
            if old[0]!=payload:
                with self.db:self.db.execute('UPDATE uid_recovery_profiles SET quarantined=1 WHERE history_key=?',(history_key,))
                raise ValueError('Saved G-code plan changed')
            return 'quarantined' if old[1] else 'duplicate'
        with self.db:self.db.execute('INSERT INTO uid_recovery_profiles VALUES(?,?,0)',(history_key,payload))
        return 'saved'

    def preview(self,key,layer=None):
        row=self.db.execute('SELECT * FROM uid_motion_captures WHERE key=?',(key,)).fetchone()
        if row is None or not row['history']:raise ValueError('No bound history')
        history=json.loads(row['history'])
        if history['status'] not in TERMINAL:raise ValueError('Terminal job required')
        job=self.db.execute('SELECT * FROM uid_jobs WHERE job_key=?',(key,)).fetchone()
        if job['state']!='active' or job['last_sequence']>=0:raise ValueError('Already accounted or resolved')
        saved=self.db.execute('SELECT * FROM uid_recovery_profiles WHERE history_key=?',(row['history_key'],)).fetchone()
        if saved is None or saved['quarantined']:raise ValueError('No trusted saved plan')
        profile=json.loads(saved['profile'])
        if profile['filename']!=history['filename'] or profile['started_at']!=history['start_time']:
            raise ValueError('Plan/history identity changed')
        mapping=profile['mapping'];weights=profile['logical_weights']
        if (len(mapping)!=4 or sorted(mapping)!=[0,1,2,3] or profile['replenished']!=[0,1,2,3]
                or len(weights)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in weights)):
            raise ValueError('Unsupported mapping or plan')
        used=[i for i,w in enumerate(weights) if w>0]
        if not used:raise ValueError('Empty plan')
        bindings={t['channel']:t['spool_id'] for t in self.db.execute('SELECT * FROM uid_job_tools WHERE job_key=?',(key,))}
        if any(str(mapping[i]) not in bindings for i in used):raise ValueError('Missing original spool binding')
        reasons=[r[0] for r in self.db.execute('SELECT reason FROM uid_motion_review WHERE job_key=?',(key,))]
        if any('automatic' in r.lower() or 'mapping' in r.lower() or 'identity' in r.lower() for r in reasons):
            raise ValueError('Automatic transition or ambiguous identity remains blocked')
        counter=history.get('filament_used');totals={};ranges=None
        if type(counter) in (int,float) and math.isfinite(counter) and counter>0 and len(used)==1:
            i=used[0];totals[str(mapping[i])]=mass(counter,profile['parameters'][i]);basis='printer_history_estimate'
        elif history['status']=='completed':
            totals={str(mapping[i]):round(weights[i]*1000) for i in used};basis='completed_slicer_estimate'
        elif layer is not None:
            if type(layer) is not int or layer<0:raise ValueError('Invalid layer')
            data=profile.get('layers',{}).get(str(layer))
            if data is None:raise ValueError('Layer estimate unavailable')
            ranges={str(mapping[i]):[mass(data['low_mm'][i],profile['parameters'][i]),mass(data['high_mm'][i],profile['parameters'][i])] for i in used}
            basis='layer_range_estimate'
        else:raise ValueError('No usable history counter; layer estimate requires an explicit layer')
        revision=hashlib.sha256(json.dumps([dict(row),dict(job),dict(saved),layer],sort_keys=True).encode()).hexdigest()
        return dict(job_key=key,history_status=history['status'],basis=basis,totals_mg=totals,ranges_mg=ranges,
                    original_spools=bindings,revision=revision,requires_confirmation=True,authorizes_debit=False,
                    warning='Estimated usage only. Spool continuity and unobserved automatic changes require review.')

    def calculate(self,key,status,digest,accounting,fleet):
        """Completed-job estimate; source identities/amounts come from the start.

        Caller obtains fresh terminal status and re-verifies the file. A single
        proven exhausted-source transition can use saved Tracker remainder.
        """
        from tracker_uid_accounting import mg
        from tool_mapping import validate_mapping
        job=accounting.job(key)
        if job is None:raise ValueError('No original job')
        if job['state']=='completed':return {'status':'duplicate'}
        if job['state']!='active' or job['last_sequence']>=0:raise ValueError('Job already resolved or partially debited')
        if job['mapping_valid']:return {'status':'pending_motion'}
        capture=self.db.execute('SELECT * FROM uid_motion_captures WHERE key=?',(key,)).fetchone()
        history=json.loads(capture['history'])
        saved=self.db.execute('SELECT * FROM uid_recovery_profiles WHERE history_key=?',(capture['history_key'],)).fetchone()
        if saved is None or saved['quarantined']:raise ValueError('Saved plan unavailable or restored/quarantined')
        plan=json.loads(saved['profile']);ctx=json.loads(self.db.execute('SELECT context FROM uid_motion_starts WHERE job_key=?',(key,)).fetchone()[0])
        if (history['status']!='completed' or status['print_stats']['state']!='complete'
                or history['filename']!=plan['filename'] or status['print_stats']['filename']!=plan['filename']
                or history['start_time']!=plan['started_at'] or digest!=plan['file_sha256']):
            raise ValueError('Completion, history or file identity mismatch')
        reasons=[r[0] for r in self.db.execute('SELECT reason FROM uid_motion_review WHERE job_key=?',(key,))]
        forbidden=('Ambiguous history/start match','History identity changed','Terminal history changed','Conflicting history records','Tool mapping changed during capture','Automatic replacement mode changed')
        if any(any(reason in r for reason in forbidden) for r in reasons):raise ValueError('Conflicting job or replacement evidence')
        start_mode=plan.get('auto_replenish');task=status['print_task_config'];end_mode=task.get('auto_replenish_filament')
        if type(start_mode) is not bool or type(end_mode) is not bool or start_mode!=end_mode:
            raise ValueError('Automatic replacement mode unknown or changed')
        initial=validate_mapping(plan['mapping']);final=validate_mapping(task['extruder_map_table'])
        repl=validate_mapping(task['extruders_replenished'])
        if plan['replenished']!=[0,1,2,3]:raise ValueError('Transition predates saved plan')
        weights=plan['logical_weights']
        if len(weights)!=4 or any(type(w) not in (int,float) or not math.isfinite(w) or w<0 for w in weights):raise ValueError('Invalid planned weights')
        tools={t['channel']:t for t in job['tools']};totals={ch:0 for ch in tools}
        used=[i for i,w in enumerate(weights) if w>0]
        changed=[h for h in range(4) if repl[h]!=h]
        if not used:raise ValueError('Empty print plan')
        if changed:
            if not start_mode:raise ValueError('Replacement evidence contradicts disabled automatic mode; verify manual transition')
            if len(changed)!=1 or len(used)!=1:raise ValueError('Multiple transitions or tools need distribution review')
            source=changed[0];target=repl[source];logical=used[0]
            if initial[logical]!=source or final[logical]!=target or any(final[i]!=initial[i] for i in range(4) if i!=logical):raise ValueError('Transition mapping inconsistent')
            def feed(snapshot,h):return snapshot.get('filament_feed left' if h<2 else 'filament_feed right',{}).get('extruder'+str(h),{})
            before=feed(plan.get('feed_start',{}),source);after=feed(status,source)
            if (before.get('filament_detected') is not True or after.get('filament_detected') is not False
                    or before.get('module_exist') is not True or after.get('module_exist') is not True
                    or before.get('disable_auto') is not False or after.get('disable_auto') is not False
                    or feed(status,target).get('filament_detected') is not True):raise ValueError('Source exhaustion or target feed is unproven')
            if str(source) not in tools or str(target) not in tools:raise ValueError('Replacement spool not bound at start')
            sid=tools[str(source)]['spool_id'];remaining=mg(ctx['start']['spools'][sid]['remaining_g']);total=mg(weights[logical])
            if remaining<=0 or total<=remaining:raise ValueError('Planned total contradicts exhausted spool remainder')
            totals[str(source)]=remaining;totals[str(target)]=total-remaining
            source_label='slicer_and_exhausted_remainder'
        else:
            if final!=initial:raise ValueError('Mapping changed without automatic transition')
            # A known manual/runout event cannot be silently treated as ordinary completion.
            for i in used:
                h=initial[i];channel=status.get('filament_feed left' if h<2 else 'filament_feed right',{}).get('extruder'+str(h),{})
                if channel.get('filament_detected') is not True:raise ValueError('Used channel is empty or unknown')
                if str(h) not in totals:raise ValueError('Missing original tool binding')
                totals[str(h)]+=mg(weights[i])
            source_label='completed_slicer_estimate'
            counter=history.get('filament_used')
            if len(used)==1 and type(counter) in (float,int) and math.isfinite(counter) and counter>0:
                i=used[0];totals[str(initial[i])]=mass(counter,plan['parameters'][i]);source_label='printer_history_estimate'
        snapshot=fleet.get(job['printer_id'],{})
        if snapshot.get('state')!='ready':raise ValueError('Fresh spool observations unavailable')
        # Only identifiable original spools auto-recover after a gap. Manual
        # assignments need an explicit later confirmation, not an inferred UID.
        for ch,t in tools.items():
            if not totals[ch]:continue
            obs=snapshot.get('channels',{}).get(ch,{})
            if not t['uid'] or obs.get('state')!='present' or obs.get('uid')!=t['uid']:
                raise ValueError('Original spool identity is not confirmed; manual review required')
            sid=t['spool_id'];original=mg(ctx['start']['spools'][sid]['remaining_g'])
            actual=self.db.execute('SELECT remaining_mg FROM uid_spools WHERE spool_id=?',(sid,)).fetchone()[0]
            if actual!=original:raise ValueError('Spool balance changed since start')
        if self.db.execute('SELECT 1 FROM uid_manual_resolutions WHERE job_key=?',(key,)).fetchone():raise ValueError('Job manually resolved')
        receipt=json.dumps(dict(totals_mg=totals,estimate_source=source_label,auto_replenish=start_mode,file_sha256=digest,history_key=capture['history_key']),sort_keys=True)
        def validate(current,current_tools):
            if current['state']!='active' or current['last_sequence']!=-1 or current['source']!=job['source']:raise ValueError('Job changed')
            if {t['channel']:t['spool_id'] for t in current_tools}!={ch:t['spool_id'] for ch,t in tools.items()}:raise ValueError('Bindings changed')
            self.db.execute('INSERT INTO uid_recovery_receipts VALUES(?,?)',(key,receipt))
        result=accounting.apply(key,1,totals,state='completed',source=job['source'],basis='calculated_history',recovery_validator=validate)
        return dict(status=result,totals_mg=totals,estimate_source=source_label,auto_replenish=start_mode)
