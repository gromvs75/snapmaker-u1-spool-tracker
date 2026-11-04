import json
import socket
import struct
import pytest

from motion_stream import MotionStreamRecorder, StreamError, WebSocket
from storage import Store


def frame(data, opcode=1):
    if isinstance(data, str):
        data = data.encode()
    size = bytes([len(data)]) if len(data) < 126 else b'\x7e' + struct.pack('!H', len(data))
    return bytes([0x80 | opcode]) + size + data


def test_websocket_reads_partial_frames_and_control_ping():
    client, server = socket.socketpair()
    ws = WebSocket.__new__(WebSocket)
    ws.sock, ws.buffer = client, bytearray()
    try:
        message = json.dumps({'method': 'notify_tracker_head_1', 'params': {'data': [[1, 2, 3]]}})
        server.sendall(frame(message))
        assert ws.receive()['method'] == 'notify_tracker_head_1'
        server.sendall(frame(b'hi', opcode=9))
        assert ws.receive() is None
        pong = server.recv(32)
        assert pong[0] == 0x8a and pong[1] & 0x80
    finally:
        client.close()
        server.close()


def test_websocket_partial_timeout_never_reuses_frame_as_new_message():
    client, server = socket.socketpair()
    client.settimeout(.05)
    ws = WebSocket.__new__(WebSocket)
    ws.sock, ws.buffer = client, bytearray()
    ws.partial_frame_timeout = .1
    try:
        server.sendall(b'\x81\x05ab')
        with pytest.raises(StreamError, match='Incomplete'):
            ws.receive()
    finally:
        client.close()
        server.close()


@pytest.mark.parametrize('split', [1, 2, 4])
def test_websocket_preserves_delayed_frame_fragments(split):
    import threading
    import time
    client, server = socket.socketpair()
    client.settimeout(.02)
    ws = WebSocket.__new__(WebSocket)
    ws.sock, ws.buffer = client, bytearray()
    ws.partial_frame_timeout = .5
    payload = frame('{"state":"printing"}')
    def sender():
        server.sendall(payload[:split])
        time.sleep(.08)  # Several socket timeouts during one valid frame.
        server.sendall(payload[split:])
    thread = threading.Thread(target=sender)
    thread.start()
    try:
        assert ws.receive() == {'state': 'printing'}
    finally:
        thread.join(timeout=1)
        client.close()
        server.close()


def test_recorder_subscribes_four_heads_records_evidence_without_changing_balances(tmp_path):
    store = Store(tmp_path)
    original = store.read()
    recorder = MotionStreamRecorder(store)
    config = {'enabled': True, 'host': 'localhost', 'port': 7125}
    store.update(lambda db: db['printer'].update(config))
    class FakeSocket:
        def __init__(self):
            self.sent = []
            self.responses = [{'id': n, 'result': {'header': []}} for n in (10, 1, 2, 3, 4)]
            self.responses.append({'method': 'notify_tracker_head_1', 'params': {'data': [[1, 2, 3]]}})
        def send(self, payload): self.sent.append(json.loads(payload))
        def receive(self):
            if not self.responses:
                recorder.stop_event.set()
                return None
            return self.responses.pop(0)
    ws = FakeSocket()
    try:
        recorder._capture(ws, config)
        events = [json.loads(line) for line in (tmp_path / 'motion-diagnostic.jsonl').read_text().splitlines()]
        assert [r['params']['name'] for r in ws.sent[1:]] == ['extruder', 'extruder1', 'extruder2', 'extruder3']
        assert ws.sent[0]['method'] == 'objects/subscribe'
        assert all(item['method'] == 'motion_report/dump_trapq' for item in ws.sent[1:])
        assert any(item['kind'] == 'subscribed' for item in events)
        assert any(item.get('method') == 'notify_tracker_head_1' for item in events)
        assert store.read()['spools'] == original['spools']
    finally:
        recorder.stop()


def test_subscription_failure_is_not_reported_as_ready(tmp_path):
    store = Store(tmp_path)
    config = {'enabled': True, 'host': 'localhost', 'port': 7125}
    store.update(lambda db: db['printer'].update(config))
    recorder = MotionStreamRecorder(store)
    class FakeSocket:
        def send(self, payload): pass
        def receive(self): return {'id': 3, 'error': {'message': 'unavailable'}}
    try:
        with pytest.raises(StreamError, match='Subscription 3'):
            recorder._capture(FakeSocket(), config)
        assert '"kind":"subscribed"' not in (tmp_path / 'motion-diagnostic.jsonl').read_text()
    finally:
        recorder.stop()


