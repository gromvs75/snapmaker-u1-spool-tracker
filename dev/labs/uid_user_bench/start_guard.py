"""Packaged user app: explicit experimental pause on NO-HARDWARE processes."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--exe',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();cfg=json.loads(args.manifest.read_text())
    assert cfg['kind']=='tracker-process-bench' and cfg['printers']=={'a':18781,'b':18782}
    root=Path(tempfile.mkdtemp(prefix='tracker-user-guard-'));args.output.mkdir(parents=True,exist_ok=True)
    app=None;descriptor=None;checks=[]
    def http(port,path,data=None,token=None):
        req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json',**({'X-Tracker-Token':token} if token else {})})
        with urllib.request.urlopen(req,timeout=15) as response:return json.load(response)
    def api(path,data=None):return http(descriptor['port'],'/api/'+path,data,descriptor['token'])
    def wait(fn):
        end=time.monotonic()+60;last=None
        while time.monotonic()<end:
            try:
                result=fn()
                if result:return result
            except Exception as exc:last=str(exc)
            time.sleep(.2)
        raise AssertionError('Timed out: '+str(last))
    def check(name,ok):assert ok,name;checks.append(name);print('PASS '+name,flush=True)
    def launch():
        nonlocal app,descriptor
        app=subprocess.Popen([str(args.exe.resolve())],env=dict(os.environ,TRACKER20_DATA_DIR=str(root)),cwd=root)
        descriptor=wait(lambda:json.loads((root/'instance.json').read_text()))
        wait(lambda:api('state'))
    def stop():
        nonlocal app
        app.terminate();app.wait(15);assert app.returncode==0;app=None
    def event(pid,action,**kw):return http(cfg['printers'][pid],'/printer/bench_motion/event',dict(action=action,**kw))
    def commands(pid):return http(cfg['printers'][pid],'/printer/objects/query?bench_transition')['result']['status']['bench_transition']['control_commands']
    def connected():return len(api('state')['printers'])==2 and all(p['ready'] for p in api('state')['printers'])
    def guard():return api('desktop/data')['last_guard']
    try:
        baseline={pid:commands(pid) for pid in cfg['printers']};launch()
        api('settings',dict(values=dict(printers=[dict(id=pid,name='Process '+pid,url=f'http://127.0.0.1:{port}') for pid,port in cfg['printers'].items()],guard_modes={'a':'strict','b':'warn'}),expected_revision=api('state')['settings']['revision']))
        api('connections_start',{'confirmed':True});wait(connected)
        for pid in cfg['printers']:event(pid,'start',filename='recovery.gcode')
        wait(lambda:guard() and guard()['state']=='paused')
        check('strict pauses observed new job exactly once',commands('a')==baseline['a']+['PAUSE'])
        check('warning mode never commands other printer',commands('b')==baseline['b'])
        check('full shell reports confirmed live pause',api('desktop/data')['monitor']['state']=='paused')
        saved=guard();api('connections_stop',{'confirmed':True});stop();launch()
        check('normal restart preserves mode and keeps connections stopped',not api('state')['connections']['connected'] and api('state')['settings']['values']['guard_modes']['a']=='strict')
        api('connections_start',{'confirmed':True});wait(connected);time.sleep(3)
        check('reconnect does not repeat pause',commands('a')==baseline['a']+['PAUSE'])
        result=api('desktop/guard/decision',dict(printer_id='a',expected_revision=saved['revision'],action='resume',confirmed=True))
        check('explicit resume verifies same job',result['state']=='resumed' and commands('a')==baseline['a']+['PAUSE','RESUME'])
        try:api('desktop/guard/decision',dict(printer_id='a',expected_revision=saved['revision'],action='resume',confirmed=True))
        except urllib.error.HTTPError as exc:assert exc.code==409
        else:raise AssertionError('stale decision accepted')
        check('repeated decision does not repeat command or debit',commands('a')==baseline['a']+['PAUSE','RESUME'] and not api('state')['debits'])
        for pid in cfg['printers']:event(pid,'cancel')
        api('connections_stop',{'confirmed':True});stop()
        (args.output/'results.json').write_text(json.dumps(dict(success=True,checks=checks,data=str(root)),indent=2))
    finally:
        if app and app.poll() is None:stop()


if __name__=='__main__':main()
