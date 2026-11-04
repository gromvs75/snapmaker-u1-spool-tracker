"""Experimental U1 stream accounting with conservative review fallback.

Amounts are estimates; untagged spool identity follows the user's assignment.
Klipper provides no sequence numbers, so matching the aggregate counter is a
consistency check, not proof of measured physical consumption or spool identity.
"""
import base64
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import socket
import struct
import threading
import time
import uuid
from motion_analysis import HeadMotionSummary, MotionDataError
from motion_allocation import provisional_allocation
from feed_evidence import FeedEvidence
from tag_evidence import TagEvidence
from tool_mapping import validate_mapping, MappingError

MAX_FRAME = 2_000_000
GUID = b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'


class StreamError(Exception):
    pass


class WebSocket:
    """Minimal bounded RFC 6455 client for Moonraker's Klipper bridge."""
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=5)
        self.buffer = bytearray()
        try:
            key = base64.b64encode(os.urandom(16)).decode('ascii')
            request = (f'GET /klippysocket HTTP/1.1\r\nHost: {host}:{port}\r\n'
                       f'Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n'
                       'Sec-WebSocket-Version: 13\r\n\r\n')
            self.sock.sendall(request.encode('ascii'))
            while b'\r\n\r\n' not in self.buffer:
                self._read_more()
                if len(self.buffer) > 16384:
                    raise StreamError('WebSocket handshake too large')
            end = self.buffer.index(b'\r\n\r\n') + 4
            header = bytes(self.buffer[:end]).decode('iso-8859-1')
            del self.buffer[:end]
            lines = header.split('\r\n')
            headers = {}
            for line in lines[1:]:
                if ':' in line:
                    k, v = line.split(':', 1)
                    headers[k.strip().lower()] = v.strip()
            expected = base64.b64encode(hashlib.sha1(key.encode('ascii') + GUID).digest()).decode('ascii')
            if not lines[0].startswith('HTTP/1.1 101 ') or headers.get('sec-websocket-accept') != expected:
                raise StreamError('WebSocket handshake rejected')
            self.sock.settimeout(1)
        except Exception:
            self.sock.close()
            raise

    def _read_more(self):
        data = self.sock.recv(65536)
        if not data:
            raise StreamError('WebSocket disconnected')
        self.buffer.extend(data)

    def _take(self, count, frame_started=False):
        # A socket timeout between TCP fragments is not a broken frame.
        # Once a frame begins, retain its bytes while waiting, but cap the
        # total wait so a stalled peer cannot block the recorder forever.
        deadline = None
        while len(self.buffer) < count:
            if (frame_started or self.buffer) and deadline is None:
                deadline = time.monotonic() + getattr(self, 'partial_frame_timeout', 10.0)
            try:
                self._read_more()
            except socket.timeout:
                if deadline is None and not self.buffer and not frame_started:
                    raise
                if deadline is None:
                    deadline = time.monotonic() + getattr(self, 'partial_frame_timeout', 10.0)
                if time.monotonic() >= deadline:
                    raise StreamError('Incomplete WebSocket frame')
        data = bytes(self.buffer[:count])
        del self.buffer[:count]
        return data

    def send(self, data, opcode=1):
        if len(data) > MAX_FRAME:
            raise StreamError('WebSocket message too large')
        mask = os.urandom(4)
        n = len(data)
        size = bytes([0x80 | n]) if n < 126 else (b'\xfe' + struct.pack('!H', n) if n <= 65535 else b'\xff' + struct.pack('!Q', n))
        self.sock.sendall(bytes([0x80 | opcode]) + size + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))

    def receive(self):
        try:
            first = self._take(2)
        except socket.timeout:
            if self.buffer:
                raise StreamError('Incomplete WebSocket frame')
            raise
        try:
            return self._receive_frame(first)
        except socket.timeout as exc:
            raise StreamError('Incomplete WebSocket frame') from exc

    def _receive_frame(self, first):
        fin, opcode, masked, length = first[0] & 0x80, first[0] & 15, first[1] & 0x80, first[1] & 127
        if first[0] & 0x70 or masked or not fin:
            raise StreamError('Unsupported WebSocket frame')
        if length == 126:
            length = struct.unpack('!H', self._take(2, frame_started=True))[0]
        elif length == 127:
            length = struct.unpack('!Q', self._take(8, frame_started=True))[0]
        if length > MAX_FRAME:
            raise StreamError('WebSocket frame too large')
        data = self._take(length, frame_started=True)
        if opcode == 8:
            raise StreamError('WebSocket closed')
        if opcode == 9:
            self.send(data, 10)
            return None
        if opcode == 10:
            return None
        if opcode != 1:
            raise StreamError('Unsupported WebSocket message')
        return json.loads(data.decode('utf-8'))

    def close(self):
        self.sock.close()


