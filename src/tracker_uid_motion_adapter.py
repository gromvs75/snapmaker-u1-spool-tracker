"""Bench boundary for MotionStreamRecorder evidence; no sockets or legacy writes.

Call observe_start while the history identity AND UID binding are known. A late
history record cannot reconstruct that binding. Terminal motion only: net motion
can decrease on retraction, so intermediate snapshots are not debit checkpoints.
"""
import json
import math
from tracker_uid_accounting import job_key, mg
from motion_allocation import provisional_allocation


class UidMotionAdapter:
    def __init__(self, service):
        self.service = service
        self.db = service.accounting.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS uid_motion_starts (
                job_key TEXT PRIMARY KEY, context TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS uid_motion_review (
                id INTEGER PRIMARY KEY, job_key TEXT NOT NULL, reason TEXT NOT NULL);
        ''')

    def _review(self, key, reason):
        with self.db:
            self.db.execute('INSERT INTO uid_motion_review(job_key,reason) SELECT ?,? WHERE NOT EXISTS (SELECT 1 FROM uid_motion_review WHERE job_key=? AND reason=?)', (key, reason, key, reason))
        return {'status': 'review', 'reason': reason}

    @staticmethod
    def source(epoch, capture_id):
        if any(not isinstance(v, str) or not v or len(v) > 128 for v in (epoch, capture_id)):
            raise ValueError('Capture identity unavailable')
        return json.dumps([epoch, capture_id])

    def observe_start(self, printer_id, history, *, observed, capture_id, epoch, start, channels):
        """Explicit observed start, never called retrospectively from history replay.

        channels includes every physical head allowed to feed during this capture,
        including replacement heads. All must have a confirmed UID at start.
        """
        key = job_key(printer_id, history['job_id'], str(history['start_time']))
        try:
            if observed is not True or history.get('status') != 'in_progress':
                raise ValueError('Start was not observed')
            for channel in channels:
                assigned=self.db.execute('SELECT spool_id FROM manual_assignments WHERE printer_id=? AND channel=?',(printer_id,channel)).fetchone()
                if assigned and start.get('slots',{}).get(str(int(channel)+1))!=assigned['spool_id']:
                    raise ValueError('Manual material snapshot does not match assigned spool')
            source = self.source(epoch, capture_id)
            context = json.dumps({'filename': history['filename'], 'start_time': history['start_time'],
                                  'start': start, 'channels': sorted(channels), 'source': source},
                                 sort_keys=True, allow_nan=False)
            old = self.db.execute('SELECT context FROM uid_motion_starts WHERE job_key=?', (key,)).fetchone()
            if old and old[0] != context:
                raise ValueError('Start evidence changed')
            self.service.begin(printer_id, history['job_id'], str(history['start_time']), channels, source)
            # A crash between begin and this insert fails closed: finish requires both.
            with self.db:
                self.db.execute('INSERT OR IGNORE INTO uid_motion_starts VALUES(?,?)', (key, context))
            return {'status': 'started', 'job_key': key}
        except (ValueError, KeyError, TypeError) as exc:
            return self._review(key, str(exc))

    def finish(self, printer_id, history, evidence, *, bound_key=None):
        key = bound_key or job_key(printer_id, history['job_id'], str(history['start_time']))
        try:
            row = self.db.execute('SELECT context FROM uid_motion_starts WHERE job_key=?', (key,)).fetchone()
            if row is None:
                raise ValueError('No observed start binding')
            context = json.loads(row[0])
            state = history['status']
            if state not in ('completed', 'cancelled'):
                raise ValueError('Terminal history required')
            if evidence.get('complete') is not True or evidence.get('continuous') is not True:
                raise ValueError('Complete uninterrupted motion evidence required')
            if self.source(evidence['epoch'], evidence['capture_id']) != context['source']:
                raise ValueError('Motion capture changed')
            profile = evidence['profile']
            if (history['filename'] != context['filename'] or profile['filename'] != context['filename']
                    or profile['started_at'] != context['start_time'] or evidence['start'] != context['start']):
                raise ValueError('Motion profile or start snapshot does not match job')
            heads = evidence['heads']
            if not isinstance(heads, list) or len(heads) != 4:
                raise ValueError('Four physical head totals required')
            for i, head in enumerate(heads):
                value = head['net_mm']
                if (type(head['head']) is not int or head['head'] != i or type(value) not in (float, int)
                        or not math.isfinite(value) or value < 0):
                    raise ValueError('Invalid physical head total')
            comparison = evidence['comparison']
            total = comparison['printer_total_mm']
            if (comparison.get('matches') is not True or type(total) not in (float, int)
                    or not math.isfinite(total) or total <= 0
                    or abs(math.fsum(h['net_mm'] for h in heads) - total) > .102):
                raise ValueError('Motion differs from printer total')
            feed, tags = evidence['feed'], evidence['tags']
            if feed.get('valid') is not True or tags.get('known') is not True:
                raise ValueError('Feeder or tag evidence unavailable')
            for obj, field in ((feed, 'covered'), (feed, 'insertions'), (tags, 'unchanged')):
                if not isinstance(obj.get(field), list) or len(obj[field]) != 4 or any(type(v) is not bool for v in obj[field]):
                    raise ValueError('Incomplete continuity evidence')
            for i, head in enumerate(heads):
                if head['net_mm'] > 0 and (not feed['covered'][i] or feed['insertions'][i] or not tags['unchanged'][i]):
                    raise ValueError('Spool continuity lost')
            # Existing estimator is read-only. Identity is supplied by the UID
            # service's start binding, never by legacy slot IDs at completion.
            allocation = provisional_allocation(heads, context['start'], context['start'], profile)
            totals = {ch: 0 for ch in context['channels']}
            for item in allocation:
                ch = str(item['head'])
                if ch not in totals:
                    raise ValueError('Consumption on a head without start binding')
                if item.get('estimated_g') is None:
                    raise ValueError('Mass parameters unavailable')
                totals[ch] = mg(item['estimated_g'])
            result = self.service.apply(key, 1, totals, state=state, source=context['source'], basis='motion_estimate')
            return {'status': result, 'totals_mg': totals}
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            return self._review(key, str(exc))

    def observation_gap(self, printer_id, reason):
        """Motion socket loss also invalidates jobs even if UID socket stays live."""
        rows = self.db.execute("SELECT job_key FROM uid_jobs WHERE printer_id=? AND state='active'", (printer_id,)).fetchall()
        with self.db:
            self.db.execute("UPDATE uid_jobs SET mapping_valid=0 WHERE printer_id=? AND state='active'", (printer_id,))
            self.db.executemany('INSERT INTO uid_motion_review(job_key,reason) SELECT ?,? WHERE NOT EXISTS (SELECT 1 FROM uid_motion_review WHERE job_key=? AND reason=?)',
                                [(r[0], reason, r[0], reason) for r in rows])
