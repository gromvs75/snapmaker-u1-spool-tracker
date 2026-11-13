"""Isolated GUI demo; no printer sockets, old Store or installed app imports."""
from pathlib import Path
import sys,tempfile,copy,argparse,json,platform
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from tracker_uid_runtime import AccountingOwner
from tracker_uid_gui import serve
class Fleet:
    def __init__(self):
        self.states={pid:dict(printer_id=pid,state='ready',client_session='gui-bench',generation=1,epoch='fixture',
            channels={str(i):dict(state='absent',uid=None) for i in range(4)}) for pid in ('a','b')}
    def snapshot(self):return copy.deepcopy(self.states)

def setup(root, resolution=False):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    fleet=Fleet();path=root/'gui.sqlite';owner=AccountingOwner(path,fleet)
    owner.call('register_manual','Чёрный PLA',500000,spool_id='manual-black',details={'material':'PLA'})
    owner.call('register_manual','Оранжевый PETG',123456,spool_id='manual-orange',details={'material':'PETG'})
    owner.call('assign_manual','a','0','manual-black',confirmed=True)
    owner.close() # Fixture starts with an assignment needing renewed confirmation.
    if resolution:
        import time
        from types import SimpleNamespace
        import tracker_uid_accounting
        (root/'clock-offset.txt').write_text('0')
        tracker_uid_accounting.time=SimpleNamespace(time=lambda:time.time()+float((root/'clock-offset.txt').read_text()),monotonic=time.monotonic)
        from tracker_uid_catalog import UidCatalog
        from tracker_uid_accounting import UidAccounting
        catalog=UidCatalog(path);accounting=UidAccounting(catalog)
        accounting.assign_manual('a','0','manual-black',fleet.snapshot(),confirmed=True)
        accounting.assign_manual('b','1','manual-orange',fleet.snapshot(),confirmed=True)
        key=accounting.begin('a','native-interrupted','1794313351',['0'],'native-fixture',fleet.snapshot())
        catalog.db.execute('UPDATE uid_jobs SET mapping_valid=0 WHERE job_key=?',(key,))
        catalog.db.execute("UPDATE uid_spools SET remaining_mg=499702 WHERE spool_id='manual-black'")
        catalog.db.execute("UPDATE uid_spools SET remaining_mg=299404 WHERE spool_id='manual-orange'")
        catalog.db.commit();catalog.close()
        (root/'print-state.txt').write_text('cancelled')
    owner=AccountingOwner(path,fleet)
    if resolution:owner.call('assign_manual','b','1','manual-orange',confirmed=True)
    return owner,fleet

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=18749);parser.add_argument('--window',action='store_true');parser.add_argument('--resolution',action='store_true');args=parser.parse_args()
    root=Path(tempfile.mkdtemp(prefix='uid-gui-bench-'))
    owner,fleet=setup(root,args.resolution)
    try:server=serve(owner,fleet,args.port,status_reader=(lambda pid:(root/'print-state.txt').read_text().strip()) if args.resolution else None)
    except BaseException:
        owner.close();raise
    thread=None
    run_info={'platform':platform.platform(),'python':platform.python_version(),'native_gui_requested':args.window,'native_event_loop_returned':False,'renderer':None}
    (root/'run-info.json').write_text(json.dumps(run_info,indent=2),encoding='utf-8')
    print(f'GUI http://127.0.0.1:{server.server_port} DATA {root}',flush=True)
    try:
        if args.window:
            import threading,webview
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            from tracker_uid_window import UidWindow
            UidWindow(f'http://127.0.0.1:{server.server_port}', root/'webview').run()
            run_info['native_event_loop_returned']=True
            run_info['renderer']=getattr(webview,'renderer',None)
        else:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        if thread is not None:
            server.shutdown();thread.join()
        server.server_close()
        try:
            (root/'verification.json').write_text(json.dumps(owner.call('inspect'),ensure_ascii=False,indent=2),encoding='utf-8')
            (root/'run-info.json').write_text(json.dumps(run_info,indent=2),encoding='utf-8')
        finally:owner.close()
if __name__=='__main__':main()
