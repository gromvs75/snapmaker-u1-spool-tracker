"""Full published shell against isolated fleets and a loopback Spoolman server."""
import copy
import json
from pathlib import Path
import socket
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

import pytest
from playwright.sync_api import sync_playwright

from tracker_uid_session import Session
from tracker_uid_gui import serve
from tracker_uid_sender import Sender
from test_uid_accounting import snapshot
from test_uid_motion_adapter import evidence
from test_accounting import setup_plan


class Fleet:
    def __init__(self,endpoints):
        self.value={p.printer_id:snapshot(p.printer_id,{}) for p in endpoints}
        for s in self.value.values():s.update(client_session='fixture',generation=1,epoch='fixture')
        self.started=False
    def start(self):self.started=True
    def stop(self):self.started=False
    def snapshot(self):return copy.deepcopy(self.value)


@pytest.fixture
def remote():
    value={'balance':500.,'writes':[],'fault':'','name':'Test PLA'}
    def item():return dict(id=42,remaining_weight=value['balance'],filament=dict(name=value['name'],material='PLA',color_hex='ff7f26'))
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,v):
            raw=json.dumps(v).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.path=='/api/v1/info':self.reply({'version':'0.27.1'})
            elif self.path.startswith('/api/v1/spool?'):self.reply([item()])
            elif self.path=='/api/v1/spool/42':self.reply(item())
            else:self.send_error(404)
        def do_PUT(self):
            assert self.path=='/api/v1/spool/42/use'
            data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));value['writes'].append(data)
            if value['fault']!='drop_before':value['balance']-=data['use_weight']
            if value['fault'] in ('drop_before','drop_after'):
                self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            self.reply(item())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever);thread.start()
    yield value,f'http://127.0.0.1:{server.server_port}'
    server.shutdown();thread.join();server.server_close()


def test_probe_allowlist_precedes_network_and_start_revision(tmp_path,monkeypatch):
    calls=[]
    class Probe:
        def __init__(self,url):calls.append(url)
        def status(self):return {'print_stats':{'state':'standby'}}
        def read(self,path):return {'objects':['tracker_uid']}
    monkeypatch.setattr('tracker_uid_collectors.ReadOnlyMoonraker',Probe)
    app=Session(tmp_path,allowed_urls=['http://127.0.0.1:19101'],fleet_factory=Fleet)
    try:
        with pytest.raises(ValueError):app.call('test_printer',url='http://192.0.2.9:7125')
        assert calls==[]
        assert app.call('test_printer',url='http://127.0.0.1:19101')['uid_available']
        old=app.call('settings')['revision']
        app.call('save_settings',values={'printers':[dict(id='a',name='A',url='http://127.0.0.1:19101')]},expected_revision=old)
        with pytest.raises(ValueError):app.call('connect_printers',confirmed=True,expected_revision=old)
        assert not app.connected
    finally:app.close()


