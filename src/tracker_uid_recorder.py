"""UID-only U1 stream recorder promoted from the verified lifecycle bench.

Amounts are estimates; untagged spool identity follows the user's assignment.
Klipper provides no sequence numbers, so matching the aggregate counter is a
consistency check, not proof of measured physical consumption or spool identity.
"""
import json
import logging
from logging.handlers import RotatingFileHandler
import socket
import threading
import time
import uuid
from motion_analysis import HeadMotionSummary, MotionDataError
from motion_allocation import provisional_allocation
from feed_evidence import FeedEvidence
from tag_evidence import TagEvidence
from tool_mapping import validate_mapping, MappingError

class StreamError(Exception):
    pass


class MotionStreamRecorder:
    def __init__(self, store, lifecycle, printer_id, channels=None):
        self.lifecycle = lifecycle
        self.printer_id = printer_id
        self.channels = None if channels is None else tuple(channels)
        if lifecycle is None or not printer_id:raise ValueError("UID lifecycle and printer identity required")
        self.store = store
        self.stop_event = threading.Event()
        self.thread = None
        self.logger = logging.getLogger('tracker_uid.motion.'+printer_id+'.'+uuid.uuid4().hex)
        self.logger.propagate = False
        self.logger.setLevel(logging.INFO)
        store.directory.mkdir(parents=True, exist_ok=True)
        self.handler = RotatingFileHandler(store.directory / 'motion-diagnostic.jsonl', maxBytes=32_000_000,
                                           backupCount=4, encoding='utf-8')
        self.logger.addHandler(self.handler)
        self.lifecycle_logger = logging.getLogger('tracker_uid.lifecycle.'+printer_id+'.'+uuid.uuid4().hex)
        self.lifecycle_logger.propagate = False
        self.lifecycle_logger.setLevel(logging.INFO)
        self.lifecycle_handler = RotatingFileHandler(store.directory / 'motion-lifecycle.jsonl', maxBytes=2_000_000,
                                                      backupCount=2, encoding='utf-8')
        self.lifecycle_logger.addHandler(self.lifecycle_handler)

    def _write(self, kind, **fields):
        import time
        record = json.dumps({'time': time.time(), 'kind': kind, **fields}, ensure_ascii=False, separators=(',', ':'))
        self.logger.info(record)
        if kind not in ('event', 'motion_summary'):
            self.lifecycle_logger.info(record)

    def _capture(self, ws, config):
        try:
            return self._capture_connected(ws, config)
        finally:
            if self.lifecycle is not None:
                self.lifecycle.disconnected(self.printer_id, 'Motion capture stopped or disconnected')

    def _capture_connected(self, ws, config):
        self._write('connecting', note='Experimental estimated accounting; uncertain jobs require review')
        requests = [
            {'id': 10, 'method': 'objects/subscribe', 'params': {'objects': {'print_stats': None, 'filament_detect': None, 'print_task_config': None, 'system_stats': None, 'filament_feed left': None, 'filament_feed right': None}, 'response_template': {'method': 'notify_tracker_status'}}}
        ]
        for i in range(4):
            requests.append({'id': i + 1, 'method': 'motion_report/dump_trapq',
                             'params': {'name': 'extruder' if i == 0 else f'extruder{i}',
                                        'response_template': {'method': f'notify_tracker_head_{i}'}}})
        for request in requests:
            ws.send(json.dumps(request).encode('utf-8'))
        pending = {1, 2, 3, 4, 10}
        last_check = 0
        summary = HeadMotionSummary()
        print_state = None
        filename = ''
        started_mid_print = True
        last_summary = 0
        spool_snapshot = None
        observed_start = None
        printer_total_mm = None
        feed = FeedEvidence()
        tags = TagEvidence()
        capture_epoch = uuid.uuid4().hex
        capture_id = None
        completion_time = None
        cancel_heads = None
        cancel_comparison = None
        cancel_total_mm = None
        cancel_search_open = False
        start_ready = False
        previous_attempt = 0
        previous_profile = getattr(self.store, '_motion_slicer_profile', None)
        start_profile_baseline = previous_profile
        task_config = {}
        initial_mapping = None
        mapping_changed = False
        observed_mappings = []
        error_job_start = None
        def observe_mapping(status):
            nonlocal mapping_changed
            update = status.get('print_task_config') if isinstance(status, dict) else None
            if update is None:
                return
            if not isinstance(update, dict):
                mapping_changed = True
                return
            task_config.update(update)
            try:
                if 'extruder_map_table' in update:
                    observed_mappings.append(validate_mapping(update['extruder_map_table']))
                if 'extruders_replenished' in update and validate_mapping(update['extruders_replenished']) != [0, 1, 2, 3]:
                    mapping_changed = True
            except MappingError:
                mapping_changed = True
        def current_profile():
            profile = getattr(self.store, '_motion_slicer_profile', None)
            if (not isinstance(profile, dict) or profile is start_profile_baseline or profile.get('filename') != filename
                    or started_mid_print or observed_start is None
                    or isinstance(profile.get('started_at'), bool)
                    or not isinstance(profile.get('started_at'), (int, float))
                    or abs(profile['started_at'] - observed_start) > 30):
                return None
            return profile
        def write_summary(note):
            heads = summary.result()
            allocation, allocation_error = [], None
            try:
                profile = current_profile()
                allocation = provisional_allocation(heads, spool_snapshot, self.store.read(), profile)
            except (ValueError, TypeError, KeyError) as exc:
                allocation_error = str(exc)
            comparison = None
            try:
                comparison = summary.compare_printer_total(printer_total_mm)
            except MotionDataError:
                pass
            self._write('motion_summary', filename=filename, heads=heads, allocation=allocation,
                        allocation_error=allocation_error, started_mid_print=started_mid_print,
                        printer_comparison=comparison, feeder_evidence=feed.report(), tag_evidence=tags.report(feed.report()),
                        provisional=True, note=note)
        def try_commit():
            profile = current_profile()
            if not start_ready or not summary.valid or profile is None:
                raise ValueError('Start, stream or verified profile unavailable')
            if mapping_changed:
                self.lifecycle.disconnected(self.printer_id, 'Automatic transition requires research; debit blocked')
                raise ValueError('Automatic transition requires research; debit blocked')
            if self.lifecycle is not None:
                report = feed.report()
                cancelled = print_state == 'cancelled'
                evidence = {'complete': True, 'continuous': True,
                            'comparison': cancel_comparison if cancelled else summary.compare_printer_total(printer_total_mm),
                            'feed': report, 'tags': tags.report(report),
                            'heads': cancel_heads if cancelled else summary.result(),
                            'profile': profile, 'start': spool_snapshot, 'epoch': capture_epoch,
                            'capture_id': capture_id,
                            'terminal_state': 'cancelled' if cancelled else 'completed'}
                result = self.lifecycle.terminal(self.printer_id, evidence)
                if result['status'] == 'review':
                    raise ValueError(result['reason'])
                return result['status'] in ('applied', 'duplicate')
        import time
        while not self.stop_event.is_set():
            now = time.monotonic()
            if completion_time is not None and now - completion_time >= 4 and now - previous_attempt >= 2:
                previous_attempt = now
                if now - completion_time > 35:
                    self._write('auto_accounting_review', reason='Complete verified evidence unavailable')
                    completion_time = None
                else:
                    try:
                        if try_commit():
                            self._write('auto_accounting_committed', filename=filename,
                                        note='Estimated usage; untagged spool identity follows user slot assignment')
                        completion_time = None
                    except (ValueError, MotionDataError, KeyError, TypeError) as exc:
                        if now - completion_time >= 30:
                            self._write('auto_accounting_review', reason=str(exc)[:200])
                            completion_time = None
            if now - last_check >= 3:
                latest = self.store.read()['printer']
                if not latest['enabled'] or (latest['host'], latest['port']) != (config['host'], config['port']):
                    self._write('stopped', reason='Monitor configuration changed')
                    return
                last_check = now
            try:
                message = ws.receive()
            except socket.timeout:
                continue
            if message is None:
                continue
            if not isinstance(message, dict):
                raise StreamError('Invalid notification')
            if message.get('id') in pending:
                if 'error' in message or 'result' not in message:
                    raise StreamError(f'Subscription {message["id"]} failed')
                pending.remove(message['id'])
                self._write('subscription', id=message['id'], result=message['result'])
                if message['id'] == 10:
                    initial_status = message['result'].get('status', {})
                    observe_mapping(initial_status)
                    feed.apply(initial_status)
                    tags.apply(initial_status)
                    stats = initial_status.get('print_stats', {})
                    print_state = stats.get('state')
                    filename = stats.get('filename', '')
                    started_mid_print = print_state in ('printing', 'paused')
                    if started_mid_print:
                        spool_snapshot = self.store.read()
                if not pending:
                    self._write('subscribed', note='Subscriptions accepted; receipt of motion is not yet verified')
            method = message.get('method', '')
            if method == 'notify_tracker_status' or method in {f'notify_tracker_head_{i}' for i in range(4)}:
                self._write('event', method=method, params=message.get('params'))
                params = message.get('params')
                if method == 'notify_tracker_status' and isinstance(params, dict):
                    status = params.get('status', {})
                    stats = status.get('print_stats', {})
                    if not isinstance(stats, dict) or stats.get('state') != 'complete':
                        observe_mapping(status)
                    feed.apply(status)
                    tags.apply(status)
                    if isinstance(stats, dict):
                        state = stats.get('state', print_state)
                        if state != print_state and 'state' in stats:
                            self._write('print_state', previous=print_state, state=state,
                                        filename=stats.get('filename') or filename)
                        if state == 'printing' and print_state not in ('printing', 'paused'):
                            profile_before_resume = current_profile()
                            same_resumed_job = (print_state == 'error' and error_job_start is not None
                                                and isinstance(profile_before_resume, dict)
                                                and profile_before_resume.get('started_at') == error_job_start
                                                and (not stats.get('filename') or stats['filename'] == filename))
                            if same_resumed_job:
                                print_state = state
                                continue
                            if print_state == 'error':
                                # Without a verified same-job identity do not
                                # treat this transition as a fresh capture.
                                started_mid_print = True
                                print_state = state
                                continue
                            summary = HeadMotionSummary()
                            started_mid_print = False
                            observed_start = time.time()
                            spool_snapshot = self.store.read()
                            printer_total_mm = None
                            feed = feed.for_new_job()
                            tags = tags.for_new_job()
                            observed_mappings.clear()
                            try:
                                initial_mapping = validate_mapping(task_config.get('extruder_map_table'))
                            except MappingError:
                                initial_mapping = None
                            try:
                                mapping_changed = ('extruders_replenished' in task_config and
                                                   validate_mapping(task_config['extruders_replenished']) != [0, 1, 2, 3])
                            except MappingError:
                                mapping_changed = True
                            capture_id = uuid.uuid4().hex
                            start_profile_baseline = previous_profile
                            start_ready = not pending and isinstance(stats.get('filename'), str) and bool(stats['filename'])
                            if self.lifecycle is not None and start_ready:
                                self.lifecycle.start(self.printer_id, filename=stats['filename'],
                                    observed_at=observed_start, capture_id=capture_id, epoch=capture_epoch,
                                    start=spool_snapshot, channels=self.channels if self.channels is not None else [str(i) for i in range(4) if spool_snapshot['slots'].get(str(i+1))])
                            completion_time = None
                            cancel_heads = None
                            cancel_comparison = None
                            cancel_total_mm = None
                            cancel_search_open = False
                            error_job_start = None
                        if 'filament_used' in stats:
                            printer_total_mm = stats['filament_used']
                        filename = stats.get('filename') or filename
                        if state == 'complete' and print_state in ('printing', 'paused') and summary.valid:
                            write_summary('Diagnostic estimate only; completion batches may arrive later; no debit')
                            completion_time = now
                            previous_profile = getattr(self.store, '_motion_slicer_profile', None)
                        elif state == 'error':
                            profile_at_error = current_profile()
                            error_job_start = profile_at_error.get('started_at') if isinstance(profile_at_error, dict) else None
                            completion_time = None
                        elif state == 'cancelled':
                            # Wait for late motion and history, just as for a
                            # completion. Only the motion path can debit a
                            # partial print; the full slicer plan cannot.
                            profile_at_cancel = current_profile()
                            same_failed_job = (print_state == 'error' and error_job_start is not None
                                               and isinstance(profile_at_cancel, dict)
                                               and profile_at_cancel.get('started_at') == error_job_start)
                            if (print_state in ('printing', 'paused') or same_failed_job) and summary.valid:
                                cancel_heads = summary.result()
                                cancel_total_mm = printer_total_mm
                                try:
                                    cancel_comparison = summary.compare_printer_total(printer_total_mm)
                                except MotionDataError:
                                    cancel_comparison = None
                                cancel_search_open = cancel_comparison is not None
                                completion_time = now
                            error_job_start = None
                        print_state = state
                elif method.startswith('notify_tracker_head_') and summary.valid:
                    try:
                        head = int(method[-1])
                        rows = params.get('data') if isinstance(params, dict) else None
                        if print_state == 'cancelled' and cancel_search_open and isinstance(rows, list):
                            # A batch may contain both queued print moves and
                            # the later cancellation retract. Search only the
                            # forward prefix against the frozen U1 counter.
                            for row in rows:
                                before = summary.heads[head]['net_mm']
                                summary.add(head, [row])
                                delta = summary.heads[head]['net_mm'] - before
                                if delta < -1e-7:
                                    cancel_search_open = False
                                if cancel_search_open:
                                    candidate = summary.compare_printer_total(cancel_total_mm)
                                    if abs(candidate['difference_mm']) < abs(cancel_comparison['difference_mm']):
                                        cancel_comparison = candidate
                                        cancel_heads = summary.result()
                        else:
                            summary.add(head, rows)
                        if now - last_summary >= 30:
                            write_summary('Diagnostic estimate only; no debit')
                            last_summary = now
                    except MotionDataError as exc:
                        self._write('motion_summary_invalid', error=str(exc))
        self._write('stopped', reason='Tracker exited')

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=7)
        self.logger.removeHandler(self.handler)
        self.handler.close()
        self.lifecycle_logger.removeHandler(self.lifecycle_handler)
        self.lifecycle_handler.close()
