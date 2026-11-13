"""Real upstream software pipeline, simulated radio/SPI results. No printer access."""
import copy
import json
import logging
import subprocess
import sys
import types
from pathlib import Path

import pytest
from bridge import UidBridge

ROOT = Path(__file__).resolve().parents[3]
SOURCES = ROOT / 'output/uid-bridge-bench/sources'
TEMPLATE = {'CARD_UID': 0, 'OFFICIAL': False, 'VENDOR': 'NONE', 'MAIN_TYPE': 'NONE'}


def load(name, path):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(path.read_text(), str(path), 'exec'), module.__dict__)
    if '.' in name:
        setattr(sys.modules[name.rsplit('.', 1)[0]], name.rsplit('.', 1)[1], module)
    return module


@pytest.fixture(params=['1.3.0.168', '2.0.0.205', '2.1.0.157'])
def pipeline(request, tmp_path, monkeypatch):
    version = request.param
    base = SOURCES / 'base'
    target = tmp_path/'klippy/extras'
    target.mkdir(parents=True)
    for name in ('fm175xx_reader', 'filament_detect'):
        stock = base/'tests_support/snapmaker_source'/version/'klippy/extras'/f'{name}.py'
        (target/f'{name}.py').write_text(stock.read_text())
        variant = 'v1.3' if version.startswith('1.3') else ('v2.1' if version.startswith('2.1') else 'v1.4.246')
        patch = base/f'u1-base-{name.replace("_", "-")}'/'files/patches'/f'{name}-{variant}.patch'
        subprocess.run(['patch','-f','-F0','-p1','-i',str(patch)],cwd=tmp_path,check=True,capture_output=True)
    # No driver constructor is invoked: GPIO/SPI entry points cannot access hardware.
    for name in ('spidev', 'gpiod'):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    pkg = types.ModuleType('uid_bench_extras'); pkg.__path__ = []
    monkeypatch.setitem(sys.modules, pkg.__name__, pkg)
    proto = types.ModuleType(pkg.__name__+'.filament_protocol')
    proto.FILAMENT_INFO_STRUCT = TEMPLATE
    proto.FILAMENT_PROTO_OK = 0; proto.FILAMENT_PROTO_ERR = -1
    proto.m1_proto_data_parse = lambda data: (0, dict(TEMPLATE, CARD_UID=[4,1,2,3], OFFICIAL=True))
    monkeypatch.setitem(sys.modules, proto.__name__, proto); pkg.filament_protocol = proto
    pkg.filament_feed = types.ModuleType(pkg.__name__+'.filament_feed')
    fm = load(pkg.__name__+'.fm175xx_reader',target/'fm175xx_reader.py')
    fd = load(pkg.__name__+'.filament_detect',target/'filament_detect.py')
    support = SOURCES/'rfid/rfid-ntag/files/klipper/klippy/extras/rfid-support'
    for name, path in [('mifare_classic',support/'chips/mifare_classic.py'),
                       ('ndef_parser',support/'chips/ndef_parser.py'),
                       ('ntag_reader',support/'chips/ntag_reader.py'),
                       ('payload_mapper',support/'payload_mapper.py'),
                       ('openspool_mapper',support/'tags/openspool_mapper.py'),
                       ('rfid_ntag',support/'rfid_ntag.py')]:
        load(pkg.__name__+'.'+name,path)
    logger = logging.getLogger('bespok3d')
    monkeypatch.setattr(logger, 'handlers', [logging.NullHandler()])
    hub_module = load(pkg.__name__+'.bespok3d_rfid',SOURCES/'rfid/rfid-ntag/files/rfid-base/extras/bespok3d_rfid.py')
    monkeypatch.setattr(hub_module,'RFID_DATA_FILE',str(tmp_path/'rfid_data.json'))
    reader = fm.FM175XXReader.__new__(fm.FM175XXReader)
    reader._first_scan_fail_fast = False
    reader._card_type_handlers = {}; reader._card_claim_handlers = []
    reader._FM175XXReader__picc_a = fm.Fm175xxPiccMetaData()
    detector = fd.FilamentDetector.__new__(fd.FilamentDetector)
    detector._config = {}; detector._channel_nums = 4; detector._state = [0]*4
    detector._filament_info = [dict(TEMPLATE) for _ in range(4)]
    detector._card_protocol_parsers = {}; detector._self_test_success_cnt = 0
    detector._notify_data_update_cb = []
    detector.reactor = types.SimpleNamespace(register_async_callback=lambda fn: fn(0))
    objects = {'fm175xx_reader':reader,'filament_detect':detector}
    printer = types.SimpleNamespace(lookup_object=lambda n, default=None: objects.get(n,default),
                                   register_event_handler=lambda *args: None)
    config = types.SimpleNamespace(get_printer=lambda: printer)
    hub = hub_module.Bespok3dRfid(config); objects['bespok3d_rfid'] = hub
    hub._handle_ready()
    ntag = pkg.rfid_ntag.RfidNtag(config)
    ntag.register_protocol_mapper(pkg.openspool_mapper.OpenSpoolMapper())
    hub.register_hw_reader(pkg.ntag_reader.NtagReader()); hub.register_payload_parser(ntag)
    bridge = UidBridge()
    bridge.enable_mifare_fallback(reader)
    def callback(ch, op, result, kind, data):
        bridge.observe(ch,op,result,kind,data,read_op=fm.FM175XX_CARD_INFO_READ,
                       clear_op=fm.FM175XX_CARD_INFO_CLEAR,ok=fm.FM175XX_OK,
                       mifare_uid_type=0x88,ntag_type=pkg.ntag_reader.NTAG_CARD_TYPE)
        detector._fm175xx_card_info_deal_callback(ch,op,result,kind,data)
    return types.SimpleNamespace(fm=fm, reader=reader, detector=detector, bridge=bridge,
                                 callback=callback, pkg=pkg, version=version)


