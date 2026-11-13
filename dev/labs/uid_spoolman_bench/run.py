"""Official local Spoolman API + fault proxy + UID owner. Synthetic data only.

Requires separately started 0.27.1 at fixed loopback port and an explicit marker.
This runner never discovers installed configuration or connects to a printer.
"""
from pathlib import Path
import base64,json,re,socket,sys,tempfile,threading,urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),str(ROOT)]
from tracker_uid_runtime import AccountingOwner
from tracker_uid_sender import Sender
from tracker_uid_spoolman import Client,catalog_item
from tracker_uid_gui import serve
from test_uid_accounting import snapshot
from test_uid_motion_adapter import evidence
from test_accounting import setup_plan

REAL='http://127.0.0.1:18897'
MARKER=Path('/private/tmp/tracker-spoolman-data-20261113/.tracker-spoolman-bench')
class Fleet:
    def snapshot(self):return {pid:snapshot(pid,{}) for pid in ('a','b')}


def main():
    if not MARKER.is_file() or MARKER.read_text()!='synthetic-only':raise RuntimeError('Explicit disposable Spoolman marker required')
    real=Client(REAL);assert real.request('GET','/info')[0]['version']=='0.27.1'
    filament=real.request('POST','/filament',{'name':'UID delivery bench','material':'PLA','density':1.24,'diameter':1.75,'weight':500})[0]
    spool=real.request('POST','/spool',{'filament_id':filament['id'],'initial_weight':500})[0]
    remote_id=spool['id'];writes=[];fault=[''];events=[]
    class Proxy(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def forward(self,method):
            if not self.path.startswith('/api/v1/'):self.send_error(404);return
            body=json.loads(self.rfile.read(int(self.headers['Content-Length']))) if method=='PUT' else None
            drop=fault[0] if method=='PUT' else ''
            if method=='PUT':writes.append({'body':body,'fault':drop})
            if drop!='before':result,_=real.request(method,self.path[len('/api/v1'):],body)
            if drop in ('before','after'):
                self.close_connection=True
                self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            raw=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):self.forward('GET')
        def do_PUT(self):self.forward('PUT')
    proxy=ThreadingHTTPServer(('127.0.0.1',0),Proxy);pt=threading.Thread(target=proxy.serve_forever);pt.start()
    url=f'http://127.0.0.1:{proxy.server_port}';root=Path(tempfile.mkdtemp(prefix='uid-spoolman-live-'))
    owner=AccountingOwner(root/'uid.sqlite',Fleet());sender=Sender(owner,[url]);gui=None;gt=None
    def check(name,value):
        assert value,name
        events.append({'check':name,'passed':True});print('PASS '+name,flush=True)
    try:
        store,*_=setup_plan(root)
        item=catalog_item(spool);cache=owner.call('cache_catalog',url,{str(remote_id):item})
        owner.call('create_spool','Remote',500,remote=dict(url=url,id=remote_id,revision=cache['revision']),assignment=dict(printer_id='a',channel='0',expected_version='',confirmed=True))
        owner.call('create_spool','Local B',500,details={'material':'PLA'},assignment=dict(printer_id='b',channel='0',expected_version='',confirmed=True))
        def use(pid,run):
            e=evidence(store);e['start']=owner.call('inventory_snapshot',pid);e['capture_id']=f'{pid}-{run}';e['terminal_state']='completed'
            start=1010.+run*100;e['profile']['started_at']=start
            owner.call('start',pid,filename='job.gcode',observed_at=start,capture_id=e['capture_id'],epoch=e['epoch'],start=e['start'],channels=['0'])
            owner.call('terminal',pid,e)
            h=[dict(job_id=f'{pid}-{run}',start_time=start,filename='job.gcode',status='completed')]
            owner.call('history',pid,h);return h
        def balance():return real.request('GET',f'/spool/{remote_id}')[0]['remaining_weight']
        def decide(action='approve',index=-1):
            row=owner.call('delivery_list')[index]
            return owner.call('delivery_decide',row['operation_id'],row['revision'],action,'Verified against isolated Spoolman',f"{row['revision']}:{action}",True)
        use('a',0);decide();check('official Spoolman receives exact .298 g',sender.send_one()=='sent' and abs(balance()-499.702)<1e-6)
        backup=owner.call('export_backup')
        history=use('a',1);decide();fault[0]='after'
        check('server applies write but lost response becomes uncertain',sender.send_one()=='uncertain' and abs(balance()-499.404)<1e-6)
        count=len(writes);fault[0]=''
        for _ in range(3):owner.call('history','a',history);sender.send_one()
        check('history and retries do not duplicate remote write',len(writes)==count)
        use('b',0);check('local second printer continues during uncertainty',len(owner.call('inspect')['debits'])==3)
        owner.close();owner=AccountingOwner(root/'uid.sqlite',Fleet());sender=Sender(owner,[url])
        check('restart does not retry uncertain write',sender.send_one()=='blocked' and len(writes)==count)
        decide('applied');check('manual applied reconciles without HTTP',sender.send_one()=='idle' and len(writes)==count)
        row=owner.call('inspect')['manual_assignments'][0]
        owner.call('assign_manual',row['printer_id'],row['channel'],row['spool_id'],confirmed=True,expected_version=row['version'])
        use('a',2);decide();fault[0]='before';check('lost request before server still needs review',sender.send_one()=='uncertain' and abs(balance()-499.404)<1e-6)
        decide('not_applied');fault[0]='';check('explicit not-applied permits exactly one new attempt',sender.send_one()=='sent' and abs(balance()-499.106)<1e-6)
        # Export while pending, then send, then open that older snapshot elsewhere.
        use('a',3);decide();old=owner.call('export_backup');assert sender.send_one()=='sent'
        restored=root/'restored.sqlite';restored.write_bytes(base64.b64decode(old['base64']))
        other=AccountingOwner(restored,Fleet())
        try:
            count=len(writes)
            check('older backup is quarantined instead of resending',Sender(other,[url]).send_one()=='blocked' and len(writes)==count)
        finally:other.close()
        # Public localhost bridge exposes the same revision-checked manual decision.
        use('a',4)
        gui=serve(owner,Fleet(),sender=sender);gt=threading.Thread(target=gui.serve_forever);gt.start()
        base=f'http://127.0.0.1:{gui.server_port}'
        html=urllib.request.urlopen(base).read().decode();token=json.loads(re.search(r'const TOKEN=("[^"]+")',html)[1])
        row=owner.call('delivery_list')[-1]
        def post(path,body):
            request=urllib.request.Request(base+'/api/'+path,data=json.dumps(body).encode(),headers={'X-Tracker-Token':token,'Content-Type':'application/json'})
            with urllib.request.urlopen(request) as reply:return json.load(reply)
        post('delivery_decide',dict(operation_id=row['operation_id'],expected_revision=row['revision'],decision='approve',note='Operator checked test operation',request_id='http-approval',confirmed=True))
        check('authenticated bridge sends approved operation',post('delivery_send',{'confirmed':True})['status']=='sent')
        check('remote balance matches five unique usages',abs(balance()-498.51)<1e-6)
        output=ROOT/'output/spoolman-live';output.mkdir(parents=True,exist_ok=True)
        report=dict(success=True,checks=events,real_server=REAL,spool_id=remote_id,remaining_g=balance(),writes=writes,tracker=owner.call('inspect'),delivery=owner.call('delivery_list'),audit=owner.call('delivery_audit'),root=str(root))
        (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    finally:
        if gui:gui.shutdown();gt.join();gui.server_close()
        sender.stop();owner.close();proxy.shutdown();pt.join();proxy.server_close()
    print(f'{len(events)} official Spoolman checks passed; local proxy and owner stopped')
if __name__=='__main__':main()
