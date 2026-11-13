import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'dev/labs/uid_bridge_bench'))
sys.path.insert(0,str(ROOT/'dev/klipper'))
import tracker_uid as module
import test_memory_bridge as harness
from test_memory_bridge import stock
from install import Installer,MARKER,BLOCK,MODULE


class Printer:
    def __init__(self,reader):
        self.events={};self.queue=[];self.endpoints={};self.order=[]
        self.objects={'fm175xx_reader':reader,'webhooks':self}
    def get_reactor(self):return self
    def register_async_callback(self,fn):self.queue.append(fn)
    def lookup_object(self,name,default=None):return self.objects.get(name,default)
    def register_event_handler(self,event,fn):self.events.setdefault(event,[]).append(fn)
    def register_endpoint(self,name,fn):self.endpoints[name]=fn
    def send_event(self,event):
        for fn in self.events.get(event,[]):fn()
    def drain(self):
        while self.queue:self.queue.pop(0)(0)


class Config:
    def __init__(self,printer,enabled=True):self.printer=printer;self.enabled=enabled
    def get_printer(self):return self.printer
    def getboolean(self,name,default):return self.enabled
    def getfloat(self,name,default,**kw):return default


def setup(p,enabled=True):
    setattr(p.reader,module.P+'card_info_deal_cb',None)
    printer=Printer(p.reader)
    # Simulate stock ready handlers registered before our extra (the actual order).
    printer.register_event_handler('klippy:ready',lambda:printer.order.append('reader thread starts'))
    printer.register_event_handler('klippy:ready',lambda:p.reader.register_cb_2_card_info_deal(p.callback))
    extra=module.load_config(Config(printer,enabled))
    printer.objects['tracker_uid']=extra
    return printer,extra


def test_connect_precedes_ready_and_registers_late_stock_callback(stock):
    printer,extra=setup(stock)
    assert extra.get_status()['state']=='waiting'
    printer.send_event('klippy:connect')
    assert extra.get_status()['state']=='attached',extra.reason
    wrapper=getattr(stock.reader,module.P+'card_info_deal_cb')
    assert callable(wrapper) and not printer.order
    printer.send_event('klippy:ready')
    assert extra.get_status()['state']=='ready'
    assert getattr(stock.reader,module.P+'card_info_deal_cb') is wrapper
    wrapper(2,stock.fm.FM175XX_CARD_INFO_CLEAR,0,None,None)
    printer.drain()
    assert stock.events[-1][0]==2
    assert extra.get_status()['channels']['2']['state']=='absent'
    answer=[]
    printer.endpoints['tracker_uid/status'](types.SimpleNamespace(send=answer.append))
    assert answer[0]['channels']['2']['state']=='absent'
    assert answer[0]['epoch']==printer.objects['tracker_uid'].get_status()['epoch']
    assert answer[0]['schema_version']==1


@pytest.mark.parametrize('event',['klippy:shutdown','klippy:disconnect','klippy:connect_error','gcode:request_restart'])
def test_shutdown_invalidates_queue_but_leaves_stock_callback_live(stock,event):
    printer,extra=setup(stock)
    printer.send_event('klippy:connect');printer.send_event('klippy:ready')
    extra.bridge._publish(0,'present','04010203')
    original_wrapper=getattr(stock.reader,module.P+'card_info_deal_cb')
    printer.send_event(event);printer.drain()
    assert extra.get_status()['state']=='stopped'
    assert extra.get_status()['channels']['0']['uid'] is None
    assert getattr(stock.reader,module.P+'card_info_deal_cb') is original_wrapper
    original_wrapper(0,stock.fm.FM175XX_CARD_INFO_CLEAR,0,None,None)
    assert stock.events[-1][0]==0


def test_disabled_module_does_not_hook(stock):
    printer,extra=setup(stock,False)
    printer.send_event('klippy:connect');printer.send_event('klippy:ready')
    assert extra.state=='disabled'
    assert not hasattr(stock.reader,'_tracker_uid_owner')


