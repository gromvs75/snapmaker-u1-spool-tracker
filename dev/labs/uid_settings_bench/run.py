"""Explicit isolated application entrypoint. No installed settings discovery."""
import argparse
from pathlib import Path
import sys
import threading
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from tracker_uid_session import Session
from tracker_uid_gui import serve


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--port',type=int,default=0);parser.add_argument('--window',action='store_true')
    parser.add_argument('--allow-url',action='append',default=[])
    args=parser.parse_args()
    session=Session(args.data,allowed_urls=args.allow_url)
    server=serve(session,session.fleet,args.port)
    thread=threading.Thread(target=server.serve_forever);thread.start()
    print(f'GUI http://127.0.0.1:{server.server_port} DATA {session.directory}',flush=True)
    try:
        if args.window:
            from tracker_uid_window import UidWindow
            UidWindow(f'http://127.0.0.1:{server.server_port}',session.directory/'webview').run()
        else:thread.join()
    except KeyboardInterrupt:pass
    finally:
        server.shutdown();thread.join();server.server_close();session.close()

if __name__=='__main__':main()