def test_full_shell_connections_uid_spoolman_and_unknown_delivery(tmp_path,remote,monkeypatch):
    value,url=remote;probe=[]
    class Probe:
        def __init__(self,url):probe.append(url)
        def status(self):return {'print_stats':{'state':'standby'}}
        def read(self,path):
            if 'extruder' in path:return {'status':{('extruder'+str(i) if i else 'extruder'):dict(switch_count=20+i,last_maintenance_count=10) for i in range(4)}}
            return {'objects':['tracker_uid']}
    monkeypatch.setattr('tracker_uid_collectors.ReadOnlyMoonraker',Probe)
    app=Session(tmp_path/'profile',allowed_urls=['http://127.0.0.1:19101','http://127.0.0.1:19102'],fleet_factory=Fleet)
    sender=Sender(app,[url]);print_state={'value':'standby'}
    server=serve(app,app.fleet,status_reader=lambda pid:print_state['value'],sender=sender,app_info={'mode':'user','version':'2.0.0rc1'})
    thread=threading.Thread(target=server.serve_forever);thread.start();errors=[]
    screens=Path('output/full-133-services-ui');screens.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1360,'height':1080});page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.accept())
            page.goto(f'http://127.0.0.1:{server.server_port}/desktop');page.locator('#nav-settings').click();page.locator('[data-settings-section=printer]').click()
            for language,caption in [('en','Printer name'),('de','Druckername'),('uk','Назва принтера'),('es','Nombre de impresora'),('ru','Имя принтера')]:
                page.locator('#lang-picker').select_option(language)
                page.wait_for_function('(caption)=>document.getElementById("desktop-printer-name").parentElement.textContent===caption',arg=caption)
                assert app.call('settings')['values']['language']==language
            for index in (1,2):
                page.locator('#desktop-printer-add').click();page.locator('#desktop-printer-name').fill('Bench '+str(index));page.locator('#printer-host').fill('127.0.0.1');page.locator('#printer-port').fill(str(19100+index))
                with page.expect_response('**/api/settings') as response:page.locator('#printer-save').click()
                assert response.value.ok
                page.wait_for_function('(n)=>desktopFormData.printers.length===n',arg=index)
                assert not app.connected
            p1,p2=[p['id'] for p in app.call('settings')['values']['printers']]
            with page.expect_response('**/api/test_printer'):page.locator('#printer-test').click()
            page.wait_for_function("document.getElementById('desktop-connections-message').textContent.includes('UID')")
            assert probe==['http://127.0.0.1:19102']
            with page.expect_response('**/api/connections_start') as response:page.locator('#desktop-connections-toggle').click()
            assert response.value.ok
            page.wait_for_function('desktopFormData.connections.connected');assert app.connected
            with page.expect_response('**/api/desktop/printer/head-counters') as response:page.locator('#heads-read').click()
            assert response.value.ok and response.value.json()['heads'][3]['switches_since_maintenance']==13
            assert probe[-1]=='http://127.0.0.1:19102'
            page.screenshot(path=str(screens/'connections.png'),full_page=True)
            f=app.fleet.fleet
            f.value[p1]['channels']['0']=dict(state='present',uid='04112233',sequence=1)
            f.value[p2]['channels']['1']=dict(state='present',uid='04AABBCC',sequence=1)
            existing=app.call('create_spool',name='Existing PETG',remaining_g='123.456',details={'material':'PETG'})['spool_id']
            page.evaluate('loadData()');page.locator('#nav-spools').click();page.locator('#desktop-tags-open').click()
            page.locator('[data-uid="04112233"]').click();page.locator('#desktop-tag-name').fill('RFID PLA');page.locator('#desktop-tag-material').fill('PLA');page.locator('#desktop-tag-mass').fill('200.123');page.locator('#desktop-tag-ack').check()
            lost=[]
            def lose(route):
                if not lost:assert route.fetch().ok;lost.append(True);route.abort()
                else:route.continue_()
            page.route('**/api/tag_register',lose)
            with page.expect_event('requestfailed',predicate=lambda r:r.url.endswith('/tag_register')):page.locator('#desktop-tag-save').click()
            page.locator('#desktop-tag-save').click()
            page.wait_for_function("document.querySelectorAll('#desktop-tags-dialog [data-uid]').length===1")
            assert page.locator('#desktop-tags-dialog').is_visible()
            page.locator('#desktop-tag-mode').select_option('existing');page.locator('#desktop-tag-existing').select_option(existing);page.locator('#desktop-tag-ack').check()
            # Changing the observed generation must reject the already confirmed form.
            f.value[p2]['generation']=2
            with page.expect_response('**/api/tag_register') as response:page.locator('#desktop-tag-save').click()
            assert response.value.status==409
            assert next(s for s in app.call('inspect')['spools'] if s['spool_id']==existing)['uid'] is None
            page.locator('#desktop-tags-refresh').click();page.locator('#desktop-tag-mode').select_option('existing');page.locator('#desktop-tag-existing').select_option(existing);page.locator('#desktop-tag-ack').check()
            with page.expect_response('**/api/tag_register') as response:page.locator('#desktop-tag-save').click()
            assert response.value.ok
            page.wait_for_function("document.querySelectorAll('#desktop-tags-dialog [data-uid]').length===0")
            assert len(app.call('inspect')['spools'])==2
            saved=next(s for s in app.call('inspect')['spools'] if s['spool_id']==existing);assert saved['remaining_mg']==123456 and saved['uid']=='04AABBCC'
            page.screenshot(path=str(screens/'uid-queue-complete.png'),full_page=True);page.locator('#desktop-tags-close').click()
            page.locator('#nav-settings').click();page.locator('[data-settings-section=spoolman]').click();page.locator('[data-sm-tab=connection]').click()
            page.wait_for_function('desktopSpoolmanData!==null');page.locator('#sm-url').fill(url);page.locator('#sm-read').check();page.locator('#sm-send').check();page.locator('#sm-sole').check()
            with page.expect_response('**/api/desktop/spoolman/configure') as response:page.locator('#sm-save').click()
            assert response.value.ok
            page.wait_for_function("desktopSpoolmanData.state.mode==='send'")
            with page.expect_response('**/api/desktop/spoolman/refresh') as response:page.locator('#sm-refresh').click()
            assert response.value.ok
            page.locator('[data-sm-tab=spools]').click();page.locator('#sm-search').fill('test pla 42');page.locator('.sm-spool-row').click();page.locator('#sm-head').select_option('0')
            with page.expect_response('**/api/desktop/spoolman/attach') as response:page.locator('#sm-assign').click()
            assert response.value.ok
            page.wait_for_function('desktopSpoolmanData.linked.length===1')
            # Compare canonical names through the original 1.3.3 comparison dialog.
            value['name']='Updated PLA'
            page.locator('#sm-refresh-selected').click();page.wait_for_function("Object.values(desktopSpoolmanData.state.catalog)[0]?.name==='Updated PLA'")
            page.locator('#sm-inspector .sc-open').click();page.locator('[data-sc-filter=different]').click()
            page.locator('#sc-sync').click();page.wait_for_function("document.getElementById('sc-message').textContent.includes('Название обновлено')");page.locator('#sc-close').click()
            store,*_=setup_plan(tmp_path/'motion');e=evidence(store);e['start']=app.call('inventory_snapshot',p2);e['capture_id']='desktop-services';e['terminal_state']='completed';e['profile']['started_at']=1010.
            app.call('start',p2,filename='job.gcode',observed_at=1010.,capture_id=e['capture_id'],epoch=e['epoch'],start=e['start'],channels=['0']);app.call('terminal',p2,e)
            history=[dict(job_id='desktop-services',start_time=1010.,filename='job.gcode',status='completed')];app.call('history',p2,history)
            assert len(app.call('delivery_list'))==1
            page.evaluate('refreshSpoolmanAfterRestore()');page.locator('[data-sm-tab=usage]').click();page.locator('#sm-queue button').click()
            page.locator('#desktop-delivery-note').fill('Reviewed local ledger and server');page.locator('#desktop-delivery-ack').check();page.locator('#desktop-delivery-approve').click()
            page.wait_for_function("!document.getElementById('desktop-delivery-dialog').open")
            page.locator('#sm-queue button').click();value['fault']='drop_after';page.locator('#desktop-delivery-ack').check();page.locator('#desktop-delivery-send').click()
            page.wait_for_function("document.getElementById('desktop-delivery-not_applied')!==null")
            assert len(value['writes'])==1 and app.call('delivery_list')[0]['state']=='uncertain'
            assert sender.send_one()=='blocked' and len(value['writes'])==1
            page.locator('#desktop-delivery-review').click();page.wait_for_function("document.getElementById('desktop-delivery-dialog').textContent.includes('499,7')")
            page.screenshot(path=str(screens/'uncertain-spoolman.png'),full_page=True)
            page.locator('#desktop-delivery-note').fill('PUT was applied on fixture, verified audit');page.locator('#desktop-delivery-ack').check();page.locator('#desktop-delivery-applied').click()
            page.wait_for_function("!document.getElementById('desktop-delivery-dialog').open")
            before=app.call('inspect')['debits'];app.call('history',p2,history);assert app.call('inspect')['debits']==before
            assert sender.send_one()=='idle' and len(value['writes'])==1
            assert app.call('delivery_list')[0]['state']=='sent'
            page.locator('[data-settings-section=printer]').click();page.locator('#desktop-connections-toggle').click();page.wait_for_function('!desktopFormData.connections.connected')
            assert not errors,errors
            browser.close()
        package=app.call('backup_package');checked=app.call('validate_backup',package=package);app.call('restore_backup',package=package,expected_revision=checked['current_revision'],confirmed=True)
        assert app.call('inspect')['debits']==before and sender.send_one()=='idle'
    finally:
        server.shutdown();thread.join();server.server_close();sender.stop();app.close()
    app=Session(tmp_path/'profile',allowed_urls=[],fleet_factory=Fleet)
    try:
        assert not app.connected and len(app.call('settings')['values']['printers'])==2
        assert app.call('inspect')['debits']==before
        assert app.call('delivery_list')[0]['state']=='sent'
    finally:app.close()