def test_existing_hook_rejected_without_stopping_printer(stock):
    setattr(stock.reader,module.P+'reader_a_activate',lambda:0)
    printer,extra=setup(stock)
    printer.send_event('klippy:connect');printer.send_event('klippy:ready')
    assert extra.state=='unavailable' and 'existing hook' in extra.reason
    assert not hasattr(stock.reader,'_tracker_uid_owner')
    assert printer.order==['reader thread starts']


def test_modified_class_code_rejected(stock,monkeypatch):
    monkeypatch.setattr(type(stock.reader),module.P+'reader_a_activate',lambda self:0)
    printer,extra=setup(stock)
    printer.send_event('klippy:connect')
    assert extra.state=='unavailable' and 'differs' in extra.reason


def test_unknown_driver_hash_rejected(stock,monkeypatch):
    monkeypatch.setattr(module,'SUPPORTED_DRIVERS',{})
    printer,extra=setup(stock)
    printer.send_event('klippy:connect')
    assert extra.state=='unavailable' and 'hash' in extra.reason
    assert not hasattr(stock.reader,'_tracker_uid_owner')


def test_stale_uid_not_returned_as_current(stock,monkeypatch):
    printer,extra=setup(stock)
    printer.send_event('klippy:connect')
    monkeypatch.setattr(module.time,'monotonic',lambda:100.)
    extra.bridge._publish(0,'present','04010203');printer.drain()
    monkeypatch.setattr(module.time,'monotonic',lambda:401.)
    state=extra.get_status()['channels']['0']
    assert state['state']=='stale' and state['uid'] is None and state['age_seconds']==301


@pytest.mark.parametrize('kind,uid',[('mifare',[4,1,2,3]),('ntag',[4,1,2,3,4,5,6]),('official',[4,1,2,3])])
def test_deployable_core_runs_stock_scan(stock,monkeypatch,kind,uid):
    monkeypatch.setattr(harness,'MemoryUidBridge',module.MemoryUidBridge)
    bridge,_=harness.run(stock,{2:(kind,uid)})
    assert bridge.get_status()['channels']['2']['uid']==bytes(uid).hex().upper()
    bridge.detach()


@pytest.fixture
def filesystem(tmp_path):
    root=tmp_path/'printer';root.mkdir()
    (root/'.tracker-uid-simulator.json').write_text(json.dumps(MARKER))
    extras=root/'klipper/klippy/extras';extras.mkdir(parents=True)
    cfg=root/'printer_data/config';cfg.mkdir(parents=True)
    (cfg/'printer.cfg').write_bytes(b'# user settings\n[printer]\nkinematics: cartesian\n')
    (cfg/'printer.cfg').chmod(0o640)
    source=harness.SOURCES/'base/tests_support/snapmaker_source/2.0.0.205/klippy/extras/fm175xx_reader.py'
    (extras/'fm175xx_reader.py').write_bytes(source.read_bytes())
    return root


def test_install_idempotence_rollback_preserves_config_and_driver(filesystem):
    root=filesystem;installer=Installer(root)
    cfg=root/'printer_data/config/printer.cfg';before=cfg.read_bytes()
    driver=root/'klipper/klippy/extras/fm175xx_reader.py';original=driver.read_bytes()
    assert installer.install()=='installed'
    assert installer.install()=='already-installed'
    assert cfg.read_bytes()==before+BLOCK
    assert cfg.stat().st_mode & 0o777==0o640
    assert installer.rollback()=='rolled-back'
    assert installer.rollback()=='not-installed'
    assert cfg.read_bytes()==before and driver.read_bytes()==original
    assert not (root/'klipper/klippy/extras/tracker_uid.py').exists()
    assert (root/'.tracker-uid-last-rollback.json').exists()


@pytest.mark.parametrize('step',[1,2,3])
def test_interrupted_install_recovers(filesystem,step):
    installer=Installer(filesystem);cfg=filesystem/'printer_data/config/printer.cfg';before=cfg.read_bytes()
    with pytest.raises(RuntimeError):installer.install(fail_after=step)
    with pytest.raises(ValueError,match='Pending'):installer.install()
    installer.rollback()
    assert cfg.read_bytes()==before
    assert installer.install()=='installed'


