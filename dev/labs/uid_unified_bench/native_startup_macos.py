"""Inspect an explicitly supplied macOS bundle using fresh, disposable profiles.

Capture only child-PID windows, not the desktop. No printer/Spoolman connections
are started. A dark screenshot is evidence of rendering, not a diagnosis of a
previous intermittent failure. Keep profiles/logs for investigation.
"""
import argparse
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen


def wait(check, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(.05)
    raise TimeoutError('Native startup condition was not reached')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=2)
    args = parser.parse_args()
    if sys.platform != 'darwin' or not 1 <= args.repeats <= 20:
        parser.error('Requires macOS; repeats must be between 1 and 20')
    import AppKit
    import Quartz
    from PIL import Image

    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'src'))
    from dev.observer_fixture import payload
    from tracker_uid_session import Session
    bundle = args.bundle.resolve()
    info = plistlib.loads((bundle / 'Contents/Info.plist').read_bytes())
    executable = bundle / 'Contents/MacOS' / info['CFBundleExecutable']
    args.output.mkdir(parents=True, exist_ok=True)
    report = dict(bundle=str(bundle), version=info['CFBundleShortVersionString'],
                  commit=info.get('TrackerSourceCommit'), cases=[])
    for repeat in range(args.repeats):
        for scenario in ('empty', 'slice', 'early-hide-show'):
            case = dict(repeat=repeat, scenario=scenario)
            report['cases'].append(case)
            directory = Path(tempfile.mkdtemp(prefix='tracker-native-startup-'))
            profile = directory / 'profile'
            case['profile'] = str(profile)
            if scenario == 'slice':
                # A selected printer is needed for a tray forecast event.
                # Save a dummy endpoint but never connect to it.
                session = Session(profile)
                try:
                    session.call('save_settings', values={'printers': [dict(
                        id='fixture', name='Startup fixture', url='http://127.0.0.1:9')],
                        'selected_printer': 'fixture'},
                        expected_revision=session.call('settings')['revision'])
                finally:
                    session.close()
                folder = profile / 'slices/Preview/Metadata'
                folder.mkdir(parents=True)
                (folder / '.42.0.gcode').write_bytes(payload('0, 0, 0, 54.7'))
            with (directory / 'stdio.log').open('w') as stream:
                child = subprocess.Popen([str(executable)],
                    env=dict(os.environ, TRACKER20_DATA_DIR=str(profile)),
                    stdout=stream, stderr=subprocess.STDOUT)
                case['pid'] = child.pid
                try:
                    descriptor = profile / 'instance.json'
                    def started():
                        if child.poll() is not None:
                            raise RuntimeError('Candidate exited during startup')
                        return descriptor.exists()
                    wait(started)
                    ipc = json.loads(descriptor.read_text())
                    def api(path, body=None):
                        req = Request(f"http://127.0.0.1:{ipc['port']}/api/{path}",
                            data=None if body is None else json.dumps(body).encode(),
                            headers={'X-Tracker-Token': ipc['token'], 'Content-Type': 'application/json'})
                        with urlopen(req, timeout=10) as response:
                            return json.load(response)
                    if scenario == 'early-hide-show':
                        api('window', dict(action='hide'))
                        time.sleep(2)
                        api('window', dict(action='show'))
                    log = profile / 'logs/tracker.log'
                    wait(lambda: log.exists() and 'Native DOM probe result=' in log.read_text())
                    time.sleep(2)
                    app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(child.pid)
                    assert app and str(app.bundleURL().path()) == str(bundle), 'Unexpected process identity'
                    case['activation_policy'] = int(app.activationPolicy())
                    assert case['activation_policy'] == 1, 'Candidate gained a Dock tile'
                    state = api('state')
                    assert not state['connections']['connected'], 'Unexpected connections'
                    assert not state['debits'], 'Unexpected accounting'
                    windows = [w for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionAll, 0)
                        if w.get('kCGWindowOwnerPID') == child.pid and w.get('kCGWindowLayer') == 0]
                    window = max(windows, key=lambda w: w['kCGWindowBounds']['Width'] * w['kCGWindowBounds']['Height'])
                    case['bounds'] = dict(window['kCGWindowBounds'])
                    case['onscreen'] = bool(window.get('kCGWindowIsOnscreen'))
                    assert case['onscreen'], 'Window did not return onscreen'
                    image = args.output / f'{repeat}-{scenario}.png'
                    subprocess.run(['screencapture', '-x', '-o', '-l', str(window['kCGWindowNumber']), str(image)], check=True)
                    with Image.open(image) as captured:
                        pixels = list(captured.convert('RGB').crop((80, 100, captured.width-80, captured.height-80)).resize((100, 100)).getdata())
                    case['white_fraction'] = sum(min(p) > 235 for p in pixels) / len(pixels)
                    case['dark_fraction'] = sum(max(p) < 100 for p in pixels) / len(pixels)
                    assert case['dark_fraction'] > .5 and case['white_fraction'] < .5, 'Blank/unexpected native surface; inspect screenshot and logs'
                    case['rendered'] = True
                finally:
                    if child.poll() is None:
                        child.send_signal(signal.SIGTERM)
                        try:
                            child.wait(20)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait()
                    case['exit_code'] = child.returncode
                    case['ipc_removed'] = not (profile / 'instance.json').exists()
                    (args.output / 'results.json').write_text(json.dumps(report, indent=2))
                assert case['exit_code'] == 0 and case['ipc_removed'], 'Unclean shutdown'
                print(f'PASS {repeat} {scenario}: rendered, disconnected, no Dock, clean exit', flush=True)


if __name__ == '__main__':
    main()
