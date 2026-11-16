"""Ordinary user package + disposable official Spoolman + lost-response proxy."""
import argparse,json,os,re,socket,subprocess,sys,tempfile,threading,time,urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),str(ROOT)]
from tracker_uid_spoolman import Client,catalog_item
from tracker_uid_runtime import AccountingOwner
from dev.labs.uid_spoolman_bench.run import Fleet
from test_accounting import setup_plan
from test_uid_motion_adapter import evidence


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--exe',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);a=parser.parse_args()
    root=Path(tempfile.mkdtemp(prefix='tracker-user-spoolman-'));a.output.mkdir(parents=True,exist_ok=True)
    data=root/'tracker';data.mkdir();remote=root/'spoolman';remote.mkdir()
    env=dict(os.environ,SPOOLMAN_DB_TYPE='sqlite',SPOOLMAN_DIR_DATA=str(remote),SPOOLMAN_DIR_LOGS=str(remote),SPOOLMAN_DIR_BACKUPS=str(remote/'backups'),SPOOLMAN_UPDATE_CHECK='FALSE',EXTERNAL_DB_SYNC_INTERVAL='0',PATH='/private/tmp/tracker-spoolman-server-env/bin:'+os.environ['PATH'])
    log=(root/'spoolman-console.log').open('w')
    upstream=subprocess.Popen(['/private/tmp/tracker-spoolman-server-env/bin/python','-m','uvicorn','spoolman.main:app','--host','127.0.0.1','--port','18997'],cwd='/private/tmp/tracker-spoolman-0271',env=env,stdout=log,stderr=subprocess.STDOUT)
    real=Client('http://127.0.0.1:18997');app=proxy=None;thread=None;checks=[];writes=[];fault=[''];base=token=None
    def wait(fn):
        for _ in range(200):
            try:
                value=fn()
                if value:return value
            except Exception:pass
            time.sleep(.1)
        raise AssertionError('Timed out')
    def check(name,ok):assert ok,name;checks.append(name);print('PASS '+name,flush=True)
    def api(path,value=None):
        request=urllib.request.Request(base+'/api/'+path,data=None if value is None else json.dumps(value).encode(),headers={'X-Tracker-Token':token,'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=20) as r:return json.load(r)
    def launch():
        nonlocal app,base,token
        app=subprocess.Popen([str(a.exe.resolve())],env=dict(os.environ,TRACKER20_DATA_DIR=str(data)),cwd=data)
        def ready():
            nonlocal base,token
            base='http://127.0.0.1:'+re.findall(r'GUI http://127.0.0.1:(\d+)',(data/'logs/tracker.log').read_text())[-1]
            html=urllib.request.urlopen(base,timeout=1).read().decode();token=json.loads(re.search(r'const TOKEN=("[^"]+")',html)[1]);return True
        wait(ready)
    def stop():
        nonlocal app
        app.terminate();app.wait(10);assert app.returncode==0;app=None
    try:
        wait(lambda:real.request('GET','/info')[0]['version']=='0.27.1')
        filament=real.request('POST','/filament',{'name':'Candidate disposable PLA','material':'PLA','density':1.24,'diameter':1.75,'weight':500})[0]
        spool=real.request('POST','/spool',{'filament_id':filament['id'],'initial_weight':500})[0]
        class Proxy(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def forward(self,method):
                assert self.path.startswith('/api/v1/')
                body=json.loads(self.rfile.read(int(self.headers['Content-Length']))) if method=='PUT' else None
                if method=='PUT':writes.append(body)
                if method!='PUT' or fault[0]!='before':value,_=real.request(method,self.path[7:],body)
                if method=='PUT' and fault[0] in ('before','after'):
                    self.close_connection=True;self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                raw=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def do_GET(self):self.forward('GET')
            def do_PUT(self):self.forward('PUT')
        proxy=ThreadingHTTPServer(('127.0.0.1',0),Proxy);thread=threading.Thread(target=proxy.serve_forever);thread.start()
        url=f'http://127.0.0.1:{proxy.server_port}'
        owner=AccountingOwner(data/'tracker.sqlite',Fleet())
        try:
            cache=owner.call('cache_catalog',url,{str(spool['id']):catalog_item(spool)})
            owner.call('create_spool','Candidate remote',500,remote=dict(url=url,id=spool['id'],revision=cache['revision']),assignment=dict(printer_id='a',channel='0',expected_version='',confirmed=True))
            owner.call('save_settings',values={'spoolman_url':url},expected_revision=owner.call('settings')['revision'])
            store,*_=setup_plan(root/'fixture')
            for n in range(3):
                e=evidence(store);e['start']=owner.call('inventory_snapshot','a');e['capture_id']='packaged-'+str(n);e['terminal_state']='completed';start=1010.+100*n;e['profile']['started_at']=start
                owner.call('start','a',filename='job.gcode',observed_at=start,capture_id=e['capture_id'],epoch=e['epoch'],start=e['start'],channels=['0'])
                owner.call('terminal','a',e);owner.call('history','a',[dict(job_id='test-'+str(n),start_time=start,filename='job.gcode',status='completed')])
        finally:owner.close()
        launch()
        def rows():return api('state')['delivery']
        def decide(index,decision):
            row=rows()[index]
            return api('delivery_decide',dict(operation_id=row['operation_id'],expected_revision=row['revision'],decision=decision,note='Verified against disposable official Spoolman',request_id=row['revision']+decision,confirmed=True))
        def send():return api('delivery_send',{'confirmed':True})['status']
        def balance():return real.request('GET',f"/spool/{spool['id']}")[0]['remaining_weight']
        check('packaged app reads only configured test catalog',api('refresh_catalog',{})['available'])
        for index in range(3):decide(index,'not_applied')
        check('explicit packaged send debits exactly .298g',send()=='sent' and abs(balance()-499.702)<1e-6)
        old=api('backup_package',{});fault[0]='after'
        check('lost applied response becomes uncertain',send()=='uncertain' and abs(balance()-499.404)<1e-6)
        stop();launch();count=len(writes)
        check('restart preserves queue and refuses uncertain retry',send()=='blocked' and len(writes)==count and len(api('state')['debits'])==3)
        fault[0]='';decide(1,'applied');check('manual applied never repeats remote write',send()=='blocked' and len(writes)==count)
        preview=api('validate_backup',{'package':old});api('restore_backup',dict(package=old,expected_revision=preview['current_revision'],confirmed=True))
        check('older pending backup cannot resend automatically',send()=='blocked' and len(writes)==count)
        decide(1,'applied');decide(2,'not_applied');fault[0]='before'
        check('lost request also remains uncertain',send()=='uncertain' and abs(balance()-499.404)<1e-6)
        decide(2,'not_applied');fault[0]=''
        check('explicit retry sends only additional operation',send()=='sent' and abs(balance()-499.106)<1e-6)
        check('repeat send is idle and local ledger unchanged',send()=='idle' and len(api('state')['debits'])==3)
        stop();check('packaged exit records clean shutdown',(data/'logs/tracker.log').read_text().rstrip().endswith('STOP clean shutdown'))
        (a.output/'results.json').write_text(json.dumps(dict(success=True,checks=checks,root=str(root),writes=writes,remote_remaining_g=balance()),indent=2))
    finally:
        if app and app.poll() is None:stop()
        if proxy:proxy.shutdown();thread.join();proxy.server_close()
        upstream.terminate();upstream.wait(15);log.close()
if __name__=='__main__':main()