def test_bridge_protocol_end_to_end_records_independent_head_batches(tmp_path):
    import base64
    import hashlib
    import threading
    import time
    from motion_stream import GUID

    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    errors = []
    def server():
        try:
            conn, _ = listener.accept()
            conn.settimeout(5)
            request = b''
            while b'\r\n\r\n' not in request: request += conn.recv(4096)
            assert request.startswith(b'GET /klippysocket HTTP/1.1\r\n')
            key = next(x.split(b':', 1)[1].strip() for x in request.split(b'\r\n') if x.lower().startswith(b'sec-websocket-key:'))
            accept = base64.b64encode(hashlib.sha1(key + GUID).digest())
            conn.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + b'\r\n\r\n')
            def take(n):
                data = b''
                while len(data) < n:
                    chunk = conn.recv(n - len(data))
                    if not chunk: raise EOFError()
                    data += chunk
                return data
            for _ in range(5):
                header = take(2); n = header[1] & 127
                if n == 126: n = struct.unpack('!H', take(2))[0]
                elif n == 127: n = struct.unpack('!Q', take(8))[0]
                mask = take(4); raw = take(n)
                req = json.loads(bytes(c ^ mask[i % 4] for i, c in enumerate(raw)))
                conn.sendall(frame(json.dumps({'id': req['id'], 'result': {'header': []}})))
            for head in (1, 3):
                sample = {'method': f'notify_tracker_head_{head}', 'params': {'data': [[1.0, .1, 10.0, 0.0, [0, 0, 0], [1, 0, 0]]]}}
                conn.sendall(frame(json.dumps(sample)))
            time.sleep(.3)
            conn.close()
        except BaseException as exc:
            errors.append(exc)
        finally:
            listener.close()
    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    store = Store(tmp_path)
    config = {'enabled': True, 'host': '127.0.0.1', 'port': port}
    store.update(lambda db: db['printer'].update(config))
    recorder = MotionStreamRecorder(store)
    ws = WebSocket('127.0.0.1', port)
    try:
        with pytest.raises(StreamError, match='disconnected|closed'):
            recorder._capture(ws, config)
    finally:
        ws.close()
        recorder.stop()
        thread.join(5)
    assert not errors
    records = [json.loads(line) for line in (tmp_path / 'motion-diagnostic.jsonl').read_text().splitlines()]
    assert [r['method'] for r in records if r['kind'] == 'event'] == ['notify_tracker_head_1', 'notify_tracker_head_3']


def test_summary_is_provisional_and_never_books_spools(tmp_path):
    store = Store(tmp_path)
    config = {'enabled': True, 'host': 'localhost', 'port': 7125}
    store.update(lambda db: db['printer'].update(config))
    original = store.read()['spools']
    recorder = MotionStreamRecorder(store)
    class FakeSocket:
        def __init__(self):
            self.responses = [
                {'id': 10, 'result': {'status': {'print_stats': {'state': 'standby', 'filename': ''}}}},
                *[{'id': n, 'result': {'header': []}} for n in (1, 2, 3, 4)],
                {'method': 'notify_tracker_status', 'params': {'status': {'print_stats': {'state': 'printing', 'filename': 'part.gcode'}}}},
                {'method': 'notify_tracker_head_0', 'params': {'data': [[1, 1, 10, 0, [0, 0, 0], [1, 0, 0]]]}},
                {'method': 'notify_tracker_head_2', 'params': {'data': [[2, 1, 4, 0, [0, 0, 0], [1, 0, 0]]]}},
                {'method': 'notify_tracker_status', 'params': {'status': {'print_stats': {'state': 'complete', 'filename': ''}}}},
            ]
        def send(self, payload): pass
        def receive(self):
            if not self.responses:
                recorder.stop_event.set()
                return None
            return self.responses.pop(0)
    try:
        recorder._capture(FakeSocket(), config)
        rows = [json.loads(line) for line in (tmp_path / 'motion-diagnostic.jsonl').read_text().splitlines()]
        final = [row for row in rows if row['kind'] == 'motion_summary'][-1]
        assert final['filename'] == 'part.gcode' and final['provisional'] is True
        assert final['heads'][0]['net_mm'] == 10 and final['heads'][2]['net_mm'] == 4
        assert final['started_mid_print'] is False
        assert store.read()['spools'] == original
    finally:
        recorder.stop()


def test_stream_summary_matches_slicer_parameters_to_two_slots(tmp_path):
    import time
    store = Store(tmp_path)
    config = {'enabled': True, 'host': 'localhost', 'port': 7125}
    def seed(db):
        db['printer'].update(config)
        db['spools']['first'] = {'name': 'black', 'material': 'PLA', 'remaining_g': 1000}
        db['spools']['second'] = {'name': 'white', 'material': 'PLA', 'remaining_g': 1000}
        db['slots']['1'], db['slots']['2'] = 'first', 'second'
    store.update(seed)
    profile = {'filename': 'part.gcode', 'started_at': time.time(),
        'mapping': [0, 1, 2, 3], 'logical_weights': [1, 2, 0, 0],
        'filament_type': 'PLA;PLA;PLA;PLA',
        'parameters': [{'diameter_mm': 1.75, 'density_g_cm3': 1.24} for _ in range(4)]}
    recorder = MotionStreamRecorder(store)
    class FakeSocket:
        def __init__(self):
            self.responses = [
                {'id': 10, 'result': {'status': {'print_stats': {'state': 'standby', 'filename': ''}}}},
                *[{'id': n, 'result': {'header': []}} for n in (1, 2, 3, 4)],
                {'method': 'notify_tracker_status', 'params': {'status': {'print_stats': {'state': 'printing', 'filename': 'part.gcode'}}}},
                {'method': 'notify_tracker_head_0', 'params': {'data': [[1, 1, 100, 0, [0, 0, 0], [1, 0, 0]]]}},
                {'method': 'notify_tracker_head_1', 'params': {'data': [[2, 1, 200, 0, [0, 0, 0], [1, 0, 0]]]}},
                {'method': 'notify_tracker_status', 'params': {'status': {'print_stats': {'state': 'complete'}}}},
            ]
        def send(self, payload): pass
        def receive(self):
            if not self.responses:
                recorder.stop_event.set()
                return None
            item = self.responses.pop(0)
            if item.get('method') == 'notify_tracker_head_0': store._motion_slicer_profile = profile
            return item
    try:
        recorder._capture(FakeSocket(), config)
        rows = [json.loads(line) for line in (tmp_path / 'motion-diagnostic.jsonl').read_text().splitlines()]
        final = [x for x in rows if x['kind'] == 'motion_summary'][-1]
        assert [(a['spool_id'], a['estimated_g']) for a in final['allocation']] == [('first', .298), ('second', .597)]
        assert final['provisional'] and all(not a['identity_verified'] for a in final['allocation'])
        assert store.read()['spools']['first']['remaining_g'] == 1000
    finally:
        recorder.stop()
