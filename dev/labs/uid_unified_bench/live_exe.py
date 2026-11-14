"""Ordinary current packaged app against authenticated no-hardware process benches."""
import argparse,json,subprocess,tempfile,time,urllib.request,re,socket
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--exe',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    cfg=json.loads(a.manifest.read_text(encoding='utf-8'))
    assert cfg['kind']=='tracker-process-bench' and cfg['printers']=={'a':18781,'b':18782} and cfg['control_port']==18780
    a.output.mkdir(parents=True,exist_ok=True);root=Path(tempfile.mkdtemp(prefix='uid-unified-exe-live-'));checks=[];app=None;token=None
    def http(port,path,data=None,headers=None):
        r=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json',**(headers or {})})
        with urllib.request.urlopen(r,timeout=50) as v:return json.load(v)
    def api(path,data=None):return http(18783,'/api/'+path,data,{'X-Tracker-Token':token})
    def wait(fn,timeout=70):
        end=time.monotonic()+timeout;error=None
        while time.monotonic()<end:
            try:
                v=fn()
                if v:return v
            except Exception as e:error=str(e)
            time.sleep(.2)
        raise AssertionError('Timeout: '+str(error))
    def check(name,ok):assert ok,name;checks.append(name);print('PASS '+name,flush=True)
    def launch():
        nonlocal token
        cmd=[str(a.exe.resolve()),'--data',str(root),'--port','18783','--allow-url','http://127.0.0.1:18781','--allow-url','http://127.0.0.1:18782']
        proc=subprocess.Popen(cmd,cwd=root)
        def ready():
            nonlocal token
            with urllib.request.urlopen('http://127.0.0.1:18783',timeout=2) as r:html=r.read().decode()
            token=json.loads(re.search(r'const TOKEN=("[^"]+");',html)[1]);return True
        try:wait(ready,90)
        except BaseException:proc.terminate();proc.wait(15);raise
        return proc
    def event(pid,action,**kw):return http(cfg['printers'][pid],'/printer/bench_motion/event',dict(action=action,**kw))
    def subscribed():return all(all(http(port,'/printer/objects/query?bench_transition')['result']['status']['bench_transition']['subscribers']) for port in cfg['printers'].values())
    def connected():return len(api('state')['printers'])==2 and all(p['ready'] for p in api('state')['printers'])
    def control(action):return http(18780,'/',dict(action=action,printer='a'),{'X-Bench-Token':cfg['token']})
    try:
        app=launch();s=api('state');api('settings',dict(values={'printers':[dict(id=pid,name='Process '+pid,url=f'http://127.0.0.1:{port}') for pid,port in cfg['printers'].items()]},expected_revision=s['settings']['revision']))
        api('connections_start',{'confirmed':True});wait(connected)
        for pid,port in cfg['printers'].items():
            api('create',dict(name='Manual '+pid,remaining_g=500,details={'material':'PLA'},assignment=dict(printer_id=pid,channel='0',expected_version='',confirmed=True)))
        wait(subscribed);check('current EXE connects UID motion and history for two printers',api('state')['connections']['collectors_enabled'])
        for pid in cfg['printers']:event(pid,'start',filename='first-'+pid+'.gcode')
        wait(lambda:len(api('state')['jobs'])==2);time.sleep(2)
        for pid in cfg['printers']:event(pid,'motion',head=0,length=100,stamp=1)
        time.sleep(.7)
        for pid in cfg['printers']:event(pid,'complete')
        wait(lambda:len(api('state')['debits'])==2)
        check('verified G-code and real process motion account once',all(s['remaining_mg']==499702 for s in api('state')['spools']))
        for pid in cfg['printers']:event(pid,'start',filename='second-'+pid+'.gcode')
        wait(lambda:len(api('state')['jobs'])==4);time.sleep(2)
        for pid in cfg['printers']:event(pid,'motion',head=0,length=100,stamp=10)
        control('stop');wait(lambda:not next(p for p in api('state')['printers'] if p['id']=='a')['ready'])
        event('b','complete');wait(lambda:len(api('state')['debits'])==3)
        check('second printer accounts during first disconnect',True)
        control('start');wait(connected);wait(subscribed);event('a','cancel');time.sleep(3)
        check('reconnect leaves interrupted evidence blocked',len(api('state')['debits'])==3)
        interrupted=next(j for j in api('state')['jobs'] if j['printer_id']=='a' and not j['mapping_valid'] and j['state']=='active')
        request=dict(job_key=interrupted['job_key'],expected_version=interrupted['resolution_version'],confirmed=True,accept_unaccounted=True,mode='15_minutes')
        api('resolve',request)
        unlocked=next(j for j in api('state')['jobs'] if j['job_key']==interrupted['job_key'])['unlock']
        api('resolve',request)
        check('temporary unlock replay preserves deadline without debit',unlocked['deadline'] is not None and next(j for j in api('state')['jobs'] if j['job_key']==interrupted['job_key'])['unlock']==unlocked and len(api('state')['debits'])==3)
        assignment=next(m for m in api('state')['manual_assignments'] if m['printer_id']=='a')
        sid=assignment['spool_id']
        api('assign',dict(printer_id='a',channel='0',spool_id=sid,expected_version=assignment['version'],confirmed=True))
        balances={s['spool_id']:s['remaining_mg'] for s in api('state')['spools']}
        for src,channel,dst,target in [('a','0','b','1'),('b','1','a','0')]:
            assignment=next(m for m in api('state')['manual_assignments'] if m['spool_id']==sid)
            api('transfer',dict(spool_id=sid,source_printer=src,source_channel=channel,target_printer=dst,target_channel=target,expected_version=assignment['version'],request_id='roundtrip-'+src,confirmed=True))
        check('confirmed roundtrip transfer preserves balances and debit count',balances=={s['spool_id']:s['remaining_mg'] for s in api('state')['spools']} and len(api('state')['debits'])==3)
        api('connections_stop',{'confirmed':True});package=api('backup_package',{});v=api('validate_backup',{'package':package})
        api('restore_backup',dict(package=package,expected_revision=v['current_revision'],confirmed=True));api('connections_start',{'confirmed':True});wait(connected);time.sleep(3)
        check('restore and repeated process history do not duplicate debit',len(api('state')['debits'])==3)
        api('connections_stop',{'confirmed':True});app.terminate();app.wait(15);app=launch()
        check('EXE restart keeps settings and local ledger',len(api('state')['settings']['values']['printers'])==2 and len(api('state')['debits'])==3)
        api('connections_start',{'confirmed':True});wait(connected);time.sleep(3)
        check('restarted collectors do not double debit',len(api('state')['debits'])==3)
        (a.output/'unified-live-result.json').write_text(json.dumps(dict(success=True,checks=checks,state=api('state')),indent=2))
    finally:
        if app and app.poll() is None:app.terminate();app.wait(15)
if __name__=='__main__':main()
