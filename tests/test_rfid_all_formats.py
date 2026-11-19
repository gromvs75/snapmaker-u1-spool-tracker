"""Protocol boundaries + database identity, independent known answers, no hardware."""
import copy
import random
import sys
from pathlib import Path
import pytest
from test_rfid_bambu import env
from tracker_uid import (aes128,decode_creality,decode_pages,decode_elegoo,cbor_at,ndef_records,decode_opentag)
from tracker_rfid_metadata import validate_tag,validate_config
from tracker_rfid import RfidWorker
from tracker_uid_runtime import AccountingOwner
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dev.labs.uid_live_bench.all_tag_fixtures import KINDS,MASTER,PAYLOAD_KEY,CIPHER,KEYS,fixture,uid_for,ndef,cbor


def tag(kind,side=0):
    uid=bytes.fromhex(uid_for(kind,side));raw=fixture(kind,side)
    return decode_creality(uid,aes128(bytes.fromhex(PAYLOAD_KEY),raw[64:112],True)) if kind=='creality' else decode_pages(uid,raw,set(KINDS))


def settings(tags):
    return dict(enabled=True,allow_create=True,send_usage=True,new_spools='nominal',
                confirmed_new_tags=[t['identity'] for t in tags],densities={t['material_id']:1.24 for t in tags},
                diameters={t['material_id']:1.75 for t in tags},nominal_weights={t['material_id']:1000 for t in tags},
                material_names={t['material_id']:'PLA' for t in tags if t['format']=='tigertag'},
                manufacturer_names={t['material_id']:'Bench filament' for t in tags if t['format']=='tigertag'})


def test_aes_fips197_known_answer_and_openssl_creality_vectors():
    key=bytes.fromhex(MASTER);plain=bytes.fromhex('00112233445566778899aabbccddeeff')
    cipher=bytes.fromhex('69c4e0d86a7b0430d8cdb78070b4c55a')
    assert aes128(key,plain)==cipher and aes128(key,cipher,True)==plain
    assert aes128(bytes.fromhex(PAYLOAD_KEY),CIPHER,True)==b'3C6260276A210100100000FF0330000001000000%'.ljust(48,b'\0')
    for uid,keyhex in KEYS.items():assert aes128(key,bytes.fromhex(uid)*4)[:6].hex()==keyhex


@pytest.mark.parametrize('kind,material,color',[('creality','PLA','0000FF'),('elegoo','PLA','09C299'),
    ('tigertag',None,'ABCDEF'),('generic-ndef','PETG','C12E1F'),('opentag','PLA','112233'),('openprinttag','PLA','778899')])
def test_decoded_fields_and_no_tag_balance_or_server_id(kind,material,color):
    t=tag(kind);assert (t['material'],t['color'])==(material,color);assert validate_tag(t,t['uid'])==t
    assert t['nominal_weight_g']==1000 and 'remaining_weight' not in t and 'spool_id' not in t
    assert t['identity']==kind+':chip:'+uid_for(kind)


@pytest.mark.parametrize('kind',KINDS)
def test_each_format_pair_and_restart_preserve_remote_remaining(env,kind):
    o,f,s,w,path=env;a=tag(kind);f.set(a);o.call('save_settings',{'rfid':settings([a])},o.call('settings')['revision'])
    one=w.scan('a','0')
    details=o.call('library_snapshot')['spools'][0]['details']
    assert details['material']==('PLA' if kind=='tigertag' else a['material'])
    assert details['diameter']==1.75
    s.rows['spool'][0]['remaining_weight']=876.543
    b=tag(kind,1);f.set(b)
    with pytest.raises(ValueError,match='Confirm a new roll'):w.scan('a','0')
    assert len(s.rows['spool'])==1
    o.call('rfid_pair',o.call('rfid_prepare','a','0'),one['spool_id'],confirmed=True)
    assert w.scan('a','0')['remaining_mg']==876543
    o.close();other=AccountingOwner(path,f)
    try:
        w2=RfidWorker(other,w.allowed_urls,client_factory=s)
        for t in (a,b,a):
            f.set(t);result=w2.scan('a','0');assert result['remaining_mg']==876543 and result['spool_id']==one['spool_id']
        assert len(s.rows['spool'])==1 and s.puts==[]
    finally:other.close()


