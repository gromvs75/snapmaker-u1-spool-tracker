"""Full-process integration; local marked fixture only, children always reaped."""
from pathlib import Path
import sys, subprocess, time, json, urllib.request, urllib.error, socket, hashlib
import websocket
ROOT=Path('/private/tmp/tracker-uid-live')
REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO/'dev/labs/uid_module_bench'))
from install import Installer
DATA=ROOT/'printer_data'; PYTHON=ROOT/'env/bin/python'
BASE='http://127.0.0.1:18726'
RESULTS=[]

def http(path, body=None):
    req=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=3) as response:return json.load(response)

def wait(fn, timeout=20):
    until=time.monotonic()+timeout; last=None
    while time.monotonic()<until:
        try:
            result=fn()
            if result:return result
        except Exception as exc:last=exc
        time.sleep(.15)
    raise AssertionError('Timeout: '+str(last))

def check(name, truth, evidence=None):
    assert truth,name
    RESULTS.append({'check':name,'passed':True,'evidence':evidence})
    print('PASS '+name,flush=True)

def start_klippy():
    (ROOT/'.klipper-running').write_text('bench runner\n')
    with (DATA/'logs/klippy-console.log').open('ab') as log:
        return subprocess.Popen([str(PYTHON),str(ROOT/'klipper/klippy/klippy.py'),str(DATA/'config/printer.cfg'),'-a',str(DATA/'comms/klippy.sock'),'-I',str(ROOT/'gcode'),'-o',str(ROOT/'mcu.output'),'-d',str(ROOT/'mcu.dict'),'-l',str(DATA/'logs/klippy.log')],stdout=log,stderr=log)

def stop(p):
    if p and p.poll() is None:
        p.terminate()
        try:p.wait(timeout=6)
        except subprocess.TimeoutExpired:p.kill();p.wait(timeout=3)

def ready():return wait(lambda:(r if (r:=http('/printer/info'))['result']['state']=='ready' else None))
def uid():return http('/printer/objects/query?tracker_uid')['result']['status']['tracker_uid']
def objects():return http('/printer/objects/list')['result']['objects']
def channel_state(ch,state):
    return wait(lambda:(s if (s:=uid())['channels'][str(ch)]['state']==state else None))
def disconnected():return wait(lambda: not http('/server/info')['result']['klippy_connected'])
def stop_k(k):
    stop(k);(ROOT/'.klipper-running').unlink(missing_ok=True);disconnected()

