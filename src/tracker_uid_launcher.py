"""Explicit isolated application entrypoint. No installed settings discovery."""
import argparse
from pathlib import Path
import threading
from tracker_uid_session import Session
from tracker_uid_gui import serve
from tracker_uid_collectors import create_workers,ReadOnlyMoonraker


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--port',type=int,default=0);parser.add_argument('--window',action='store_true')
    parser.add_argument('--allow-url',action='append',default=[])
    parser.add_argument('--allow-spoolman-url',action='append',default=[])
    args=parser.parse_args(argv)
    session=Session(args.data,allowed_urls=args.allow_url,worker_factory=create_workers)
    def status_reader(pid):
        printer=next(p for p in session.call('settings')['values']['printers'] if p['id']==pid)
        if printer['url'] not in args.allow_url:raise ValueError('Endpoint not permitted')
        return ReadOnlyMoonraker(printer['url']).status()['print_stats']['state']
    from tracker_uid_sender import Sender
    sender=None
    try:
        sender=Sender(session,args.allow_spoolman_url) if args.allow_spoolman_url else None
        server=serve(session,session.fleet,args.port,status_reader=status_reader,sender=sender)
    except BaseException:
        session.close();raise
    thread=threading.Thread(target=server.serve_forever);thread.start()
    print(f'GUI http://127.0.0.1:{server.server_port} DATA {session.directory}',flush=True)
    try:
        if args.window:
            from tracker_uid_window import UidWindow
            UidWindow(f'http://127.0.0.1:{server.server_port}',session.directory/'webview').run()
        else:thread.join()
    except KeyboardInterrupt:pass
    finally:
        server.shutdown();thread.join();server.server_close();
        if sender:sender.stop()
        session.close()

if __name__=='__main__':main()