@pytest.mark.parametrize('kind',KINDS)
def test_identical_product_does_not_merge_distinct_rolls(env,kind):
    o,f,s,w,_=env;a,b=tag(kind),tag(kind,1)
    o.call('save_settings',{'rfid':settings([a,b])},o.call('settings')['revision'])
    f.set(a);one=w.scan('a','0');f.set(b);two=w.scan('a','0')
    assert one['spool_id']!=two['spool_id'] and len(s.rows['spool'])==2


@pytest.mark.parametrize('kind',KINDS)
def test_metadata_rejects_forged_identity_nan_color_and_uid(kind):
    original=tag(kind)
    for field,value in [('identity','bambu:'+'1'*32),('uid','BAD'),('diameter_mm',float('nan')),('colors',['XXFFFF']),('nominal_weight_g',-1)]:
        t=copy.deepcopy(original);t[field]=value
        with pytest.raises(ValueError):validate_tag(t,original['uid'])


def test_tigertag_without_explicit_lookup_is_held(env):
    o,f,s,w,_=env;t=tag('tigertag');cfg=settings([t]);cfg.pop('material_names');f.set(t)
    o.call('save_settings',{'rfid':cfg},o.call('settings')['revision'])
    with pytest.raises(ValueError,match='Unmapped'):w.scan('a','0')
    assert not s.posts


def test_unknown_creality_code_and_bucket_do_not_guess():
    p=b'3C6260276A21ZZZZZ00000FFFFFF000001000000%'.ljust(48,b'\0')
    t=decode_creality(bytes.fromhex(uid_for('creality')),p)
    assert t['material'] is None and t['nominal_weight_g'] is None and t['diameter_mm'] is None
    with pytest.raises(ValueError):decode_creality(bytes.fromhex(uid_for('creality')),bytes(48))


@pytest.mark.parametrize('raw',['9f0102','bf01ff','a201010102','a1181eff','a100ff','a100a100a100a100a100a100a100a100a100a10000'])
def test_cbor_untrusted_structure_bounds(raw):
    with pytest.raises(ValueError):cbor_at(bytes.fromhex(raw))


def test_conflicting_payloads_are_held_not_first_match():
    uid=uid_for('elegoo');raw=ndef(uid,'application/json',b'{"brand":"Test","material":"PLA","color":"FFFFFF"}')
    raw[128:160]=fixture('elegoo')[64:96]
    with pytest.raises(ValueError,match='unique'):decode_pages(bytes.fromhex(uid),raw,set(KINDS))


@pytest.mark.parametrize('payload',[b'{"protocol":"openspool","material":"PLA","color":"FFFFFF"}',
    b'{"material":"PLA","material":"ABS","color":"FFFFFF"}',b'{"material":"PLA","diameter":NaN}',b'{"color":"#bad"}'])
def test_json_unknown_protocol_duplicate_keys_invalid_fields_decline(payload):
    uid=uid_for('generic-ndef')
    with pytest.raises(ValueError):decode_pages(bytes.fromhex(uid),ndef(uid,'application/json',payload),set(KINDS))


def test_ndef_lengths_chunking_truncation_and_future_version():
    raw=fixture('opentag');uid=bytes.fromhex(uid_for('opentag'))
    for short in (19,40,100,200):
        with pytest.raises(ValueError):decode_pages(uid,raw[:short],set(KINDS))
    msg=ndef_records(raw)[0][1];future=bytearray(msg);future[:2]=(3000).to_bytes(2,'big')
    with pytest.raises(ValueError):decode_opentag(uid,future)
    raw[18]|=32
    with pytest.raises(ValueError):ndef_records(raw)


def test_unknown_color_never_becomes_white(env):
    uid=uid_for('generic-ndef');t=decode_pages(bytes.fromhex(uid),ndef(uid,'application/json',b'{"brand":"Test","material":"PLA"}'),set(KINDS))
    assert t['colors']==[] and t['color'] is None
    o,f,s,w,_=env;f.set(t);o.call('save_settings',{'rfid':settings([t])},o.call('settings')['revision'])
    with pytest.raises(ValueError):w.scan('a','0')
    assert not s.posts


def test_config_validates_all_chip_identity_namespaces():
    validate_config(settings([tag(k) for k in KINDS]))
    with pytest.raises(ValueError):validate_config({'confirmed_new_tags':['elegoo:chip:12345678']})
    with pytest.raises(ValueError):validate_config({'material_names':{'x':'bad\nname'}})


