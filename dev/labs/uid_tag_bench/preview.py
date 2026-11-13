"""Five unknown synthetic tags for repeatable visual comparison only."""
from pathlib import Path
import sys,tempfile,copy
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from tracker_uid_runtime import AccountingOwner
from tracker_uid_gui import serve
from test_uid_accounting import snapshot
class Fleet:
    def snapshot(self):return {'a':snapshot('a',{'0':'04112233','1':'04112244','2':'04112255'}),'b':snapshot('b',{'1':'04AABBCC','2':'04AABBDD'})}
if __name__=='__main__':
    f=Fleet();owner=AccountingOwner(Path(tempfile.mkdtemp(prefix='uid-drawer-preview-'))/'db',f)
    owner.call('register_manual','Existing PLA',300000,spool_id='existing')
    server=serve(owner,f,18895,status_reader=lambda pid:'standby')
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();owner.close()
