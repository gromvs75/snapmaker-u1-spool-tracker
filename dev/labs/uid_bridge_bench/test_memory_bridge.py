"""Unmodified stock driver, real activation/cascade loop, simulated radio replies."""
import hashlib
import sys
import threading
import types

import pytest
from memory_bridge import MemoryUidBridge, P
from test_uid_pipeline import SOURCES, load, scan

VERSIONS=['1.3.0.168','2.0.0.205','2.1.0.157']


@pytest.fixture(params=VERSIONS)
def stock(request,monkeypatch):
    for name in ('spidev','gpiod'):
        monkeypatch.setitem(sys.modules,name,types.ModuleType(name))
    path=SOURCES/'base/tests_support/snapmaker_source'/request.param/'klippy/extras/fm175xx_reader.py'
    fm=load('stock_reader_bench',path)
    reader=fm.FM175XXReader.__new__(fm.FM175XXReader)
    reader._first_scan_fail_fast=False
    setattr(reader,P+'picc_a',fm.Fm175xxPiccMetaData())
    events=[]
    return types.SimpleNamespace(fm=fm,reader=reader,path=path,
        digest=hashlib.sha256(path.read_bytes()).hexdigest(),callback=lambda *a:events.append(a),events=events)


def run(p,cards,*,wrapped=True,bad_bcc=False,radio_fail=False,enqueue=None):
    calls=[]; bridge=MemoryUidBridge(enqueue or (lambda fn:fn()))
    def setup():
        r,fm=p.reader,p.fm
        selected={'channel':None}
        previous=getattr(r,P+'select_channel')
        def select(ch):
            previous(ch);selected['channel']=ch
        setattr(r,P+'select_channel',select)
        def wakeup():
            calls.append('wakeup')
            kind,uid=cards[selected['channel']]
            if kind=='absent':return fm.FM175XX_CARD_WAKEUP_ERR
            picc=getattr(r,P+'picc_a')
            picc.ATQA[0]={4:0,7:0x40,10:0x80}[len(uid)]
            return 0
        def anticoll(level):
            calls.append(('anticoll',level))
            kind,uid=cards[selected['channel']]
            if radio_fail:return fm.FM175XX_CARD_COLL_ERR
            chunks=([uid] if len(uid)==4 else
                    [[0x88,*uid[:3]],uid[3:]] if len(uid)==7 else
                    [[0x88,*uid[:3]],[0x88,*uid[3:6]],uid[6:]])
            b=chunks[level];picc=getattr(r,P+'picc_a')
            picc.UID[level*4:level*4+4]=b
            picc.BCC[level]=b[0]^b[1]^b[2]^b[3]^(1 if bad_bcc else 0)
            return 0
        def select_card(level):
            calls.append(('select',level))
            kind,uid=cards[selected['channel']]
            last={4:0,7:1,10:2}[len(uid)]
            getattr(r,P+'picc_a').SAK[level]=4 if level<last else (0 if kind=='ntag' else 8)
            return 0
        if any(kind=='official' for kind,uid in cards.values()):
            setattr(r,P+'reader_a_m1_read_all_data',lambda *a:
                    types.SimpleNamespace(err_code=0,out_param=[42]*1024))
        setattr(r,P+'reader_a_wakeup',wakeup)
        setattr(r,P+'reader_a_anticoll',anticoll)
        setattr(r,P+'reader_a_select',select_card)
        # Use unmodified stock activation implementation, NOT an activation result stub.
        setattr(r,P+'reader_a_activate',fm.FM175XXReader._FM175XXReader__reader_a_activate.__get__(r))
        if wrapped:
            bridge.attach(r,source_path=p.path,allowed_sha256={p.digest},
                          read_op=fm.FM175XX_CARD_INFO_READ,clear_op=fm.FM175XX_CARD_INFO_CLEAR)
    scan(p,cards,before_run=setup)
    assert hashlib.sha256(p.path.read_bytes()).hexdigest()==p.digest
    return bridge,calls


@pytest.mark.parametrize('channel',range(4))
@pytest.mark.parametrize('kind,uid',[
    ('mifare',[4,0,1,2]),('ntag',[4,0,1,2,3,4,5]),('mifare',[4,0,1,2,3,4,5]),
    ('mifare',[4,0,1,2,3,4,5,6,7,8])])
def test_uid_without_payload_or_driver_file_changes(stock,channel,kind,uid):
    bridge,calls=run(stock,{channel:(kind,uid)})
    result=bridge.get_status()['channels'][str(channel)]
    assert result['state']=='present'
    assert result['uid']==bytes(uid).hex().upper()
    # Factory firmware still reports its original error/unknown result.
    assert stock.events[-1][0]==channel
    assert stock.events[-1][2]!=0
    bridge.detach()


def test_original_callbacks_and_radio_call_sequence_unchanged(stock):
    cards={0:('mifare',[4,1,2,3]),2:('ntag',[4,1,2,3,4,5,6])}
    _,baseline=run(stock,cards,wrapped=False)
    events=list(stock.events);stock.events.clear()
    bridge,observed=run(stock,cards)
    assert baseline==observed
    assert events==stock.events
    bridge.detach()
    stock.events.clear()
    _,after=run(stock,cards,wrapped=False)
    assert baseline==after and events==stock.events