def test_cbor_indefinite_maps_and_arrays_used_by_published_payload():
    raw=bytes.fromhex('a0bf0a63504c410b6454657374101903e81343112233181ef93f00182218be182318e6181c9f0001ffff')
    from tracker_uid import decode_openprinttag
    t=decode_openprinttag(bytes.fromhex(uid_for('openprinttag')),raw)
    assert t['material']=='PLA' and t['color']=='112233' and t['diameter_mm']==1.75


def test_opentag_v1_core_and_multicolor():
    uid=bytes.fromhex(uid_for('opentag'));b=bytearray(98);b[:2]=(1000).to_bytes(2,'big');b[2:5]=b'PLA'
    b[27:31]=b'Test';b[75:79]=bytes.fromhex('12345680');b[80:84]=bytes.fromhex('ABCDEF40')
    b[92:96]=bytes.fromhex('06D603E8');b[96]=40;b[97]=12
    t=decode_opentag(uid,b)
    assert t['colors']==['123456','ABCDEF'] and t['nozzle_min_c']==t['nozzle_max_c']==200
    assert t['diameter_mm']==1.75


def test_multiple_colors_survive_spoolman_registration(env):
    uid=uid_for('generic-ndef');t=decode_pages(bytes.fromhex(uid),ndef(uid,'application/json',
        b'{"brand":"Test","material":"PLA","color":"112233","additional_color_hexes":["445566","778899"]}'),set(KINDS))
    o,f,s,w,_=env;f.set(t);o.call('save_settings',{'rfid':settings([t])},o.call('settings')['revision']);w.scan('a','0')
    assert s.rows['filament'][0]['multi_color_hexes']=='112233,445566,778899' and 'color_hex' not in s.rows['filament'][0]


@pytest.mark.parametrize('fault',['changed','short','failed','stopped','capacity','uid_header'])
def test_page_reader_fails_closed_and_has_bounded_reads(monkeypatch,fault):
    import tracker_uid as module
    from types import SimpleNamespace
    uid=bytes.fromhex(uid_for('elegoo'));raw=bytearray(fixture('elegoo'));calls=[];r=SimpleNamespace()
    if fault=='capacity':raw[14]=255
    if fault=='uid_header':raw[0]^=1
    def read(page):
        calls.append(page)
        return SimpleNamespace(err_code=1 if fault=='failed' else 0,
            out_param=raw[page*4:page*4+(12 if fault=='short' else 16)])
    setattr(r,module.P+'reader_a_m1_block_read',read)
    setattr(r,module.P+'stop_event',SimpleNamespace(is_set=lambda:fault=='stopped'))
    setattr(r,module.P+'picc_a',object())
    monkeypatch.setattr(module,'selected_uid',lambda p:list(uid if fault!='changed' else bytes(7)))
    with pytest.raises(ValueError):module.read_pages(r,SimpleNamespace(FM175XX_OK=0),uid,lambda:0,{'elegoo'})
    assert len(calls)<=32


def test_creality_wrong_keys_do_not_yield_plausible_metadata():
    with pytest.raises(ValueError):decode_creality(bytes.fromhex(uid_for('creality')),aes128(bytes(16),CIPHER,True))


@pytest.mark.parametrize('unit,measure,expected',[(10,1000000,1000),(21,1000,1000),(35,1,1000),(48,1000,None),(0,1000,None)])
def test_tigertag_units_are_not_assumed_grams(unit,measure,expected):
    raw=fixture('tigertag');raw[36:39]=measure.to_bytes(3,'big');raw[39]=unit
    t=decode_pages(bytes.fromhex(uid_for('tigertag')),raw,{'tigertag'})
    assert t['nominal_weight_g']==expected and t['twin_id']==12345678 and t['tag_count']==2


def test_tigertag_resin_and_bad_count_are_not_filament():
    for offset,value in [(28,0xAD),(55,0x32)]:
        raw=fixture('tigertag');raw[offset]=value
        with pytest.raises(ValueError):decode_pages(bytes.fromhex(uid_for('tigertag')),raw,{'tigertag'})


def test_same_twin_timestamp_remains_explicit_pairing_hint():
    a,b=tag('tigertag'),tag('tigertag',1)
    assert a['twin_id']==b['twin_id'] and a['identity']!=b['identity']
    assert a['tag_index']==1 and b['tag_index']==2