def main():
    installer=Installer(ROOT) # Explicit marker check before processes/mutations.
    with socket.socket() as sock:sock.bind(('127.0.0.1',18726))
    k=m=ws=None
    driver=ROOT/'klipper/klippy/extras/fm175xx_reader.py';original_driver=driver.read_bytes()
    installer.rollback()
    config=DATA/'config/printer.cfg'; original_config=config.read_bytes()
    installed=False
    completed=False
    try:
        with (DATA/'logs/moonraker-console.log').open('ab') as log:
            m=subprocess.Popen([str(ROOT/'env/bin/moonraker'),'-d',str(DATA),'-c',str(DATA/'config/moonraker.conf'),'-l',str(DATA/'logs/moonraker.log')],stdout=log,stderr=log)
        wait(lambda:http('/server/info'))
        k=start_klippy();ready()
        check('baseline Klipper ready without UID module','tracker_uid' not in objects())
        http('/printer/bench_radio/scan',{'channel':0})
        baseline=wait(lambda:(ev if (ev:=http('/printer/objects/query?bench_radio')['result']['status']['bench_radio']['stock_callbacks']) else None))
        stop_k(k);k=None
        check('install files and config include',installer.install()=='installed');installed=True
        k=start_klippy();ready()
        current=uid();epoch=current['epoch']
        check('load_config + connect + ready',current['state']=='ready' and current['driver_version']=='2.1.0.157',current)
        check('HTTP custom endpoint',wait(lambda:http('/printer/tracker_uid/status'))['result']['epoch']==epoch)
        check('standard objects/list','tracker_uid' in objects())
        refused=False
        try:installer.rollback()
        except ValueError:refused=True
        check('rollback refuses running Klipper',refused)
        ws=websocket.create_connection('ws://127.0.0.1:18726/websocket',timeout=8)
        ws.send(json.dumps({'jsonrpc':'2.0','id':1,'method':'printer.objects.subscribe','params':{'objects':{'tracker_uid':None}}}))
        while True:
            answer=json.loads(ws.recv())
            if answer.get('id')==1:break
        check('WebSocket subscription initial state',answer['result']['status']['tracker_uid']['state']=='ready')
        http('/printer/bench_radio/scan',{'channel':0})
        state=channel_state(0,'present')
        check('unknown Mifare UID through real thread/reactor/HTTP',state['channels']['0']['uid']=='04112233',state['channels']['0'])
        notice=wait(lambda:(v if (v:=json.loads(ws.recv())).get('method')=='notify_status_update' and v['params'][0].get('tracker_uid',{}).get('channels',{}).get('0',{}).get('uid')=='04112233' else None))
        check('WebSocket push delivers UID',bool(notice),notice)
        http('/printer/bench_radio/scan',{'channel':1})
        state=channel_state(1,'present')
        check('blank NTAG full seven-byte UID',state['channels']['1']['uid']=='04112233445566',state['channels']['1'])
        events=http('/printer/objects/query?bench_radio')['result']['status']['bench_radio']['stock_callbacks']
        check('stock failure callback unchanged',events[0]==baseline[0],{'baseline':baseline,'wrapped':events})
        http('/printer/bench_radio/clear',{'channel':0})
        state=channel_state(0,'absent')
        check('clear removes UID without affecting other channel',state['channels']['0']['uid'] is None and state['channels']['1']['uid']=='04112233445566')
        ws.close();ws=None
        http('/printer/restart',{})
        state=wait(lambda:(s if (s:=uid())['epoch']!=epoch and s['state']=='ready' else None))
        check('real Klipper RESTART creates new epoch',state['epoch']!=epoch)
        check('restart invalidates cached UID',all(c['uid'] is None for c in state['channels'].values()))
        stop_k(k);k=None
        # Only disposable copy changes; test safe failure on unknown driver version.
        driver.write_bytes(original_driver+b'\n# unsupported bench version\n')
        k=start_klippy();ready();state=uid()
        check('unsupported driver disables observer but Klipper stays ready',state['state']=='unavailable' and 'hash' in state['reason'],state)
        stop_k(k);k=None;driver.write_bytes(original_driver)
        check('rollback restores files',installer.rollback()=='rolled-back');installed=False
        check('original config restored byte-for-byte',config.read_bytes()==original_config)
        check('driver never changed by install/rollback',driver.read_bytes()==original_driver)
        check('module and include file removed',not (ROOT/'klipper/klippy/extras/tracker_uid.py').exists() and not (DATA/'config/tracker_uid.cfg').exists())
        k=start_klippy();ready()
        check('Klipper ready after rollback; no UID object','tracker_uid' not in objects())
        api_gone=False
        try:http('/printer/tracker_uid/status')
        except urllib.error.HTTPError as exc:api_gone=exc.code in (400,404)
        check('UID endpoint unavailable after rollback',api_gone)
        http('/printer/bench_radio/scan',{'channel':0})
        after=wait(lambda:(ev if (ev:=http('/printer/objects/query?bench_radio')['result']['status']['bench_radio']['stock_callbacks']) else None))
        check('stock scan works after rollback',after[0]==baseline[0],after)
        stop_k(k);k=None
        check('repeat rollback is harmless',installer.rollback()=='not-installed')
        completed=True
    finally:
        if ws:ws.close()
        stop(k);stop(m);(ROOT/'.klipper-running').unlink(missing_ok=True)
        driver.write_bytes(original_driver)
        if installed:installer.rollback()
        output=REPO/'output/uid-live-bench';output.mkdir(exist_ok=True)
        report={'completed':completed,'checks':RESULTS,'klipper_commit':subprocess.check_output(['git','-C',str(ROOT/'klipper'),'rev-parse','HEAD'],text=True).strip(),'moonraker_commit':subprocess.check_output(['git','-C',str(ROOT/'moonraker'),'rev-parse','HEAD'],text=True).strip(),'driver_sha256':hashlib.sha256(original_driver).hexdigest()}
        (output/'results.json').write_text(json.dumps(report,indent=2))
    print(f'{len(RESULTS)} integration checks passed',flush=True)
if __name__=='__main__':main()
