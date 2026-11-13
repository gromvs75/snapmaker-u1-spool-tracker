"""Disposable official Spoolman + fault proxy; manual decisions through GUI."""
from pathlib import Path
import sys,threading,json,tempfile,socket,time,base64
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from tracker_uid_runtime import AccountingOwner
from tracker_uid_sender import Sender
from tracker_uid_spoolman import Client,catalog_item
from tracker_uid_gui import serve
from test_uid_delivery import Fleet
from test_uid_motion_adapter import evidence
from test_accounting import setup_plan

def main():
    marker=Path('/private/tmp/tracker-spoolman-data-20261113/.tracker-spoolman-bench')
    assert marker.read_text()=='synthetic-only'
    real=Client('http://127.0.0.1:18897');assert real.request('GET','/info')[0]['version']=='0.27.1'
    filament=real.request('POST','/filament',dict(name='GUI reconciliation',material='PLA',density=1.24,diameter=1.75,weight=500))[0]
    spool=real.request('POST','/spool',dict(filament_id=filament['id'],initial_weight=500))[0]
    rid=spool['id'];fault=['after'];writes=[];checks=[]
    class Proxy(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def forward(self,method):
            assert self.path.startswith('/api/v1/')
            data=json.loads(self.rfile.read(int(self.headers['Content-Length']))) if method=='PUT' else None
            drop=fault[0] if method=='PUT' else ''
            if method=='PUT':writes.append(dict(body=data,fault=drop))
            if drop!='before':result,_=real.request(method,self.path[len('/api/v1'):],data)
            if drop:
                self.close_connection=True;self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            raw=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):self.forward('GET')
        def do_PUT(self):self.forward('PUT')
    proxy=ThreadingHTTPServer(('127.0.0.1',0),Proxy);pt=threading.Thread(target=proxy.serve_forever);pt.start()
    root=Path(tempfile.mkdtemp(prefix='uid-delivery-gui-'));out=ROOT/'output/delivery-gui';out.mkdir(parents=True,exist_ok=True)
    owner=AccountingOwner(root/'db',Fleet());sender=Sender(owner,[f'http://127.0.0.1:{proxy.server_port}']);server=None;gt=None
    def check(name,ok):assert ok,name;checks.append(name);print('PASS '+name,flush=True)
    def wait(fn):
        deadline=time.monotonic()+300
        while time.monotonic()<deadline:
            if fn():return
            time.sleep(.1)
        raise AssertionError('GUI handoff timed out')
    try:
        store,*_=setup_plan(root);url=f'http://127.0.0.1:{proxy.server_port}'
        cache=owner.call('cache_catalog',url,{str(rid):catalog_item(spool)})
        owner.call('create_spool','Spoolman GUI PLA',500,remote=dict(url=url,id=rid,revision=cache['revision']),assignment=dict(printer_id='a',channel='0',expected_version='',confirmed=True))
        def use(run):
            e=evidence(store);e['start']=owner.call('inventory_snapshot','a');e['capture_id']=f'gui-{run}';e['terminal_state']='completed';start=1010.+100*run;e['profile']['started_at']=start
            owner.call('start','a',filename='job.gcode',observed_at=start,capture_id=e['capture_id'],epoch=e['epoch'],start=e['start'],channels=['0'])
            owner.call('terminal','a',e);h=[dict(job_id=f'gui-{run}',start_time=start,filename='job.gcode',status='completed')];owner.call('history','a',h);return h
        def prepare(run):
            h=use(run);r=owner.call('delivery_list')[-1];owner.call('delivery_decide',r['operation_id'],r['revision'],'approve','Test setup first send',f'seed-{run}',True)
            assert sender.send_one()=='uncertain';fault[0]='';return h
        first=prepare(0);backup=owner.call('export_backup')
        server=serve(owner,Fleet(),18898,sender=sender);gt=threading.Thread(target=server.serve_forever);gt.start();(out/'ready').write_text(str(root));print('GUI_READY phase1',flush=True)
        wait(lambda:owner.call('delivery_list')[0]['state']=='sent')
        check('GUI applied decision sends no HTTP',len(writes)==1)
        fault[0]='before';second=prepare(1);print('GUI_READY phase2',flush=True)
        wait(lambda:owner.call('delivery_list')[-1]['state']=='sent')
        check('GUI not-applied and explicit send make one new attempt',len(writes)==3)
        for _ in range(4):owner.call('history','a',first);owner.call('history','a',second);sender.send_one()
        check('repeated history and sender do not double debit',len(writes)==3 and len(owner.call('inspect')['debits'])==2)
        check('official remote balance equals two unique debits',abs(real.request('GET',f'/spool/{rid}')[0]['remaining_weight']-499.404)<1e-6)
        restored=root/'restored.sqlite';restored.write_bytes(base64.b64decode(backup['base64']));other=AccountingOwner(restored,Fleet())
        try:check('restored old uncertain copy cannot resend',Sender(other,[url]).send_one()=='blocked' and len(writes)==3)
        finally:other.close()
        (out/'results.json').write_text(json.dumps(dict(checks=checks,writes=writes,spool_id=rid,root=str(root),delivery=owner.call('delivery_list'),audit=owner.call('delivery_audit')),indent=2));print('DONE',flush=True)
    finally:
        if server:server.shutdown();gt.join();server.server_close()
        sender.stop();owner.close();proxy.shutdown();pt.join();proxy.server_close()
if __name__=='__main__':main()
