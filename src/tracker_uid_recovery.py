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