class MotionStreamRecorder:
    def __init__(self, store):
        self.store = store
        self.stop_event = threading.Event()
        self.thread = None
        self.logger = logging.getLogger('snapmaker_tracker.motion_diagnostic')
        self.logger.propagate = False
        self.logger.setLevel(logging.INFO)
        store.directory.mkdir(parents=True, exist_ok=True)
        self.handler = RotatingFileHandler(store.directory / 'motion-diagnostic.jsonl', maxBytes=32_000_000,
                                           backupCount=4, encoding='utf-8')
        self.logger.addHandler(self.handler)
        self.lifecycle_logger = logging.getLogger('snapmaker_tracker.motion_lifecycle')
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

    def start(self):
        self.thread = threading.Thread(target=self._run, name='motion-diagnostic', daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                config = self.store.read()['printer']
                if not config['enabled']:
                    self.stop_event.wait(3)
                    continue
                ws = WebSocket(config['host'], config['port'])
                try:
                    self._capture(ws, config)
                finally:
                    ws.close()
            except Exception as exc:
                self._write('disconnected', error=str(exc)[:200])
                self.stop_event.wait(5)

    def _capture(self, ws, config):
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
            from accounting import commit_stream_estimate, commit_unchanged_slicer_estimate
            profile = current_profile()
            if not start_ready or not summary.valid or profile is None:
                raise ValueError('Start, stream or verified profile unavailable')
            snapshot = self.store.read()
            matches = [(key, run) for key, run in snapshot['runs'].items()
                       if run.get('filename') == filename and abs(run.get('start_time', 0) - profile['started_at']) < .01
                       and run.get('status') in ('review', 'cancelled')
                       and run.get('terminal_status') in ('completed', 'cancelled')]
            if len(matches) != 1:
                raise ValueError('Unique completed printer job is not yet available')
            report = feed.report()
            try:
                expected_mapping = validate_mapping(profile.get('mapping'))
                stable_mapping = (not mapping_changed
                                  and validate_mapping(profile.get('replenished')) == [0, 1, 2, 3]
                                  and all(m == expected_mapping for m in observed_mappings)
                                  and (initial_mapping is None or initial_mapping == expected_mapping))
            except MappingError:
                stable_mapping = False
            slicer_evidence = {'complete': True, 'continuous': True, 'feed': report,
                               'tags': tags.report(report), 'profile': profile,
                               'start': spool_snapshot, 'mapping_unchanged': stable_mapping}
            try:
                return commit_unchanged_slicer_estimate(self.store, matches[0][0], slicer_evidence)
            except ValueError:
                pass  # A real replacement still needs the separate motion checks.
            cancelled_job = matches[0][1].get('terminal_status') == 'cancelled'
            # The printer can retract after it has reported cancellation,
            # while print_stats.filament_used remains frozen. Compare and
            # allocate the same observed boundary, never mix the two times.
            comparison = cancel_comparison if cancelled_job else summary.compare_printer_total(printer_total_mm)
            accounting_heads = cancel_heads if cancelled_job else summary.result()
            if not isinstance(comparison, dict) or not isinstance(accounting_heads, list):
                raise ValueError('Cancellation boundary unavailable')
            if not comparison['matches']:
                raise ValueError('Motion total differs from U1')
            evidence = {'complete': True, 'continuous': True, 'comparison': comparison,
                        'feed': report, 'tags': tags.report(report), 'heads': accounting_heads,
                        'profile': profile, 'start': spool_snapshot, 'epoch': capture_epoch,
                        'capture_id': capture_id}
            return commit_stream_estimate(self.store, matches[0][0], evidence)
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
                            if print_state in ('printing', 'paused') and summary.valid:
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
