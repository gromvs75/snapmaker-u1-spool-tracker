import json
import sqlite3
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect
from tracker_dashboard import telemetry
from tracker_uid_collectors import ReadOnlyMoonraker
from tracker_uid_session import Session
from tracker_uid_gui import serve
from test_desktop_services import Fleet
from test_printer_monitor import printer


def status(state='printing', progress=.62, elapsed=11880):
    return dict(print_stats=dict(state=state,filename='organizer.gcode',print_duration=elapsed,
                info=dict(current_layer=142,total_layer=230)),display_status=dict(progress=progress))


def test_estimate_is_display_only_and_pause_clears_finish():
    got=telemetry(status())
    assert got['progress']==.62 and got['elapsed_seconds']==11880
    assert got['remaining_seconds']==7281 and got['current_layer']==142
    for state in ('paused','cancelled','error','complete','standby'):
        assert telemetry(status(state))['remaining_seconds'] is None
    assert telemetry(status('complete'))['progress']==1
    assert telemetry(status('standby'))['progress'] is None
    assert telemetry(status(elapsed=0))['remaining_seconds'] is None


@pytest.mark.parametrize('bad',[None,True,-1,1.1,float('nan'),float('inf'),'0.62'])
def test_missing_or_invalid_progress_is_never_zero(bad):
    result=telemetry(status(progress=bad))
    assert result['progress'] is None and result['remaining_seconds'] is None


def test_optional_telemetry_and_new_job_do_not_reuse_previous_values():
    s=status(progress=None);s['virtual_sdcard']={'progress':.5}
    assert telemetry(s)['progress']==.5
    assert telemetry(dict(print_stats=dict(state='printing',filename='next.gcode')))['remaining_seconds'] is None
    assert telemetry(status(progress=0))['progress']==0
    assert telemetry(status(progress=0))['remaining_seconds'] is None
    for bad in (None,True,-1,float('inf')):
        assert telemetry(status(elapsed=bad))['elapsed_seconds'] is None


class Monitor:
    """Only actual read-only HTTP display polling; no motion or print commands."""
    def __init__(self,owner,pid,url):
        self.owner,self.pid,self.client=owner,pid,ReadOnlyMoonraker(url)
        self.stop_event=threading.Event();self.thread=threading.Thread(target=self.run)
    def start(self):self.thread.start()
    def run(self):
        while not self.stop_event.is_set():
            try:self.owner.call('monitor_status',self.pid,self.client.monitor_status())
            except Exception:self.owner.call('monitor_error',self.pid)
            self.stop_event.wait(.2)
    def stop(self):self.stop_event.set();self.thread.join(5)


