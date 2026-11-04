"""EXPERIMENTAL Klipper object: per-physical-head commanded filament motion.

Not installed automatically. This reads Klipper's per-extruder last_position;
it does not monkeypatch moves, control the printer, identify spools, or measure
actual filament. Restart/recovery, user spool changes, runout and calibration
must be addressed before any automatic inventory debit uses this evidence.
"""
import copy
import logging
import math
import time
import uuid

LOG = logging.getLogger(__name__)


class TrackerMotion:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.epoch = uuid.uuid4().hex
        self.record = None
        self.baseline = None
        self.printer.register_event_handler('print_stats:new_task_start', self._start)
        self.printer.register_event_handler('print_stats:stop', self._stop)
        self.printer.register_event_handler('filament_feed:port', self._spool_event)

    def _tag_uids(self):
        detector = self.printer.lookup_object('filament_detect', None)
        if detector is None:
            return None
        entries = detector.get_status(0).get('info')
        if not isinstance(entries, list) or len(entries) != 4:
            return None
        result = []
        for entry in entries:
            if not isinstance(entry, dict) or 'CARD_UID' not in entry:
                return None
            uid = entry['CARD_UID']
            if isinstance(uid, list) and len(uid) in (4, 7, 10) and all(type(x) is int and 0 <= x <= 255 for x in uid) and any(uid):
                result.append(''.join(f'{x:02x}' for x in uid))
            elif type(uid) is int and uid == 0:
                result.append(None)
            else:
                return None
        return result

    def _spool_event(self, channel, detected):
        # Spool movement during a print is evidence for review, not proof that
        # a particular tagged spool is unchanged or a measured consumption.
        try:
            if self.record is not None and self.record['state'] == 'active':
                if type(channel) is not int or not 0 <= channel < 4 or type(detected) is not bool:
                    self.record['valid'] = False
                    self.record['reason'] = 'Unrecognised spool port event'
                    return
                self.record['spool_port_events'][channel] = True
                if detected is True:
                    self.record['spool_insert_events'][channel] = True
        except Exception:
            LOG.exception('Tracker spool event could not be recorded; print remains unaffected')

    def _positions(self):
        heads = self.printer.lookup_object('extruder_list', [])
        if len(heads) != 4:
            raise ValueError('Four physical extruders are required')
        result = [head.last_position for head in heads]
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in result):
            raise ValueError('A physical extruder position is invalid')
        return result

    def _start(self):
        # Never propagate monitoring errors into a physical print operation.
        try:
            stats = self.printer.lookup_object('print_stats')
            if self.record is not None and self.record['state'] == 'active':
                self.record['valid'] = False
                self.record['reason'] = 'Overlapping job start'
                return
            self.baseline = self._positions()
            prior_usage = getattr(stats, 'filament_used', None)
            current_layer = getattr(stats, 'info_current_layer', None)
            resumed = (not isinstance(prior_usage, (int, float)) or isinstance(prior_usage, bool)
                       or not math.isfinite(prior_usage) or prior_usage > 0.000001
                       or (current_layer is not None and current_layer > 1))
            self.record = {'schema': 1, 'epoch': self.epoch, 'capture_id': uuid.uuid4().hex,
                           'filename': str(getattr(stats, 'filename', '')), 'started_at': time.time(),
                           'state': 'active', 'valid': not resumed, 'reason': 'Recovery or prior usage' if resumed else '',
                           'head_mm': [0.0] * 4, 'initial_tag_uids': self._tag_uids(),
                           'spool_port_events': [False] * 4, 'spool_insert_events': [False] * 4,
                           'identity_verified': False, 'manual_continuity': [False] * 4}
        except Exception:
            self.baseline = None
            self.record = None
            LOG.exception('Tracker motion could not start; print remains unaffected')

    def _measure(self):
        if self.record is None or self.baseline is None:
            return
        try:
            current = self._positions()
            delta = [value - base for value, base in zip(current, self.baseline)]
            if any(not math.isfinite(v) or v < -0.001 for v in delta):
                raise ValueError('Net per-head motion is invalid')
            self.record['head_mm'] = [max(0.0, value) for value in delta]
        except Exception as exc:
            self.record['valid'] = False
            self.record['reason'] = str(exc)[:200]
            LOG.exception('Tracker motion evidence invalid; print remains unaffected')

    def _stop(self):
        if self.record is None or self.record['state'] != 'active':
            return
        try:
            self._measure()
            stats = self.printer.lookup_object('print_stats')
            state = getattr(stats, 'state', None)
            self.record['final_tag_uids'] = self._tag_uids()
            self.record['state'] = 'completed' if state == 'complete' else 'not_completed'
            if state != 'complete':
                self.record['valid'] = False
                self.record['reason'] = 'Print did not complete'
            self.record['finished_at'] = time.time()
        except Exception:
            self.record['valid'] = False
            self.record['state'] = 'not_completed'
            self.record['reason'] = 'Completion could not be verified'
            LOG.exception('Tracker motion could not finish; print remains unaffected')

    def get_status(self, eventtime):
        if self.record is not None and self.record['state'] == 'active':
            self._measure()
        return {'capture': copy.deepcopy(self.record)}


def load_config(config):
    return TrackerMotion(config)
