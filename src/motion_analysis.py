"""Validate and summarize Klipper motion segments without editing inventory.

The diagnostic API has no sequence numbers and its clock differs from the
status clock. An uninterrupted socket and monotonic samples cannot prove that
all moves arrived or identify a spool. Results are for review only.
"""
import math


class MotionDataError(ValueError):
    pass


class HeadMotionSummary:
    def __init__(self):
        self.heads = [dict(net_mm=0.0, forward_mm=0.0, retraction_mm=0.0, segments=0, last_end=None) for _ in range(4)]
        self.valid = True
        self.reason = ''

    def add(self, head, rows):
        if not self.valid:
            raise MotionDataError(self.reason)
        try:
            if type(head) is not int or not 0 <= head < 4 or not isinstance(rows, list):
                raise MotionDataError('Invalid head or motion batch')
            h = self.heads[head]
            for row in rows:
                if not isinstance(row, (list, tuple)) or len(row) != 6:
                    raise MotionDataError('Malformed motion segment')
                timestamp, duration, speed, accel, pos, direction = row
                if (not isinstance(pos, (list, tuple)) or len(pos) != 3
                        or not isinstance(direction, (list, tuple)) or len(direction) != 3):
                    raise MotionDataError('Malformed motion vectors')
                vals = [timestamp, duration, speed, accel, *pos, *direction]
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in vals):
                    raise MotionDataError('Non-finite motion value')
                if duration < -1e-9:
                    raise MotionDataError('Invalid motion duration')
                duration = max(0.0, duration)
                if h['last_end'] is not None and timestamp < h['last_end'] - 1e-6:
                    raise MotionDataError('Overlapping or repeated motion segment')
                distance = (speed + 0.5 * accel * duration) * duration * direction[0]
                if not math.isfinite(distance):
                    raise MotionDataError('Motion distance overflow')
                h['net_mm'] += distance
                h['forward_mm'] += max(distance, 0)
                h['retraction_mm'] += max(-distance, 0)
                h['segments'] += 1
                h['last_end'] = timestamp + duration
        except MotionDataError as exc:
            self.valid = False
            self.reason = str(exc)
            raise

    def result(self):
        if not self.valid:
            raise MotionDataError(self.reason)
        return [{'head': n, 'net_mm': round(h['net_mm'], 3),
                 'forward_mm': round(h['forward_mm'], 3),
                 'retraction_mm': round(h['retraction_mm'], 3),
                 'segments': h['segments']} for n, h in enumerate(self.heads)]

    def compare_printer_total(self, total_mm, *, tolerance_mm=0.1):
        """Compare commanded head motion with U1's aggregate, not physical mass.

        A match catches some omissions; it does not prove spool identity or
        continuity. Flow-factor changes may cause legitimate differences.
        """
        if not self.valid:
            raise MotionDataError(self.reason)
        for value in (total_mm, tolerance_mm):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise MotionDataError('Printer total or tolerance unavailable')
        if total_mm <= 0 or tolerance_mm < 0:
            raise MotionDataError('Printer total or tolerance invalid')
        total = math.fsum(head['net_mm'] for head in self.heads)
        if not math.isfinite(total):
            raise MotionDataError('Motion total overflow')
        return {'head_total_mm': round(total, 3), 'printer_total_mm': round(total_mm, 3),
                'difference_mm': round(total - total_mm, 3),
                'matches': abs(total - total_mm) <= tolerance_mm}
