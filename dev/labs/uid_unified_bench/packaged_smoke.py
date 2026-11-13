"""Portable packaged bridge smoke; does not claim native tray verification."""
import argparse,json,subprocess,tempfile,socket,time,urllib.request,re
from pathlib import Path

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--exe',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True);root=Path(tempfile.mkdtemp(prefix='uid-packaged-smoke-'));checks=[]
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    command=[str(args.exe.resolve()),'--data',str(root),'--port',str(port)]
    app=subprocess.Popen(command,cwd=root);token=None
    def wait(fn):
        end=time.monotonic()+90
        while time.monotonic()<end:
            try:
                if fn():return
            except (OSError,ValueError):pass
            if app.poll() is not None:raise AssertionError('Packaged app exited')
            time.sleep(.1)
        raise AssertionError('Packaged app timed out')
    def ready():
        nonlocal token
        with urllib.request.urlopen(f'http://127.0.0.1:{port}',timeout=2) as response:html=response.read().decode()
        token=json.loads(re.search(r'const TOKEN=("[^"]+");',html)[1]);return True
    def api(route,data=None):
        request=urllib.request.Request(f'http://127.0.0.1:{port}/api/{route}',data=json.dumps(data).encode() if data is not None else None,headers={'X-Tracker-Token':token,'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=10) as response:return json.load(response)
    try:
        wait(ready);checks.append('packaged GUI HTML and authenticated API load')
        state=api('state');api('settings',dict(values={'printer_names':{'a':'Bench A'}},expected_revision=state['settings']['revision']))
        api('create',dict(name='Temporary spool',remaining_g=123.456,details={'material':'PLA'}))
        package=api('backup_package',{});preview=api('validate_backup',{'package':package});assert preview['spools']==1
        api('create',dict(name='Discarded by restore',remaining_g=1))
        preview=api('validate_backup',{'package':package})
        api('restore_backup',dict(package=package,expected_revision=preview['current_revision'],confirmed=True))
        state=api('state');assert len(state['spools'])==1 and state['spools'][0]['remaining_mg']==123456
        checks.append('settings save backup integrity restore preserve balance')
        second=subprocess.Popen([*command[:-1],'0'],cwd=root)
        try:assert second.wait(30)!=0
        finally:
            if second.poll() is None:second.terminate();second.wait(10)
        assert api('state')['spools']==state['spools'];checks.append('second process rejected without database mutation')
        (args.output/'packaged-smoke.json').write_text(json.dumps(dict(checks=checks,root=str(root),native_tray_verified=False),indent=2))
    finally:
        if app.poll() is None:app.terminate();app.wait(15)
if __name__=='__main__':main()