def test_dashboard_live_http_states_cards_languages_and_layout(tmp_path):
    out=Path('output/dashboard-bench');out.mkdir(parents=True,exist_ok=True)
    with printer('printing','desk-organizer.gcode') as (remote,url):
        remote.update(stats=dict(print_duration=11880,info=dict(current_layer=142,total_layer=230)),
                      extra=dict(display_status=dict(progress=.62)),extruder='extruder1')
        # Seed only a disposable SQLite fixture, then exercise its real read model.
        s=Session(tmp_path/'profile',fleet_factory=Fleet,allowed_urls=[url])
        s.call('save_settings',values=dict(language='ru',printers=[dict(id='a',name='U1 · стенд',url=url)]),expected_revision=s.call('settings')['revision'])
        s.call('connect_printers',confirmed=True)
        ids=[]
        for ch,name,material,color,mass in [(0,'Bambu Lab · Basic','PLA','#ec343b',500),(1,'Generic · Basic','PETG','#f4f4f0',900),(3,'Generic · Matte','PLA','#191b20',85)]:
            ids.append(s.call('create_spool',name,mass,details=dict(material=material,color=color),assignment=dict(printer_id='a',channel=str(ch),expected_version='',confirmed=True))['spool_id'])
        s.close()
        with sqlite3.connect(tmp_path/'profile/tracker.sqlite') as db:
            for i,sid in enumerate(ids):
                details=json.loads(db.execute('SELECT payload FROM spool_details WHERE spool_id=?',(sid,)).fetchone()[0])
                details['nominal_weight_g']=1000
                db.execute('UPDATE spool_details SET payload=? WHERE spool_id=?',(json.dumps(details),sid))
                if i<2:
                    uid=['04112233','04AABBCC'][i]
                    db.execute('UPDATE uid_spools SET uid=? WHERE spool_id=?',(uid,sid))
                    db.execute('DELETE FROM manual_assignments WHERE spool_id=?',(sid,))
                    db.execute('INSERT INTO uid_remote_links VALUES(?,?,?)',(sid,'http://127.0.0.1:19998',41+i))
            db.commit()
        def workers(owner,p,directory):
            return Monitor(owner,p['id'],p['url'])
        s=Session(tmp_path/'profile',fleet_factory=Fleet,worker_factory=workers,allowed_urls=[url])
        s.call('connect_printers',confirmed=True)
        fleet=s.fleet.fleet.value['a']
        for ch,uid in [('0','04112233'),('1','04AABBCC'),('2','045566778899AA')]:
            fleet['channels'][ch]=dict(state='present',uid=uid)
        from dev.klipper.tracker_uid import decode_json_tag
        fleet['channels']['2']['tag']=decode_json_tag(bytes.fromhex('045566778899AA'),json.dumps(dict(brand='Generic',material='PLA',color='695AFF')).encode())
        server=serve(s,s.fleet);thread=threading.Thread(target=server.serve_forever);thread.start()
        errors=[]
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch();page=browser.new_page(viewport=dict(width=1280,height=1050))
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}/desktop')
                expect(page.locator('.dash-percent')).to_have_text('62%')
                expect(page.locator('#dashboard-elapsed')).to_have_text('3 ч 18 мин')
                expect(page.locator('#dashboard-remaining')).to_have_text('2 ч 2 мин')
                card=page.locator('.overview-card')
                toggle=card.get_by_role('button',name='Детали')
                details=page.locator('#dashboard-print-details')
                expect(details).to_be_hidden()
                expect(toggle).to_have_attribute('aria-expanded','false')
                expect(card.locator('.overview-heading #dashboard-remaining')).to_be_visible()
                assert card.bounding_box()['height'] < 120
                toggle.click()
                expect(details).to_be_visible()
                expect(toggle).to_have_attribute('aria-expanded','true')
                expect(details.locator('#dashboard-elapsed')).to_be_visible()
                expect(details.locator('.dash-layer')).to_have_text('Слой 142 / 230')
                toggle.click()
                expect(details).to_be_hidden()
                heads=page.locator('#sidebar-slots .sidebar-slot')
                expect(heads).to_have_count(4)
                expect(heads.nth(1)).to_have_class('sidebar-slot selected-head')
                expect(heads.nth(0)).to_contain_text('RFID · распознана')
                expect(heads.nth(0)).to_contain_text('Spoolman #41 · привязана')
                expect(heads.nth(2)).to_contain_text('Остаток неизвестен')
                expect(heads.nth(2)).to_contain_text('RFID · подтвердите метку')
                assert heads.nth(2).locator('[role=meter]').count()==0
                assert heads.nth(3).locator('.is-low').count()==1
                sources=page.locator('#dashboard-sources')
                assert sources.bounding_box()['y'] < heads.first.bounding_box()['y']
                expect(sources.locator('details')).to_have_count(4)
                expect(sources.locator('[data-source=connection]')).to_contain_text('есть связь')
                expect(sources.locator('[data-source=head] .dash-source-badge')).to_have_text('T1')
                expect(sources.locator('[data-source=spoolman]')).to_contain_text('не настроен')
                sources.locator('[data-source=rfid] summary').click()
                page.wait_for_timeout(1200)
                assert sources.locator('[data-source=rfid]').get_attribute('open') is not None
                sources.locator('[data-source=rfid] summary').click()
                page.screenshot(path=str(out/'printing.png'),full_page=True)
                for lang in ('en','de','uk','es','ru'):
                    page.locator('#lang-picker').select_option(lang)
                    page.wait_for_function('(lang)=>currentLang===lang',arg=lang)
                    expect(page.locator('.dash-percent')).to_have_text('62%')
                    for width in (1280,960,700,390):
                        page.set_viewport_size(dict(width=width,height=1050))
                        assert page.locator('#view-overview').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
                        for i in range(4):assert heads.nth(i).evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
                page.screenshot(path=str(out/'narrow.png'),full_page=True);page.set_viewport_size(dict(width=1280,height=1050))
                remote['state']='paused'
                expect(page.locator('#overview-connection')).to_have_text('Пауза')
                expect(page.locator('#dashboard-remaining')).to_have_text('—')
                expect(page.locator('#dashboard-finish')).to_have_text('—')
                expect(page.locator('.dash-active')).to_have_count(0)
                page.screenshot(path=str(out/'paused.png'),full_page=True)
                remote['offline']=True
                expect(page.locator('#overview-connection')).to_have_text('Нет связи с принтером')
                expect(page.locator('.dash-percent')).to_have_text('—')
                expect(heads.nth(0)).to_contain_text('RFID · нет связи')
                expect(sources.locator('[data-source=connection] .dash-source-badge')).to_have_text('нет связи')
                expect(sources.locator('[data-source=head] .dash-source-badge')).to_have_text('неизвестно')
                assert page.locator('#dashboard-progress').get_attribute('value') is None
                remote.update(offline=False,state='complete')
                expect(page.locator('.dash-percent')).to_have_text('100%')
                for st in ('cancelled','error','standby'):
                    remote['state']=st
                    page.wait_for_function('(st)=>document.querySelector(".overview-card").dataset.state===st',arg=st)
                    expect(page.locator('#dashboard-finish')).to_have_text('—')
                remote.update(state='printing',extra={},stats={})
                expect(page.locator('#overview-connection')).to_have_text('Печать идёт')
                expect(page.locator('.dash-percent')).to_have_text('—')
                expect(page.locator('#dashboard-elapsed')).to_have_text('—')
                fleet['state']='module_missing'
                expect(heads.nth(3)).to_contain_text('RFID · без модуля')
                expect(sources.locator('[data-source=rfid] .dash-source-badge')).to_have_text('нет модуля')
                page.screenshot(path=str(out/'unknown.png'),full_page=True)
                heads.nth(3).locator('.dash-status-button').first.click()
                expect(page.locator('#desktop-tags-dialog')).to_be_visible()
                page.locator('#desktop-tags-dialog .gd-close').click()
                heads.nth(3).locator('.dash-status-button').nth(1).click()
                expect(page.locator('#spoolman-panel')).to_be_visible()
                assert not errors
                browser.close()
            assert not s.call('inspect')['debits'] and not s.call('delivery_list')
            balances={x['spool_id']:x['remaining_mg'] for x in s.call('inspect')['spools']}
            assert [balances[sid] for sid in ids]==[500000,900000,85000]
            assert all(path.startswith('/printer/objects/query?') for path in remote['requests'])
            (out/'VERIFIED.json').write_text(json.dumps(dict(success=True,real_printer_used=False,
                languages=['ru','en','de','uk','es'],widths=[1280,960,700,390],
                states=['printing','paused','offline','complete','cancelled','error','standby','unknown'],
                balances_unchanged=True,debits=0,printer_writes=0,native_windows_gui_tested=False),indent=2))
        finally:server.shutdown();thread.join();server.server_close();s.close()


def test_spoolman_source_is_cached_evidence_not_inferred_connection(tmp_path,monkeypatch):
    s=Session(tmp_path/'sources',allowed_urls=[])
    url='http://127.0.0.1:19998'
    def source():return s.call('desktop_snapshot')['data_sources']['spoolman']
    def settings(**values):s.call('save_settings',values=values,expected_revision=s.call('settings')['revision'])
    try:
        assert source()['state']=='unconfigured'
        settings(spoolman_url=url,spoolman_mode='read')
        assert source()['state']=='unchecked'
        s.call('cache_catalog',url,{})
        assert source()['state']=='current'
        assert not s.call('desktop_snapshot')['monitor']['connected']
        checked=source()['checked_at']
        with monkeypatch.context() as patch:
            patch.setattr('tracker_uid_library.time.time',lambda:checked+301)
            assert source()['state']=='stale'
        s.call('cache_catalog',url,None)
        assert source()['state']=='unavailable'
        settings(spoolman_mode='off')
        assert source()['state']=='disabled'
        assert not s.call('inspect')['debits']
    finally:s.close()
