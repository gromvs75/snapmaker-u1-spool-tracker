"""Single controlling-thread bridge for recorder callbacks and history batches.

Reserves UID bindings immediately under a capture identity; history is an alias,
never a reason to consult current slots. No network or legacy debit operations.
"""
import json
import math
import uuid
from tracker_uid_accounting import job_key
from tracker_uid_recovery import Recovery, TERMINAL


class MotionLifecycle:
    def __init__(self, adapter):
        self.adapter = adapter
        self.db = adapter.db
        self.session = uuid.uuid4().hex
        self.recovery = Recovery(self.db)
        from tracker_uid_replacements import Replacements
        self.replacements = Replacements(self.db)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS uid_motion_captures (
                key TEXT PRIMARY KEY, printer_id TEXT NOT NULL, source TEXT NOT NULL,
                observed REAL NOT NULL, filename TEXT NOT NULL, history_key TEXT UNIQUE,
                history TEXT, evidence TEXT, session TEXT NOT NULL,
                UNIQUE(printer_id,source));
        ''')
        # A new owner cannot certify uninterrupted motion from a previous owner.
        for row in self.db.execute("SELECT DISTINCT c.printer_id FROM uid_motion_captures c JOIN uid_jobs j ON j.job_key=c.key WHERE j.state='active'").fetchall():
            self.replacements.gap(row[0])
            adapter.observation_gap(row[0], 'Motion lifecycle restarted')

    def start(self, printer_id, *, filename, observed_at, capture_id, epoch, start, channels):
        if type(observed_at) not in (float, int) or not math.isfinite(observed_at) or observed_at <= 0 or not filename:
            raise ValueError('Invalid observed start')
        source = self.adapter.source(epoch, capture_id)
        history = dict(job_id='capture:' + source, start_time=observed_at, filename=filename, status='in_progress')
        result = self.adapter.observe_start(printer_id, history, observed=True, capture_id=capture_id,
                                            epoch=epoch, start=start, channels=channels)
        if result['status'] != 'started': return result
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO uid_motion_captures(key,printer_id,source,observed,filename,session) VALUES(?,?,?,?,?,?)',
                            (result['job_key'], printer_id, source, observed_at, filename, self.session))
        return result

    def attach_active(self, printer_id, profile, observed_at, epoch, capture_id):
        """A verified running print can use a completed-file estimate on prior manual placements."""
        started = float(profile['started_at'])
        jid = profile['history_job_id']
        key = job_key(printer_id, jid, str(started))
        accounting = self.adapter.service.accounting
        if accounting.job(key) or accounting.legacy_history(printer_id, jid, started):
            return None
        if self.db.execute('SELECT 1 FROM uid_motion_captures WHERE history_key=?', (key,)).fetchone():
            return None
        channels = sorted({str(profile['mapping'][i]) for i, w in enumerate(profile['logical_weights']) if w > 0})
        if not channels or profile['replenished'] != [0, 1, 2, 3]:
            return None
        fleet = self.adapter.service.fleet.snapshot()
        start = accounting.catalog.inventory_snapshot(printer_id, fleet)
        for ch in channels:
            row = self.db.execute("""SELECT a.spool_id FROM manual_assignments a
                JOIN manual_placement_times p USING(printer_id,channel,version)
                WHERE a.printer_id=? AND a.channel=? AND a.confirmed=1 AND a.token=? AND p.saved<=?""",
                (printer_id, ch, accounting.catalog.SAVED_PLACEMENT, started)).fetchone()
            if not row or start['slots'].get(str(int(ch)+1)) != row['spool_id']:
                return None
        history = dict(job_id=jid, start_time=started, filename=profile['filename'], status='in_progress')
        result = self.adapter.bind_active(printer_id, history, capture_id, epoch, start, channels)
        if result['status'] != 'started':
            return None
        with self.db:
            self.db.execute('INSERT INTO uid_motion_captures VALUES(?,?,?,?,?,?,?,NULL,?)',
                (key, printer_id, self.adapter.source(epoch,capture_id), observed_at, history['filename'],
                 key, json.dumps(history), self.session))
        self.recovery.remember(key, profile)
        return start

    def history_timeout(self, printer_id, reason):
        # Both observed starts and late attachments have an independent motion
        # stream. An HTTP timeout is not evidence that this stream disconnected.
        # Keep only captures already bound to a trusted active-job plan; terminal
        # accounting still verifies motion/feed continuity, placement and file.
        captures = self.db.execute("""SELECT c.history_key,p.quarantined
            FROM uid_motion_captures c JOIN uid_jobs j ON j.job_key=c.key
            LEFT JOIN uid_recovery_profiles p ON p.history_key=c.history_key
            WHERE c.printer_id=? AND j.state='active'""", (printer_id,)).fetchall()
        if not captures or any(not r['history_key'] or r['quarantined'] != 0 for r in captures):
            self.disconnected(printer_id, reason)

    def recovery_profile(self, printer_id, history, profile):
        if history.get('status')!='in_progress':raise ValueError('Plan must be saved while job is active')
        if profile.get('filename')!=history['filename'] or profile.get('started_at')!=history['start_time']:
            raise ValueError('Profile/history mismatch')
        self.history(printer_id,[history])
        hk=job_key(printer_id,history['job_id'],str(float(history['start_time'])))
        capture=self.db.execute('SELECT key,session FROM uid_motion_captures WHERE history_key=?',(hk,)).fetchone()
        if capture is None:return 'pending_observed_start'
        if capture['session']=='manual_history':return 'held_manual_history'
        return self.recovery.remember(hk,profile)

    def replacement_observe(self,printer_id,history,status):
        hk=job_key(printer_id,history['job_id'],str(float(history['start_time'])))
        row=self.db.execute('SELECT key FROM uid_motion_captures WHERE history_key=?',(hk,)).fetchone()
        if row:self.replacements.observe(row['key'],status,self.adapter.service.fleet.snapshot())

    def recovery_terminal(self, printer_id, history, status, digest):
        self.history(printer_id,[history])
        hk=job_key(printer_id,history['job_id'],str(float(history['start_time'])))
        row=self.db.execute('SELECT key FROM uid_motion_captures WHERE history_key=?',(hk,)).fetchone()
        if row is None:return {'status':'review','reason':'No observed start'}
        try:
            return self.recovery.calculate(row['key'],status,digest,self.adapter.service.accounting,self.adapter.service.fleet.snapshot())
        except (ValueError,KeyError,TypeError,IndexError) as exc:
            return self.adapter._review(row['key'],'Recovery: '+str(exc))

    def recovery_preview(self, key, layer=None):
        return self.recovery.preview(key,layer)

    def disconnected(self, printer_id, reason='Motion connection lost'):
        self.replacements.gap(printer_id)
        self.adapter.observation_gap(printer_id, reason)

    def terminal(self, printer_id, evidence):
        source = self.adapter.source(evidence['epoch'], evidence['capture_id'])
        row = self.db.execute('SELECT * FROM uid_motion_captures WHERE printer_id=? AND source=?', (printer_id, source)).fetchone()
        if row is None: return self.adapter._review(source, 'Terminal capture without observed start')
        payload = json.dumps(evidence, sort_keys=True, allow_nan=False)
        if row['evidence'] and row['evidence'] != payload:
            return self.adapter._review(row['key'], 'Terminal capture evidence changed')
        with self.db:
            self.db.execute('UPDATE uid_motion_captures SET evidence=? WHERE key=?', (payload, row['key']))
        return self._finish(row['key'])

    def history(self, printer_id, jobs):
        """Process a complete polling batch; ambiguous matches never pick a winner.

        The 30s bound matches the collector's existing wall-clock/profile check.
        Both capture→job and job→capture must be unique. Clock skew outside the
        bound requires review. Filename alone is never sufficient.
        """
        unique = {}
        imported = []
        for job in jobs:
            t = job.get('start_time')
            if type(t) not in (int, float) or not math.isfinite(t) or t <= 0:
                continue
            if job.get('status') not in TERMINAL | {'in_progress'}: continue
            legacy = self.adapter.service.accounting.legacy_history(printer_id, job['job_id'], t)
            if legacy:
                imported.append({'status': 'legacy_duplicate' if legacy['status']=='committed' else 'review', 'reason': 'Imported history is fenced', 'legacy_key': legacy['legacy_key']})
                continue
            key = job_key(printer_id, job['job_id'], str(float(t)))
            if key in unique and unique[key] != job:
                return [self.adapter._review(key, 'Conflicting history records')]
            unique[key] = job
        # Imported receipts already have a fenced 1.x identity. They cannot
        # be a start observation for a subsequent print with the same name.
        captures = self.db.execute("SELECT * FROM uid_motion_captures WHERE printer_id=? AND session NOT IN ('legacy','manual_history')",
                                   (printer_id,)).fetchall()
        candidates = {r['key']: [k for k, j in unique.items() if j['filename'] == r['filename'] and (k == r['key'] if r['key'] == r['history_key'] else abs(j['start_time']-r['observed']) <= 30)] for r in captures}
        results = imported
        for row in captures:
            keys = candidates[row['key']]
            if not keys: continue
            if len(keys) != 1 or sum(keys[0] in ks for ks in candidates.values()) != 1:
                with self.db:
                    self.db.execute('UPDATE uid_jobs SET mapping_valid=0 WHERE job_key=?', (row['key'],))
                results.append(self.adapter._review(row['key'], 'Ambiguous history/start match'))
                continue
            hk = keys[0]
            manual = self.db.execute("SELECT key FROM uid_motion_captures WHERE history_key=? AND session='manual_history'",(hk,)).fetchone()
            if manual:
                with self.db:self.db.execute('UPDATE uid_jobs SET mapping_valid=0 WHERE job_key=?',(row['key'],))
                results.append(self.adapter._review(row['key'],'History already reserved for explicit manual accounting'))
                continue
            if row['history_key'] and row['history_key'] != hk:
                results.append(self.adapter._review(row['key'], 'History identity changed'))
                continue
            job = unique[hk]
            old = json.loads(row['history']) if row['history'] else None
            if old and old['status'] in TERMINAL and old['status'] != job['status']:
                # Polling a stale active row must not regress a terminal receipt.
                if job['status'] == 'in_progress': continue
                # U1 can report an error (e.g. tangled filament), then resume
                # this exact history identity and eventually finish or cancel.
                # Keep the original capture/placement; all continuity checks
                # still apply. Other terminal changes remain conflicts.
                if not (old['status']=='error' and job['status'] in ('completed','cancelled')):
                    results.append(self.adapter._review(row['key'], 'Terminal history changed'))
                    continue
            with self.db:
                context = json.loads(self.db.execute('SELECT context FROM uid_motion_starts WHERE job_key=?', (row['key'],)).fetchone()[0])
                context['start_time'] = job['start_time']
                self.db.execute('UPDATE uid_motion_starts SET context=? WHERE job_key=?', (json.dumps(context, sort_keys=True), row['key']))
                self.db.execute('UPDATE uid_motion_captures SET history_key=?,history=? WHERE key=?', (hk, json.dumps(job, sort_keys=True), row['key']))
            results.append(self._finish(row['key']))
        return results

    def _finish(self, key):
        if self.db.execute('SELECT 1 FROM uid_manual_resolutions WHERE job_key=?',(key,)).fetchone():
            return {'status':'resolved_without_debit'}
        row = self.db.execute('SELECT * FROM uid_motion_captures WHERE key=?', (key,)).fetchone()
        if not row['history'] or not row['evidence']: return {'status': 'pending'}
        history = json.loads(row['history'])
        if history['status'] == 'in_progress': return {'status': 'pending'}
        evidence = json.loads(row['evidence'])
        if evidence.get('terminal_state') != history['status']:
            return self.adapter._review(key, 'Motion/history terminal states differ')
        if row['key'] == row['history_key']:
            if history['status'] != 'completed':
                return self.adapter._review(key, 'Partial observation cannot account a partial print')
            return {'status': 'pending_calculated_completion'}
        return self.adapter.finish(row['printer_id'], history, evidence, bound_key=key)
