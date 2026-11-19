"""Independent synthetic layouts: unknown fields, chip pairing and accounting."""
import copy
import struct
import pytest
from test_rfid_bambu import env, Fleet, Server
from tracker_uid import decode_qidi, decode_anycubic
from tracker_rfid_metadata import validate_tag
from tracker_rfid import RfidWorker
from tracker_uid_runtime import AccountingOwner


def qidi(uid='04123456', material=2, color=1, manufacturer=1):
    return decode_qidi(bytes.fromhex(uid),bytes([material,color,manufacturer])+bytes(13))


def anycubic_pages(uid='04112233445566', material='PLA+', sku='AHPLPBK-108'):
    u=bytes.fromhex(uid);b=bytearray(144)
    b[:3]=u[:3];b[3]=0x88^u[0]^u[1]^u[2];b[4:8]=u[3:];b[8]=u[3]^u[4]^u[5]^u[6]
    b[12:16]=bytes.fromhex('E1101200');b[16:20]=bytes.fromhex('7B006500')
    b[20:20+len(sku)]=sku.encode();b[40:42]=b'AC';b[60:60+len(material)]=material.encode()
    b[80:84]=bytes.fromhex('FF96C1FE')
    for offset,values in ((92,(50,200)),(96,(190,230)),(116,(55,65)),(120,(175,330)),(124,(1000,0))):
        struct.pack_into('<HH',b,offset,*values)
    return b


def anycubic(uid='04112233445566'):
    return decode_anycubic(bytes.fromhex(uid),anycubic_pages(uid))


def configure(o, tags):
    config=o.call('settings')['values']['rfid']
    config.update(confirmed_new_tags=[t['identity'] for t in tags],
        densities={'qidi:02':1.32,'anycubic:AHPLPBK-108':1.23},
        diameters={'qidi:02':1.75},nominal_weights={'qidi:02':1000})
    o.call('save_settings',{'rfid':config},o.call('settings')['revision'])


@pytest.mark.parametrize('material,color,expected',[(2,1,('PLA','FFFFFF')),(0x29,0x0B,('PETG','1714B0')),
    (0x29,0x12,('PETG','FF362D')),(0x29,0x14,('PETG','898F9B'))])
def test_qidi_confirmed_codes_without_invented_dimensions(material,color,expected):
    t=qidi(material=material,color=color);assert (t['material'],t['color'])==expected
    assert t['nominal_weight_g'] is None and t['diameter_mm'] is None and t['nozzle_max_c'] is None
    assert validate_tag(t,t['uid'])==t


def test_qidi_unknown_codes_stay_unknown_not_white():
    t=qidi(material=0x7E,color=0x7E)
    assert t['material'] is None and t['color'] is None and t['colors']==[]
    assert validate_tag(t,t['uid'])==t
    with pytest.raises(ValueError):decode_qidi(bytes.fromhex('04123456'),bytes([2,1,1,9])+bytes(12))


@pytest.mark.parametrize('version',[0x64,0x65])
def test_anycubic_color_order_fields_and_chip_identity(version):
    b=anycubic_pages();b[18]=version;t=decode_anycubic(bytes.fromhex('04112233445566'),b)
    assert t['color']=='FEC196' and t['nominal_weight_g']==1000 and t['diameter_mm']==1.75
    assert t['nozzle_min_c']==190 and t['nozzle_max_c']==230 and t['bed_c']==65 and t['length_m']==330
    assert t['identity']=='anycubic:chip:04112233445566' and validate_tag(t,t['uid'])==t


@pytest.mark.parametrize('fault',['short','version','offset','uid','diameter','temperature','sku_width','text'])
def test_bad_anycubic_pages_declined(fault):
    b=anycubic_pages()
    if fault=='short':b=b[:127]
    elif fault=='version':b[18]=0x66
    elif fault=='offset':b[16:20]=bytes(4);b[24:28]=bytes.fromhex('7B006500')
    elif fault=='uid':b[0]=5
    elif fault=='diameter':b[120:122]=b'\0\0'
    elif fault=='temperature':struct.pack_into('<H',b,96,300)
    elif fault=='sku_width':b[20:32]=b'ABCDEFGHIJKL'
    else:b[60]=0xFF
    with pytest.raises(ValueError):decode_anycubic(bytes.fromhex('04112233445566'),b)