def pages(uid):
    b = bytearray(180)
    b[:3] = bytes(uid[:3]); b[3] = 0x88 ^ uid[0] ^ uid[1] ^ uid[2]
    b[4:8] = bytes(uid[3:]); b[8] = uid[3] ^ uid[4] ^ uid[5] ^ uid[6]
    b[12:16] = bytes([0xE1,0x10,0x12,0])
    b[16:19] = bytes([3,0,0xFE])  # empty NDEF, not an OpenSpool payload
    return bytes(b)


def scan(p, cards, before_run=None):
    """Run the actual patched driver's background loop for one four-channel sweep.

    Only low-level radio operations and waiting are simulated; selection, retries,
    failed authentication -> fallback and callback dispatch are upstream code.
    """
    r,fm = p.reader,p.fm
    class Stop:
        stopped = False
        def is_set(self): return self.stopped
        def wait(self, seconds):
            if seconds == .2: self.stopped = True
            return self.stopped
    def private(name,value): setattr(r,'_FM175XXReader__'+name,value)
    stop=Stop(); private('stop_event',stop)
    private('need_to_shutdown',False)
    fm.time = types.SimpleNamespace(sleep=lambda seconds: private('need_to_shutdown',True) if seconds==.2 else None)
    private('self_test_stage',fm.FM175XX_SELF_TEST_STAGE_STOP); private('card_info_read_flag',sum(1<<ch for ch in cards))
    private('card_info_clear_flag',0); private('card_info_deal_cb',p.callback)
    active={'ch':0}
    private('select_fm175xx_obj',lambda ch: None)
    private('select_channel',lambda ch: active.update(ch=ch))
    private('hard_reset',lambda:None); private('register_read',lambda reg:0)
    private('reader_a_init',lambda:None); private('set_carrier_wave',lambda v:None)
    private('reader_a_halt',lambda:0)
    def activate():
        kind,data=cards[active['ch']]
        if kind=='absent':return fm.FM175XX_ERR
        picc=r._FM175XXReader__picc_a
        picc.SAK[0]=4 if kind=='ntag' else 8
        picc.UID[:4]=([0x88,*data[:3]] if kind=='ntag' else data[:4])
        return 0
    private('reader_a_activate',activate)
    private('reader_a_m1_read_all_data',lambda *args:types.SimpleNamespace(err_code=fm.FM175XX_CARD_AUTH_ERR,out_param=None))
    def read_pages(start,count):
        raw=cards[active['ch']][1]; chunk=raw[start*4:(start+count)*4]
        return (0,list(chunk)) if len(chunk)==count*4 else (fm.FM175XX_CARD_READ_ERR,None)
    r.read_nfc_type2_pages=read_pages
    if before_run is not None: before_run()
    r._FM175XXReader__bg_thread()


@pytest.mark.parametrize('channel',range(4))
def test_unknown_mifare_uid_and_channel(pipeline, channel):
    p=pipeline; uid=[4,0,0xA1,channel+1]
    scan(p,{channel:('mifare',uid)})
    assert p.detector.get_status()['info'][channel]['CARD_UID']==uid
    assert p.bridge.get_status()['channels'][str(channel)]['uid']==bytes(uid).hex().upper()
    assert p.detector.get_status()['info'][channel]['MAIN_TYPE']=='NONE'


