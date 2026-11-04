"""Standalone packaged sender lab. Never launches the installed Tracker."""
import argparse
import base64
import json
from pathlib import Path
import sys
import tempfile
import threading
from urllib.parse import urlsplit


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Dispatch before importing Cocoa or constructing any Store/server.
    if argv[:1] == ['--presend-worker']:
        from presend import main as check_main
        return check_main(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    from sender_lab_session import LabSession, SCENARIOS, default_directory
    parser.add_argument('--scenario', choices=SCENARIOS, help='Scenario for a new lab only')
    parser.add_argument('--resume', type=Path, help='Resume a previous temporary lab; never resets its ledger')
    parser.add_argument('--test-fixture', action='store_true', help='Preselect the synthetic G-code for fault tests')
    parser.add_argument('--temporary-lab', action='store_true', help='Explicit disposable fault-test lab; leaves the ordinary session alone')
    args = parser.parse_args(argv)
    from dev.sender_dashboard_demo import Demo
    import webview
    from webview.menu import Menu, MenuAction
    from sender_test_backup import LabBackupBridge
    from backup import create_backup
    if args.resume and args.temporary_lab:
        parser.error('--resume and --temporary-lab are mutually exclusive')
    root = (Path(tempfile.mkdtemp(prefix='tracker-native-lab-')) if args.temporary_lab else default_directory())
    if args.resume:
        root = args.resume.resolve()
        if root.parent != Path(tempfile.gettempdir()).resolve() or not root.name.startswith('tracker-native-lab-'):
            parser.error('Only a temporary sender lab can be resumed')
    with LabSession(root, args.scenario) as session:
        return run_lab(args, session, webview, Demo, Menu, MenuAction, LabBackupBridge, create_backup)


def run_lab(args, session, webview, Demo, Menu, MenuAction, LabBackupBridge, create_backup):
    root = session.root
    args.scenario = session.scenario
    previous = session.previous
    fault = '' if args.scenario in ('success', 'shortage') else args.scenario
    with Demo(root, fault=fault, timeout=3, **session.ports) as demo:
        demo.mock.response_delay = 8
        if args.scenario == 'shortage' and not session.resumed:
            demo.store.update(lambda db: db['spools']['s0'].update(remaining_g=1))
        initial_inventory = demo.store.path.read_bytes()
        session.save_marker(urlsplit(demo.mock.http_url).port, urlsplit(demo.mock.ws_url).port)
        if not session.resumed:
            backup = create_backup(demo.store, '1.2-alpha-lab')
            backup['data']['spools']['s0']['name'] = 'Импорт из тестовой копии'
            backup['data']['spools']['s0']['remaining_g'] = 77
            (root / 'test-backup.json').write_text(json.dumps(backup, ensure_ascii=False), encoding='utf-8')
            if args.test_fixture:
                demo.controller.select({'filename':demo.fixture.name,
                    'content':base64.b64encode(demo.fixture.read_bytes()).decode()})
        stop = threading.Event()
        def report():
            value = {'scenario': args.scenario, 'url': demo.url, 'fixture': str(demo.fixture),
                     'directory': str(root), 'status': demo.controller.status(),
                     'uploads': previous.get('uploads', 0) + len(demo.mock.uploads),
                     'start_requests': previous.get('start_requests', 0) + len(demo.mock.start_requests),
                     'accepted_starts': previous.get('accepted_starts', 0) + len(demo.mock.accepted_starts),
                     'resumed': session.resumed,
                     'inventory_unchanged': demo.store.path.read_bytes() == initial_inventory}
            temporary = root / 'report.tmp'
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(root / 'report.json')
        def watch():
            while not stop.wait(.2):
                report()
        report()
        thread = threading.Thread(target=watch, daemon=True)
        thread.start()
        print(json.dumps({'directory':str(root), 'fixture':str(demo.fixture), 'url':demo.url}), flush=True)
        bridge = LabBackupBridge(demo, webview)
        window = webview.create_window('Tracker Sender Lab 1.2-alpha · ' + args.scenario,
                              demo.url, js_api=bridge, width=1100, height=850, min_size=(760, 560))
        bridge.window = window
        try:
            webview.start(private_mode=True, storage_path=str(root / 'webview'),
                          menu=[Menu('Стенд', [MenuAction('Перезагрузить окно', lambda: window.load_url(demo.url))])])
        finally:
            stop.set()
            thread.join(timeout=2)
            report()
    return 0


if __name__ == '__main__':
    sys.exit(main())