@pytest.mark.parametrize('factory,second_uid',[(qidi,'04765432'),(anycubic,'04778899001122')])
def test_second_side_requires_confirmation_then_preserves_balance(env,factory,second_uid):
    o,f,s,w,path=env;first_tag=factory();f.set(first_tag)
    configure(o,[first_tag]);first=w.scan('a','0');s.rows['spool'][0]['remaining_weight']=654.321
    second_tag=factory(second_uid);f.set(second_tag)
    with pytest.raises(ValueError,match='Confirm a new roll'):w.scan('a','0')
    assert len(s.rows['spool'])==1
    ticket=o.call('rfid_prepare','a','0')
    with pytest.raises(ValueError):o.call('rfid_pair',ticket,first['spool_id'])
    o.call('rfid_pair',ticket,first['spool_id'],confirmed=True)
    second=w.scan('a','0');assert second['spool_id']==first['spool_id'] and second['remaining_mg']==654321
    o.close();other=AccountingOwner(path,f)
    try:
        w2=RfidWorker(other,w.allowed_urls,client_factory=s)
        assert w2.scan('a','0')['remaining_mg']==654321
        f.set(first_tag,'1')
        assert all(not x['usable'] for x in other.call('refresh'))
    finally:other.close()


def test_identical_products_explicitly_new_rolls_remain_distinct(env):
    o,f,s,w,_=env;a=qidi();b=qidi('04765432');configure(o,[a,b]);f.set(a);one=w.scan('a','0')
    f.set(b);two=w.scan('a','0')
    assert one['spool_id']!=two['spool_id'] and len(s.rows['spool'])==2
    with pytest.raises(ValueError):o.call('rfid_pair',o.call('rfid_prepare','a','0'),one['spool_id'],confirmed=True)


@pytest.mark.parametrize('fault',['color','material','stale','printing','occupied','changed_sequence'])
def test_pairing_rechecks_identity_and_idle_location(env,fault):
    o,f,s,w,_=env;a=qidi();configure(o,[a]);f.set(a);one=w.scan('a','0')
    b=qidi('04765432',color=0x12 if fault=='color' else 1,material=0x29 if fault=='material' else 2)
    f.set(b);ticket=o.call('rfid_prepare','a','0')
    if fault=='stale':f.value['a']['channels']['0']['age_seconds']=301
    elif fault=='printing':f.value['a']['print_state']='printing'
    elif fault=='occupied':f.set(a,'1')
    elif fault=='changed_sequence':f.value['a']['channels']['0']['sequence']=2
    with pytest.raises(ValueError):o.call('rfid_pair',ticket,one['spool_id'],confirmed=True)
    assert len(o.call('inspect')['spools'])==1


@pytest.mark.parametrize('fault',['unknown_material','unknown_color','unknown_maker','missing_diameter','missing_weight'])
def test_qidi_incomplete_metadata_does_not_create_remote_spool(env,fault):
    o,f,s,w,_=env;t=qidi(material=0x7E if fault=='unknown_material' else 2,
        color=0x7E if fault=='unknown_color' else 1,manufacturer=7 if fault=='unknown_maker' else 1)
    configure(o,[t]);f.set(t)
    config=o.call('settings')['values']['rfid']
    if fault=='missing_diameter':config['diameters']={}
    if fault=='missing_weight':config['nominal_weights']={}
    o.call('save_settings',{'rfid':config},o.call('settings')['revision'])
    with pytest.raises(ValueError):w.scan('a','0')
    assert not s.posts


@pytest.mark.parametrize('factory',[qidi,anycubic])
def test_lost_creation_reply_resumes_without_duplicate(env,factory):
    o,f,s,w,path=env;t=factory();configure(o,[t]);f.set(t);s.fail='after_spool'
    with pytest.raises(OSError):w.scan('a','0')
    o.close();other=AccountingOwner(path,f)
    try:
        s.fail=None;w2=RfidWorker(other,w.allowed_urls,client_factory=s)
        assert w2.scan('a','0')['remaining_mg']==1000000
        assert s.posts.count('spool')==1
    finally:other.close()


def test_aliases_survive_backup_and_automation_stays_off(env):
    o,f,s,w,_=env;a=qidi();configure(o,[a]);f.set(a);one=w.scan('a','0')
    f.set(qidi('04765432'));o.call('rfid_pair',o.call('rfid_prepare','a','0'),one['spool_id'],confirmed=True)
    package=o.call('backup_package');preview=o.call('validate_backup',package=package)
    o.call('restore_backup',package=package,expected_revision=preview['current_revision'])
    assert not o.call('settings')['values'].get('rfid',{}).get('enabled')
    for t in (a,qidi('04765432')):
        f.set(t);row=o.call('refresh')[0]
        assert row['spool']['spool_id']==one['spool_id']


def test_pair_cannot_hide_an_ambiguous_remote_creation(env):
    o,f,s,w,_=env;a=qidi();b=qidi('04765432');configure(o,[a,b]);f.set(a);one=w.scan('a','0')
    f.set(b);s.fail='after_spool'
    with pytest.raises(OSError):w.scan('a','0')
    with pytest.raises(ValueError,match='Creation was attempted'):
        o.call('rfid_pair',o.call('rfid_prepare','a','0'),one['spool_id'],confirmed=True)
