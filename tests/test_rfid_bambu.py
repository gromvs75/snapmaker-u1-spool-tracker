"""No printer or server: deterministic failures around RFID identity and POSTs."""
import copy
import struct
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'dev/klipper'))
from tracker_uid import decode_bambu_blocks, bambu_keys
from tracker_rfid import RfidWorker
from tracker_uid_runtime import AccountingOwner
from tracker_uid_catalog import UidCatalog
from tracker_uid_accounting import UidAccounting
from tracker_uid_library import Library


def blocks(uid='04112233', identity=1):
    b = {i: bytearray(16) for i in (0,1,2,4,5,6,9,16)}
    b[0][:4] = bytes.fromhex(uid)
    b[1][:7] = b'A00-R00'; b[1][8:13] = b'GFA00'
    b[2][:3] = b'PLA'; b[4][:9] = b'PLA Basic'
    b[5][:4] = bytes.fromhex('C12E1FFF')
    struct.pack_into('<H', b[5], 4, 1000); struct.pack_into('<f', b[5], 8, 1.75)
    struct.pack_into('<HH', b[6], 8, 230, 190)
    b[9][:] = identity.to_bytes(16, 'big')
    return b


def tag(uid='04112233', identity=1):
    return decode_bambu_blocks(bytes.fromhex(uid), blocks(uid, identity))


class Fleet:
    def __init__(self):
        self.value={'a':dict(printer_id='a',state='ready',printer_connected=True,print_state='standby',
                            client_session='test',generation=1,epoch='test',
                            channels={str(i):dict(state='absent',uid=None) for i in range(4)})}
        self.set(tag())
    def set(self, value, ch='0'):
        self.value['a']['channels'][ch] = dict(state='present',uid=value['uid'],tag=value,sequence=1,age_seconds=0)
    def snapshot(self):return copy.deepcopy(self.value)


class Server:
    def __init__(self):
        self.rows={'filament':[], 'spool':[]}; self.posts=[]; self.puts=[]; self.fail=None; self.before_reply=None
    def __call__(self, url): return self
    def request(self, method, path, body=None):
        if path == '/info': return {'version':'0.27.1'}, {}
        if path.startswith('/spool/'):
            row=self.rows['spool'][int(path.split('/')[2])-1]
            if method=='PUT':
                self.puts.append(copy.deepcopy(body));row['remaining_weight']-=body['use_weight']
                if self.fail=='after_use':raise OSError('Use reply lost')
            return copy.deepcopy(row),{}
        kind=path.split('?')[0].strip('/')
        if method == 'GET': return copy.deepcopy(self.rows[kind]), {}
        assert method == 'POST'
        self.posts.append(kind)
        if self.fail == 'before_'+kind: raise OSError('No reply')
        result=dict(body,id=len(self.rows[kind])+1)
        if kind == 'spool': result['filament']=copy.deepcopy(self.rows['filament'][body['filament_id']-1])
        self.rows[kind].append(result)
        if self.before_reply:self.before_reply()
        if self.fail == 'after_'+kind: raise OSError('Reply lost')
        return copy.deepcopy(result), {}


@pytest.fixture
def env(tmp_path):
    fleet=Fleet(); owner=AccountingOwner(tmp_path/'db',fleet); server=Server()
    owner.call('save_settings',dict(spoolman_url='http://127.0.0.1:1',spoolman_mode='send',
        rfid=dict(enabled=True,allow_create=True,new_spools='nominal',densities={'GFA00':1.24})),
        owner.call('settings')['revision'])
    worker=RfidWorker(owner,['http://127.0.0.1:1'],client_factory=server)
    yield owner,fleet,server,worker,tmp_path/'db'
    owner.close()


def test_hkdf_independent_public_trailer_vector():
    assert bambu_keys(bytes.fromhex('0DF58A36'))[0].hex() == '6b5e53ad3b22'
    assert bambu_keys(bytes.fromhex('0DF58A36'))[4].hex() == '505a316bc57a'


@pytest.mark.parametrize('fault', ['short','wrong_uid','zero_identity','nan','bad_text','bad_temperature'])
def test_invalid_dump_never_decodes(fault):
    b=blocks()
    if fault=='short':b.pop(9)
    elif fault=='wrong_uid':b[0][1]=0
    elif fault=='zero_identity':b[9][:]=bytes(16)
    elif fault=='nan':struct.pack_into('<f',b[5],8,float('nan'))
    elif fault=='bad_text':b[2][0]=255
    else:struct.pack_into('<H',b[6],10,390)
    with pytest.raises(ValueError):decode_bambu_blocks(bytes.fromhex('04112233'),b)


def test_two_chips_same_roll_and_identical_product_different_roll(env):
    o,f,s,w,_=env; first=w.scan('a','0')
    assert first['remaining_mg']==1000000
    s.rows['spool'][0]['remaining_weight']=712.345
    f.set(tag('04AABBCC'))
    second=w.scan('a','0')
    assert second['spool_id']==first['spool_id'] and second['remaining_mg']==712345
    assert len(s.rows['spool'])==1
    f.set(tag('04998877',identity=2)); third=w.scan('a','0')
    assert third['spool_id']!=first['spool_id']
    assert len(s.rows['spool'])==2 and len(s.rows['filament'])==1
    f.set(tag());assert w.scan('a','0')['remaining_mg']==712345