def test_rollback_preserves_later_user_config_edit(filesystem):
    installer=Installer(filesystem);cfg=filesystem/'printer_data/config/printer.cfg';before=cfg.read_bytes()
    installer.install();cfg.write_bytes(cfg.read_bytes()+b'# later user note\n')
    installer.rollback()
    assert cfg.read_bytes()==before+b'# later user note\n'


def test_rollback_refuses_changed_module_without_touching_config(filesystem):
    installer=Installer(filesystem);installer.install()
    cfg=filesystem/'printer_data/config/printer.cfg';before=cfg.read_bytes()
    (filesystem/'klipper/klippy/extras/tracker_uid.py').write_text('# edited by someone else')
    with pytest.raises(ValueError,match='Owned file changed'):installer.rollback()
    assert cfg.read_bytes()==before


def test_running_klipper_blocks_both_operations(filesystem):
    installer=Installer(filesystem)
    (filesystem/'.klipper-running').touch()
    with pytest.raises(ValueError,match='Stop'):installer.install()
    with pytest.raises(ValueError,match='Stop'):installer.rollback()


def test_unmarked_root_rejected(tmp_path):
    with pytest.raises((ValueError,FileNotFoundError)):Installer(tmp_path)


def test_symlink_target_rejected(filesystem,tmp_path):
    module_path=filesystem/'klipper/klippy/extras/tracker_uid.py'
    elsewhere=tmp_path/'unrelated';elsewhere.write_text('keep')
    module_path.symlink_to(elsewhere)
    with pytest.raises(ValueError,match='Symlink'):Installer(filesystem).install()
    assert elsewhere.read_text()=='keep'


def test_config_conflict_refused(filesystem):
    cfg=filesystem/'printer_data/config/printer.cfg';cfg.write_text('[tracker_uid]\n')
    with pytest.raises(ValueError,match='Existing'):Installer(filesystem).install()
    assert not (filesystem/'klipper/klippy/extras/tracker_uid.py').exists()


def test_slow_reactor_does_not_make_old_scan_fresh(stock,monkeypatch):
    printer,extra=setup(stock);printer.send_event('klippy:connect')
    monkeypatch.setattr(module.time,'monotonic',lambda:100.)
    extra.bridge._publish(0,'present','04010203')
    monkeypatch.setattr(module.time,'monotonic',lambda:500.)
    printer.drain()
    assert extra.get_status()['channels']['0']['state']=='stale'


def test_runtime_hook_replacement_invalidates_module_without_overwrite(stock):
    printer,extra=setup(stock);printer.send_event('klippy:connect')
    foreign=lambda:0
    setattr(stock.reader,module.P+'reader_a_activate',foreign)
    assert extra.get_status()['state']=='unavailable'
    assert getattr(stock.reader,module.P+'reader_a_activate') is foreign
    assert not extra.bridge.active


def test_missing_reader_leaves_manual_mode_possible():
    printer=Printer(None);extra=module.load_config(Config(printer))
    printer.send_event('klippy:connect');printer.send_event('klippy:ready')
    assert extra.state=='unavailable' and extra.reason=='RFID reader unavailable'


def test_installed_module_loads_from_simulated_extras(filesystem,stock):
    installer=Installer(filesystem);installer.install()
    path=filesystem/'klipper/klippy/extras/tracker_uid.py'
    spec=importlib.util.spec_from_file_location('installed_tracker_uid_bench',path)
    deployed=importlib.util.module_from_spec(spec);spec.loader.exec_module(deployed)
    setattr(stock.reader,module.P+'card_info_deal_cb',None)
    printer=Printer(stock.reader)
    extra=deployed.load_config(Config(printer))
    printer.send_event('klippy:connect');printer.send_event('klippy:ready')
    assert extra.state=='ready',extra.reason
    printer.send_event('klippy:shutdown')
    installer.rollback()
    assert not path.exists()