@pytest.mark.parametrize('fault',['bcc','radio','random','absent'])
def test_invalid_or_unstable_uid_is_not_bound(stock,fault):
    cards={0:('absent',[]) if fault=='absent' else ('mifare',[8 if fault=='random' else 4,1,2,3])}
    bridge,_=run(stock,cards,bad_bcc=fault=='bcc',radio_fail=fault=='radio')
    assert bridge.get_status()['channels']['0']['state']=='unreadable'
    assert bridge.get_status()['channels']['0']['uid'] is None
    bridge.detach()


def test_delayed_event_cannot_resurrect_cleared_or_detached_tag(stock):
    queue=[]
    bridge,_=run(stock,{0:('mifare',[4,1,2,3])},enqueue=queue.append)
    getattr(stock.reader,P+'card_info_deal_cb')(0,stock.fm.FM175XX_CARD_INFO_CLEAR,0,None,None)
    assert len(queue)==2
    queue[1]();queue[0]()  # reordered delivery
    assert bridge.get_status()['channels']['0']['state']=='absent'
    bridge.detach();queue[0]()
    assert bridge.get_status()['channels']['0']['state']=='unknown'


def test_late_callback_registration_preserved_on_detach(stock):
    bridge,_=run(stock,{0:('mifare',[4,1,2,3])})
    events=[];cb=lambda *args:events.append(args)
    stock.reader.register_cb_2_card_info_deal(cb)
    getattr(stock.reader,P+'card_info_deal_cb')(0,stock.fm.FM175XX_CARD_INFO_CLEAR,0,None,None)
    assert len(events)==1
    bridge.detach()
    assert getattr(stock.reader,P+'card_info_deal_cb') is cb


def test_conflicting_wrapper_not_silently_removed(stock):
    bridge,_=run(stock,{0:('mifare',[4,1,2,3])})
    name=P+'reader_a_activate';own=getattr(stock.reader,name)
    foreign=lambda:0;setattr(stock.reader,name,foreign)
    with pytest.raises(ValueError,match='restart required'):bridge.detach()
    assert getattr(stock.reader,name) is foreign
    setattr(stock.reader,name,own);bridge.detach()


def test_unknown_version_and_double_install_refused(stock):
    bridge,_=run(stock,{0:('mifare',[4,1,2,3])})
    other=MemoryUidBridge(lambda fn:fn())
    with pytest.raises(ValueError,match='Already wrapped'):
        other.attach(stock.reader,source_path=stock.path,allowed_sha256={stock.digest},read_op=0,clear_op=1)
    bridge.detach()
    with pytest.raises(ValueError,match='Unsupported driver hash'):
        other.attach(stock.reader,source_path=stock.path,allowed_sha256={'invalid'},read_op=0,clear_op=1)
    assert not hasattr(stock.reader,'_tracker_uid_owner')


def test_reactor_enqueue_failure_does_not_break_stock_driver(stock):
    def fail(fn):raise RuntimeError('reactor stopped')
    bridge,_=run(stock,{0:('mifare',[4,1,2,3])},enqueue=fail)
    assert len(stock.events)==1
    assert bridge.get_status()['channels']['0']['state']=='unknown'
    bridge.detach()


def test_original_success_payload_is_preserved(stock):
    cards={1:('official',[4,1,2,3])}
    _,baseline=run(stock,cards,wrapped=False)
    events=list(stock.events);stock.events.clear()
    bridge,calls=run(stock,cards)
    assert calls==baseline and stock.events==events
    assert stock.events[-1][2]==0 and stock.events[-1][4]==[42]*1024
    assert bridge.get_status()['channels']['1']['uid']=='04010203'
    bridge.detach()


def test_background_thread_to_reactor_copies_uid(stock):
    queue=[];holder=[];errors=[]
    def worker():
        try:holder.append(run(stock,{2:('ntag',[4,1,2,3,4,5,6])},enqueue=queue.append)[0])
        except Exception as e:errors.append(e)
    thread=threading.Thread(target=worker);thread.start();thread.join(timeout=5)
    assert not thread.is_alive() and not errors
    bridge=holder[0]
    assert bridge.get_status()['channels']['2']['state']=='unknown'
    getattr(stock.reader,P+'picc_a').reset()
    for event in queue:event()
    assert bridge.get_status()['channels']['2']['uid']=='04010203040506'
    bridge.detach()


def test_two_identities_in_one_scan_mark_conflict(stock):
    bridge,_=run(stock,{0:('mifare',[4,1,2,3])})
    bridge.local.channel=0
    bridge.local.seen={'04010203','04010204'}
    getattr(stock.reader,P+'card_info_deal_cb')(0,stock.fm.FM175XX_CARD_INFO_READ,-1,None,None)
    assert bridge.get_status()['channels']['0']['state']=='conflict'
    assert bridge.get_status()['channels']['0']['uid'] is None
    bridge.detach()
