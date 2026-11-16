"""User candidate entrypoint. Separate persistent data; explicit connections only."""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import sys
import threading

VERSION = '2.0.0rc1'


def data_directory():
    override = os.environ.get('TRACKER20_DATA_DIR')
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    elif sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local')))
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local' / 'share')))
    return base / 'Snapmaker Tracker 2.0'


def build_info():
    path = Path(__file__).with_name('tracker_build.json')
    info = json.loads(path.read_text()) if path.exists() else {'commit':'development','built_at':None}
    return dict(info, version=VERSION, mode='user', isolation='Пользовательский кандидат. Подключения запускаются только по вашей команде.')


def main(argv=None):
    # Never silently ignore --data/--allow-url intended for the lab launcher.
    if (sys.argv[1:] if argv is None else argv):
        return 2
    from tracker_uid_session import Session
    from tracker_uid_catalog import CatalogBusyError
    from tracker_uid_collectors import create_workers, ReadOnlyMoonraker
    from tracker_uid_sender import Sender
    from tracker_uid_gui import serve
    from tracker_uid_window import UidWindow
    directory = data_directory()
    try:
        session = Session(directory, worker_factory=create_workers)
    except CatalogBusyError:
        # Expected rejection must not open a PyInstaller exception dialog.
        return 2
    directory.joinpath('logs').mkdir(exist_ok=True)
    handler = RotatingFileHandler(directory/'logs'/'tracker.log', maxBytes=2_000_000, backupCount=5, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(threadName)s %(message)s'))
    logger = logging.getLogger('tracker20'); logger.setLevel(logging.INFO); logger.addHandler(handler)
    info = build_info()
    logger.info('START version=%s commit=%s data=%s connections=stopped', info['version'], info['commit'], directory)
    sender = Sender(session, lambda: [session.call('settings')['values'].get('spoolman_url','')])
    from tracker_uid_forecast import SliceForecast
    import tempfile
    forecast = SliceForecast(session, directory/'slices' if os.environ.get('TRACKER20_DATA_DIR') else Path(tempfile.gettempdir())/'snapmaker_orca_model')
    server = thread = shell = None
    previous_signals = {}
    try:
        def status_reader(pid):
            printer = next(p for p in session.call('settings')['values']['printers'] if p['id']==pid)
            if not session.connected:
                raise ValueError('Подключения остановлены.')
            return ReadOnlyMoonraker(printer['url']).status()['print_stats']['state']
        forecast.start()
        server = serve(session,session.fleet,status_reader=status_reader,sender=sender,app_info=info,forecast=forecast)
        thread = threading.Thread(target=server.serve_forever,name='tracker20-http'); thread.start()
        url = f'http://127.0.0.1:{server.server_port}'
        logger.info('GUI %s', url)
        shell = UidWindow(url,directory/'webview',title=f'Snapmaker U1 Spool Tracker {VERSION} · кандидат',tray_title=f'Tracker {VERSION} · кандидат')
        def stop(signum, frame):
            logger.info('Exit requested signal=%s', signum)
            shell.quit()
        for signum in (signal.SIGTERM,signal.SIGINT):
            previous_signals[signum] = signal.getsignal(signum)
            if sys.platform=='darwin':
                # Cocoa may stay inside its native run loop without executing
                # Python bytecode; ordinary Python signal callbacks then wait.
                from PyObjCTools import MachSignals
                MachSignals.signal(signum,lambda number: stop(number,None))
            else:
                signal.signal(signum,stop)
        shell.run()
    except BaseException:
        logger.exception('Application failed')
        raise
    finally:
        for signum, previous in previous_signals.items(): signal.signal(signum,previous)
        if server:
            server.shutdown()
            if thread: thread.join()
            server.server_close()
        sender.stop()
        forecast.stop()
        session.close()
        logger.info('STOP clean shutdown')
        handler.close(); logger.removeHandler(handler)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
