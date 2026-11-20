"""Exercise a packaged Tracker with recorded status from the real 0.8.1 bench.

This is a transport replay, not a Klippy process running alongside the EXE.
The paired tag and module data are kept. The sequence and age are refreshed
for each replayed event. Printer events and the Spoolman server are synthetic.
"""

import argparse
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'src'), str(ROOT / 'tests')]
from dev.labs.uid_candidate_bench.run import native_windows, wait
from test_rfid_bambu import Server
from tracker_uid_client import validate_status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('exe', 'capture', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--exe-sha256', required=True)
    args = parser.parse_args()
    exe = args.exe.resolve(strict=True)
    exe_hash = hashlib.sha256(exe.read_bytes()).hexdigest()
    assert exe_hash == args.exe_sha256
    raw_capture = args.capture.read_bytes()
    capture = json.loads(raw_capture)
    statuses = capture['statuses']
    initial = validate_status(statuses['initial'])
    assert initial['module_version'] == '0.8.1-read-budget-bench'
    sides = [name for name in statuses if name != 'initial']
    assert len(sides) == 2
    tags = [validate_status(statuses[uid])['channels']['0']['tag'] for uid in sides]
    assert [tag['uid'] for tag in tags] == sides
    assert tags[0]['identity'] == tags[1]['identity'] and tags[0]['format'] == tags[1]['format'] == 'bambu'
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    spoolman = Server()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def call(self):
            size = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(size)) if size else None
            value, _ = spoolman.request(self.command, self.path.removeprefix('/api/v1'), body)
            raw = json.dumps(value).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        do_GET = do_POST = do_PUT = call

    # WebView2 can briefly retain cache locks after its parent exits on Windows.
    with tempfile.TemporaryDirectory(prefix='tracker-rfid-wire-', ignore_cleanup_errors=sys.platform=='win32') as temporary, (out/'process.log').open('w') as log:
        folder = Path(temporary).resolve()
        profile, wire = folder/'profile', folder/'reader.json'
        descriptor, sequence = {}, 0
        app = simulator = None
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        printer = f'http://127.0.0.1:{port}'
        remote = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=remote.serve_forever)
        thread.start()
        remote_url = f'http://127.0.0.1:{remote.server_port}'

        def request(url, body=None, headers=None):
            req = Request(url, None if body is None else json.dumps(body).encode(),
                          headers or {'Content-Type': 'application/json'})
            with urlopen(req, timeout=15) as response:
                return json.load(response)

        def api(path, body=None):
            return request(f'http://127.0.0.1:{descriptor["port"]}/api/{path}', body,
                           {'Content-Type': 'application/json', 'X-Tracker-Token': descriptor['token']})

        def state():
            return api('state')

        def publish(uid=None):
            nonlocal sequence
            sequence += 1
            status = copy.deepcopy(statuses[uid] if uid else initial)
            status['sequence'] = sequence
            for channel in status['channels'].values():
                if channel['state'] == 'present':
                    channel.update(sequence=sequence, age_seconds=0)
            if not uid:
                status['channels']['0'] = dict(state='absent', uid=None, sequence=sequence, age_seconds=0, uid_length=0)
            temporary_wire = wire.with_suffix('.pending')
            temporary_wire.write_text(json.dumps(status))
            wait(lambda: replace(temporary_wire, wire), timeout=4)

        def replace(source, target):
            source.replace(target)
            return True

        def select(uid, spool_id=None):
            publish()
            wait(lambda: not any(row.get('uid') for row in state()['occupied']))
            publish(uid)

            def matched_snapshot():
                snapshot = state()
                if any(row.get('uid') == uid and
                       (spool_id is None or (row.get('spool') or {}).get('spool_id') == spool_id)
                       for row in snapshot['occupied']):
                    return snapshot

            return wait(matched_snapshot)

        def launch():
            nonlocal app, descriptor
            old = descriptor.get('token')
            app = subprocess.Popen([str(exe)], env=dict(os.environ, TRACKER20_DATA_DIR=str(profile)),
                                   stdout=log, stderr=log)

            def ready():
                nonlocal descriptor
                if app.poll() is not None:
                    raise RuntimeError('Packaged Tracker exited during startup')
                descriptor = json.loads((profile/'instance.json').read_text())
                return descriptor['token'] != old and state()

            wait(ready)

        def stop():
            if sys.platform == 'win32':
                native_windows(app, out)
            else:
                api('connections_stop', dict(confirmed=True))
                app.terminate()
                assert app.wait(30) == 0
            assert not (profile/'instance.json').exists()

        try:
            publish()
            simulator = subprocess.Popen([sys.executable, str(Path(__file__).with_name('simulator.py')), str(port),
                '--reader-status-file', str(wire)], stdout=log, stderr=log)
            wait(lambda: request(printer+'/ready'))
            launch()
            api('settings', dict(values=dict(language='ru',
                 printers=[dict(id='a', name='RFID wire replay', url=printer)], selected_printer='a',
                 spoolman_url=remote_url, spoolman_mode='send', rfid=dict(send_usage=True)),
                 expected_revision=state()['settings']['revision']))
            api('connections_start', dict(confirmed=True))
            select(sides[0])
            review = api('rfid_preview', dict(printer_id='a', channel='0', uid=sides[0]))
            registered = api('rfid_confirm', dict(review_id=review['review_id'], action='new', confirmed=True,
                values=dict(remaining_g=840.123, density=1.24, diameter=1.75, nominal=1000)))
            sid = registered['spool_id']
            assert len(spoolman.rows['spool']) == 1
            wait(lambda: request(printer+'/ready')['result']['motion_clients'] > 0)
            request(printer+'/event', dict(action='start', filename='archive-rfid-replay.gcode'))
            wait(lambda: len(state()['recovery_plans']) == 1)
            time.sleep(1)
            request(printer+'/event', dict(action='motion', stamp=1, length=18.42/(math.pi*(1.75/2)**2*1.24/1000)))
            request(printer+'/event', dict(action='complete'))
            wait(lambda: len(state()['delivery']) == 1 and state()['delivery'][0]['state'] == 'sent')
            request(printer+'/event', dict(action='complete'))
            second_side = select(sides[1], sid)
            assert len(second_side['debits']) == 1 and second_side['debits'][0]['delta_mg'] == 18420
            assert second_side['spools'][0]['remaining_mg'] == 821703
            assert len(spoolman.puts) == 1 and round(spoolman.rows['spool'][0]['remaining_weight'], 3) == 821.703
            print('PASS paired Bambu sides, a single debit and one remote write', flush=True)
            stop()
            launch()
            api('connections_start', dict(confirmed=True))
            restarted = select(sides[0], sid)
            assert len(restarted['spools']) == len(restarted['debits']) == len(spoolman.puts) == 1
            assert restarted['spools'][0]['remaining_mg'] == 821703
            print('PASS restart preserved the spool, debit and remaining balance', flush=True)
            stop()
            report = dict(success=True, exe_sha256=exe_hash, capture_sha256=hashlib.sha256(raw_capture).hexdigest(),
                          archive_sha256=capture['archive_sha256'], module_sha256=capture['module_sha256'],
                          platform=sys.platform, native_windows_tray_checked=sys.platform=='win32',
                          scope='recorded Klippy output; synthetic print and Spoolman; no live Klippy in replay',
                          sides=2, debits=1, remote_writes=1, remaining_mg=821703, real_printer_used=False)
            (out/'results.json').write_text(json.dumps(report, indent=2))
            print(json.dumps(report, indent=2))
        finally:
            if app and app.poll() is None:
                app.terminate()
                app.wait(20)
            if simulator:
                simulator.terminate()
                simulator.wait(15)
            remote.shutdown()
            remote.server_close()
            thread.join()
            tracker_log = profile/'logs/tracker.log'
            if tracker_log.exists():
                shutil.copyfile(tracker_log, out/'tracker.log')


if __name__ == '__main__':
    main()
