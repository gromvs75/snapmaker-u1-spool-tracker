"""User candidate entrypoint. Separate persistent data; explicit connections only."""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import sys
import threading

VERSION = '2.0.0rc9'


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
    arguments=sys.argv[1:] if argv is None else argv
    if arguments:
        if len(arguments)!=1 or arguments[0].startswith('-'):return 2
        from tracker_user_hook import handle_slicer_hook
        return handle_slicer_hook(data_directory(),arguments[0],output_name=os.environ.get('SLIC3R_PP_OUTPUT_NAME'))
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
        try:
            from tracker_user_hook import instance_call
            instance_call(directory,'window',{'action':'show'})
        except (ValueError,OSError,KeyError):pass
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
    descriptor=directory/'instance.json'
    try:
        def status_reader(pid):
            printer = next(p for p in session.call('settings')['values']['printers'] if p['id']==pid)
            if not session.connected:
                raise ValueError('Подключения остановлены.')
            return ReadOnlyMoonraker(printer['url']).status()['print_stats']['state']
        from tracker_desktop_files import BackupFiles
        import webview
        backup_files=BackupFiles(lambda: shell._window if shell else None,webview,
                                 on_dialog_closed=lambda: shell.show() if shell else None)
        forecast.start()
        server = serve(session,session.fleet,status_reader=status_reader,sender=sender,app_info=info,forecast=forecast,
                       window_action=lambda action:getattr(shell,action)() if shell else None,backup_file=backup_files)
        thread = threading.Thread(target=server.serve_forever,name='tracker20-http'); thread.start()
        url = f'http://127.0.0.1:{server.server_port}'
        logger.info('GUI %s', url)
        shell = UidWindow(url,directory/'webview',title=f'Snapmaker U1 Spool Tracker {VERSION} · кандидат',tray_title=f'Tracker {VERSION} · кандидат',forecast=forecast)
        # Per-profile IPC capability, never a public fixed-port write endpoint.
        from tracker_uid_migration import atomic
        atomic(descriptor,json.dumps(dict(port=server.server_port,token=server.tracker_token)).encode())
        descriptor.chmod(0o600)
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
        descriptor.unlink(missing_ok=True)
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