@pytest.mark.parametrize('kind', ['filament','spool'])
def test_lost_post_ack_recovered_without_second_post(env,kind):
    o,f,s,w,path=env;s.fail='after_'+kind
    with pytest.raises(OSError):w.scan('a','0')
    o.close(); o2=AccountingOwner(path,f)
    try:
        s.fail=None
        w2=RfidWorker(o2,w.allowed_urls,client_factory=s)
        assert w2.scan('a','0')['remaining_mg']==1000000
        assert s.posts.count(kind)==1
    finally:o2.close()


def test_missing_post_ack_without_remote_record_never_retried(env):
    o,f,s,w,_=env;s.fail='before_spool'
    with pytest.raises(OSError):w.scan('a','0')
    s.fail=None
    with pytest.raises(ValueError,match='outcome unknown'):w.scan('a','0')
    assert s.posts.count('spool')==1


@pytest.mark.parametrize('fault',['printing','stale','offline','two_heads','metadata','manual_uid','no_initial','no_density','not_allowed'])
def test_guards_before_remote_writes(env,fault):
    o,f,s,w,_=env
    if fault=='printing':f.value['a']['print_state']='printing'
    elif fault=='stale':f.value['a']['channels']['0']['age_seconds']=301
    elif fault=='offline':f.value['a']['state']='offline'
    elif fault=='two_heads':f.set(tag('04AABBCC'),'1')
    elif fault=='metadata':f.value['a']['channels']['0']['tag']['uid']='04AABBCC'
    elif fault=='manual_uid':o.call('register','04112233','Manual',10000)
    elif fault=='not_allowed':w.allowed_urls=frozenset()
    else:
        config=o.call('settings')['values']['rfid']
        if fault=='no_initial':config['new_spools']='hold'
        else:config['densities']={}
        o.call('save_settings',{'rfid':config},o.call('settings')['revision'])
    with pytest.raises(ValueError):w.scan('a','0')
    assert not s.posts


def test_scan_changes_during_http_cannot_bind_old_tag(env):
    o,f,s,w,_=env
    s.before_reply=lambda:f.set(tag('04AABBCC',identity=2))
    with pytest.raises(ValueError):w.scan('a','0')
    assert not o.call('inspect')['spools']


def test_pending_consumption_kept_when_other_side_is_seen(env):
    o,f,s,w,path=env; first=w.scan('a','0');o.close()
    c=UidCatalog(path);a=UidAccounting(c);Library(a)
    key=a.begin('a','print','1',['0'],'fixture',f.snapshot())
    assert a.apply(key,1,{'0':12500},state='completed',source='fixture',basis='executed_gcode')=='applied'
    c.close();o2=AccountingOwner(path,f)
    try:
        f.set(tag('04AABBCC'));w2=RfidWorker(o2,w.allowed_urls,client_factory=s)
        result=w2.scan('a','0')
        assert result['spool_id']==first['spool_id'] and result['remaining_mg']==987500
        assert result['balance_source']=='local' and s.rows['spool'][0]['remaining_weight']==1000
        # Two physical chip observations of the same roll cannot feed two heads.
        f.set(tag(),'1')
        assert all(not row['usable'] for row in o2.call('refresh'))
    finally:o2.close()


def test_duplicate_remote_roll_marker_is_blocked(env):
    o,f,s,w,_=env;w.scan('a','0')
    s.rows['spool'].append(dict(s.rows['spool'][0],id=2))
    with pytest.raises(ValueError,match='Duplicate'):w.scan('a','0')


def test_restore_disables_rfid_enrollment(env):
    o,f,s,w,_=env;w.scan('a','0');package=o.call('backup_package')
    preview=o.call('validate_backup',package=package)
    o.call('restore_backup',package=package,expected_revision=preview['current_revision'])
    assert not o.call('settings')['values'].get('rfid',{}).get('enabled')


@pytest.mark.parametrize('lost_ack',[False,True])
def test_explicit_auto_send_policy_and_ambiguous_delivery(tmp_path,lost_ack):
    from tracker_uid_delivery import Delivery
    from tracker_rfid import RfidRegistry
    c=UidCatalog(tmp_path/'db');a=UidAccounting(c);lib=Library(a);delivery=Delivery(a)
    registry=RfidRegistry(lib,delivery);f=Fleet();s=Server();url='http://127.0.0.1:1'
    class Owner:
        fleet=f
        def call(self, operation, *args, **kwargs):
            if operation.startswith('rfid_'):return getattr(registry,operation[5:])(*args,fleet=f.snapshot(),**kwargs)
            if operation.startswith('delivery_'):return getattr(delivery,operation[9:])(*args,**kwargs)
            if operation=='settings':return lib.settings()
            raise AssertionError(operation)
    try:
        lib.save_settings(dict(spoolman_url=url,spoolman_mode='send',rfid=dict(
            enabled=True,allow_create=True,new_spools='nominal',send_usage=True,densities={'GFA00':1.24})),lib.settings()['revision'])
        worker=RfidWorker(Owner(),[url],client_factory=s);worker.scan('a','0')
        key=a.begin('a','print','1',['0'],'fixture',f.snapshot())
        a.apply(key,1,{'0':12500},state='completed',source='fixture',basis='executed_gcode')
        if lost_ack:s.fail='after_use'
        worker.tick();worker.tick()
        assert len(s.puts)==1 and s.rows['spool'][0]['remaining_weight']==987.5
        assert delivery.list()[0]['state']==('uncertain' if lost_ack else 'sent')
        f.set(tag('04AABBCC'));assert worker.scan('a','0')['remaining_mg']==987500
    finally:c.close()
