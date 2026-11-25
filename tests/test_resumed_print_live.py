"""Actual rc3 collectors against a local HTTP/WebSocket U1 simulator, no RFID."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import Request,urlopen
import pytest
from backup import create_backup
from storage import Store
from tracker_uid_session import Session
from tracker_uid_collectors import create_workers
from test_legacy_backup_restore import restore


def until(fn, timeout=20):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        value=fn()
        if value:return value
        time.sleep(.1)
    raise AssertionError('Local simulator condition timed out')


@pytest.mark.parametrize('scenario',[
    'counter-kept', 'counter-reset', 'counter-reset-unannounced', 'quick-standby',
])
def test_real_collectors_complete_manual_spool(tmp_path,scenario):
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}'
    simulator=Path(__file__).resolve().parents[1]/'dev/labs/uid_candidate_bench/simulator.py'
    app=None
    with (tmp_path/'simulator.log').open('w') as log:
        process=subprocess.Popen([sys.executable,str(simulator),str(port)],stdout=log,stderr=log)
        def http(path,body=None):
            req=Request(url+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
            with urlopen(req,timeout=3) as r:return json.load(r)['result']
        def ready():
            try:return http('/ready')
            except OSError:return False
        def event(action,**values):return http('/event',dict(action=action,**values))
        try:
            until(ready)
            old=Store(tmp_path/'old')
            def seed(data):
                data['printer'].update(host='127.0.0.1',port=port)
                data['spools']['manual']=dict(name='Manual PLA',material='PLA',remaining_g=500)
                data['slots']['1']='manual'
            old.update(seed)
            app=Session(tmp_path/'profile',allowed_urls=[url],worker_factory=create_workers);restore(app,create_backup(old,'1.3.3'))
            app.call('connect_printers',confirmed=True)
            def connected():
                app.call('refresh')
                return ready()['motion_clients'] and app.call('inspect')['manual_assignments'][0]['confirmed']
            until(connected)
            short_print=scenario=='quick-standby'
            reset_counter=scenario.startswith('counter-reset')
            omit_counter=scenario=='counter-reset-unannounced'
            event('start',filename='short.gcode' if short_print else 'tangled.gcode')
            until(lambda:app.call('inspect')['recovery_plans'])
            event('motion',stamp=1,length=69.452 if short_print else 100)
            if not short_print:
                event('error')
                until(lambda:app.call('inspect')['jobs'][0]['history_status']=='error')
                assert not app.call('inspect')['debits']
                event('resume',reset_counter=reset_counter,omit_counter=omit_counter)
                time.sleep(1)
                event('motion',stamp=2,length=200 if omit_counter else 50)
            event('complete')
            if short_print:
                time.sleep(.8)
                event('standby')
                assert not app.call('inspect')['debits']
            until(lambda:app.call('inspect')['debits'])
            state=app.call('inspect')
            # Total motion is 150mm. With a reset aggregate counter, preserve
            # original placement and use the verified full-file estimate.
            expected=207 if short_print else 18420 if reset_counter else 447
            assert sum(d['delta_mg'] for d in state['debits'])==expected,state
            assert state['spools'][0]['remaining_mg']==500000-expected
            key=state['jobs'][0]['job_key']
            assert state['jobs'][0]['state']=='completed'
            app.call('disconnect_printers',confirmed=True)
            app.call('connect_printers',confirmed=True)
            time.sleep(1.2)
            assert len(app.call('inspect')['debits'])==1
            out=Path('output/resumed-print-live');out.mkdir(parents=True,exist_ok=True)
            (out/scenario).with_suffix('.json').write_text(json.dumps(dict(success=True,real_printer_used=False,rfid_module=False,expected_mg=expected,job=state['jobs'][0],debits=state['debits']),indent=2))
            app.close();app=None
            app=Session(tmp_path/'profile',allowed_urls=[])
            assert app.call('history_detail',job_key=key)['accounted_mg']==expected
            assert len(app.call('inspect')['debits'])==1
        finally:
            if app:app.close()
            process.terminate();process.wait(timeout=10)