@pytest.mark.parametrize('channel',range(4))
def test_blank_ntag_lost_by_upstream_decoder_retained_by_bridge(pipeline,channel):
    p=pipeline; uid=[4,0,0xA1,0xB2,0xC3,0xD4,channel+1]
    scan(p,{channel:('ntag',pages(uid))})
    assert p.detector.get_status()['info'][channel]['CARD_UID']==0
    assert p.bridge.get_status()['channels'][str(channel)]['uid']==bytes(uid).hex().upper()


def test_transfer_clear_error_and_restart(pipeline):
    p=pipeline; uid=[4,1,2,3]
    scan(p,{0:('mifare',uid),2:('ntag',pages([4,5,6,7,8,9,10]))})
    original=p.bridge.get_status()
    scan(p,{0:('absent',[])})
    assert p.bridge.get_status()['channels']['0']['state']=='unreadable'
    assert p.bridge.get_status()['channels']['2']==original['channels']['2']
    p.callback(0,p.fm.FM175XX_CARD_INFO_CLEAR,0,None,None)
    scan(p,{3:('mifare',uid)})
    state=p.bridge.get_status()
    assert state['channels']['0']['state']=='absent'
    assert state['channels']['3']['uid']=='04010203'
    state['channels']['3']['uid']='BAD'
    assert p.bridge.get_status()['channels']['3']['uid']=='04010203'
    fresh=UidBridge()
    assert fresh.epoch!=p.bridge.epoch
    assert all(c['state']=='unknown' for c in fresh.channels.values())


def test_random_mifare_not_used_as_persistent_identity(pipeline):
    p=pipeline
    scan(p,{0:('mifare',[8,1,2,3])})
    assert p.bridge.get_status()['channels']['0']['uid'] is None


@pytest.mark.parametrize('bad',['truncated','bcc','zero'])
def test_bad_ntag_never_becomes_identity(pipeline,bad):
    p=pipeline; raw=bytearray(pages([4,1,2,3,4,5,6]))
    if bad=='truncated':raw=raw[:8]
    if bad=='bcc':raw[3]^=1
    if bad=='zero':raw=bytearray(len(raw))
    scan(p,{1:('ntag',raw)})
    assert p.bridge.get_status()['channels']['1']['uid'] is None


def test_original_success_still_reaches_original_detector(pipeline):
    p=pipeline
    p.callback(1,p.fm.FM175XX_CARD_INFO_READ,0,p.fm.FM175XX_MIFARE_CARD_TYPE_M1,[0]*1024)
    assert p.detector.get_status()['info'][1]['OFFICIAL'] is True
    # Successful proprietary payload decoding is a stub, not a crypto/RF test.


def test_upstream_default_mifare_fallback_is_gated(pipeline):
    p=pipeline
    p.reader._card_claim_handlers.clear()
    scan(p,{0:('mifare',[4,1,2,3])})
    assert p.detector.get_status()['info'][0]['CARD_UID']==0
    assert p.bridge.get_status()['channels']['0']['uid'] is None
    p.bridge.enable_mifare_fallback(p.reader)
    scan(p,{0:('mifare',[4,1,2,3])})
    assert p.bridge.get_status()['channels']['0']['uid']=='04010203'


@pytest.mark.parametrize('kind', ['mifare','ntag'])
@pytest.mark.parametrize('channel', range(4))
def test_minimal_path_needs_no_detector_patch_or_bespok3d_hub(pipeline,kind,channel):
    p=pipeline
    stock_path=SOURCES/'base/tests_support/snapmaker_source'/p.version/'klippy/extras/filament_detect.py'
    stock=load('uid_bench_extras.stock_detector',stock_path)
    # Use original detector methods. Remove the Bespok3d parser/callback registrations.
    p.detector.__class__=stock.FilamentDetector
    p.detector._notify_data_update_cb=[]
    p.detector._card_protocol_parsers={}
    p.reader._card_claim_handlers=[]; p.reader._card_type_handlers={}
    p.bridge.enable_mifare_fallback(p.reader)
    p.bridge.enable_type2_uid(p.reader)
    uid=[4,0,1,2] if kind=='mifare' else [4,0,1,2,3,4,5]
    scan(p,{channel:(kind,uid if kind=='mifare' else pages(uid))})
    assert p.bridge.get_status()['channels'][str(channel)]['uid']==bytes(uid).hex().upper()
    assert p.detector.get_status()['info'][channel]['CARD_UID']==0


def test_minimal_module_refuses_existing_ntag_handler(pipeline):
    with pytest.raises(ValueError,match='already registered'):
        pipeline.bridge.enable_type2_uid(pipeline.reader)
