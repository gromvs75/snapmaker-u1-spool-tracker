"""Persistent, single-instance lab state, separate from all Tracker preferences."""
import json
import os
from pathlib import Path
import sys
import tempfile

from filelock import FileLock

SCENARIOS = ('success', 'shortage', 'start_timeout', 'rpc_error', 'upload_reject')


def default_directory():
    if getattr(sys, 'frozen', False):
        bundle = Path(sys.executable).resolve().parents[2]
        return bundle.with_suffix('.data')
    return Path(__file__).resolve().parent / 'output' / 'sender-lab' / 'TrackerSenderLab-1.2-alpha.data'


class LabSession:
    def __init__(self, root, scenario=None):
        self.root = Path(root).resolve()
        self.requested_scenario = scenario
        self.resumed = False
        self.previous = {}
        self.ports = {}

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.root / 'application.lock'), timeout=0)
        self.lock.acquire()
        try:
            marker = self.root / 'session.json'
            if marker.exists():
                session = json.loads(marker.read_text())
                if session.get('format') != 'TrackerSenderLab-1' or session.get('scenario') not in SCENARIOS:
                    raise ValueError('Invalid saved lab session; refusing to reset it')
                self.scenario = session['scenario']
                if self.requested_scenario and self.requested_scenario != self.scenario:
                    raise ValueError('Saved scenario differs; refusing to replace the current job')
                for key in ('http_port', 'ws_port'):
                    port = session.get(key)
                    if type(port) is not int or not 0 < port < 65536:
                        raise ValueError('Invalid saved loopback port')
                    self.ports[key] = port
                for name in ('inventory/spools_u1.json', 'sender/draft.json', 'sender/sender.sqlite', 'report.json'):
                    if not (self.root / name).is_file():
                        raise ValueError('Incomplete saved lab; refusing to create a new job: ' + name)
                self.previous = json.loads((self.root / 'report.json').read_text())
                for key in ('uploads', 'start_requests', 'accepted_starts'):
                    if type(self.previous.get(key)) is not int or self.previous[key] < 0:
                        raise ValueError('Invalid saved lab counters')
                self.resumed = True
            else:
                if any(p.name != 'application.lock' for p in self.root.iterdir()):
                    raise ValueError('Lab marker missing; refusing to overwrite existing data')
                self.scenario = self.requested_scenario or 'success'
            return self
        except BaseException:
            self.lock.release()
            raise

    def save_marker(self, http_port, ws_port):
        data = {'format':'TrackerSenderLab-1', 'scenario':self.scenario,
                'http_port':http_port, 'ws_port':ws_port}
        fd, name = tempfile.mkstemp(prefix='session-', suffix='.tmp', dir=self.root)
        try:
            with os.fdopen(fd, 'w') as file:
                json.dump(data, file)
                file.flush()
                os.fsync(file.fileno())
            os.replace(name, self.root / 'session.json')
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def __exit__(self, *args):
        self.lock.release()
