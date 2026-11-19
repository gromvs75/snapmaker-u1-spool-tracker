"""Real public key fingerprints and offline vocabulary, synthetic RF only."""
import copy
import hashlib
from types import SimpleNamespace
import pytest
from test_rfid_bambu import env
from test_rfid_all_formats import settings
from tracker_uid import (CREALITY_MASTER,CREALITY_PAYLOAD,configured_creality_keys,aes128,decode_creality,decode_pages)
from tracker_rfid_lookup import resolve_names
from tracker_tigertag_registry import MATERIALS,BRANDS,REVISION
from tracker_rfid import RfidWorker
from tracker_uid_runtime import AccountingOwner
from dev.labs.uid_live_bench.automatic_tag_fixtures import fixture,CIPHER,KEYS
from dev.labs.uid_live_bench.all_tag_fixtures import uid_for


def tag(kind='tigertag',side=0):
    uid=bytes.fromhex(uid_for(kind,side));b=fixture(kind,side)
    return decode_creality(uid,aes128(CREALITY_PAYLOAD,b[64:112],True)) if kind=='creality' else decode_pages(uid,b,{'tigertag'})


def config(tags):
    c=settings(tags);c.pop('material_names');c.pop('manufacturer_names');return c


def test_published_keys_match_independent_bespok_fingerprints_and_openssl_vectors():
    assert hashlib.sha256(CREALITY_MASTER).hexdigest()=='e544d94feb16159bbd7bc227df1e283eca1f38f2bb2015dfcc6161b74473b5c2'
    assert hashlib.sha256(CREALITY_PAYLOAD).hexdigest()=='acec2106007458579ba522b25610b2cf509ae59d7879cb975f65c45228e5c9a1'
    assert aes128(CREALITY_PAYLOAD,CIPHER,True)==b'3C6260276A210100100000FF0330000001000000%'.ljust(48,b'\0')
    for uid,expected in KEYS.items():assert aes128(CREALITY_MASTER,bytes.fromhex(uid)*4)[:6].hex()==expected
    t=tag('creality');assert t['material']=='PLA' and t['color']=='0000FF'


def test_absent_configuration_uses_public_defaults():
    assert configured_creality_keys(SimpleNamespace(get={}.get))==(CREALITY_MASTER,CREALITY_PAYLOAD)


@pytest.mark.parametrize('values',[{'creality_master_key':''},{'creality_master_key':'00'*16},
    {'creality_payload_key':'bad'},{'creality_master_key':'bad','creality_payload_key':'00'*16},
    {'creality_master_key':'','creality_payload_key':''}])
def test_partial_invalid_or_empty_override_never_falls_back(values):
    assert configured_creality_keys(SimpleNamespace(get=values.get))==(None,None)


def test_explicit_synthetic_keys_still_supported():
    assert configured_creality_keys(SimpleNamespace(get={'creality_master_key':'01'*16,'creality_payload_key':'02'*16}.get))==(bytes([1])*16,bytes([2])*16)


def test_offline_names_from_real_vocab_leave_raw_tag_identity_colors_mass_unchanged():
    t=tag();before=copy.deepcopy(t);names=resolve_names(t,{})
    assert names['material']=='PLA' and names['manufacturer']=='Bambu Lab'
    assert all(REVISION in s for s in names['lookup_sources'].values()) and t==before
    assert MATERIALS[38256]=='PETG' and BRANDS[26956]=='Creality'


@pytest.mark.parametrize('badcode',['tigertag:FFFF:FFFF:FFFFFFFF','tigertag:8933:FFFF:FFFFFFFF','tigertag:FFFF:954B:FFFFFFFF'])
def test_unknown_material_or_brand_held_before_post(env,badcode):
    o,f,s,w,_=env;t=tag();t['material_id']=badcode;f.set(t)
    o.call('save_settings',{'rfid':config([t])},o.call('settings')['revision'])
    with pytest.raises(ValueError,match='Unmapped'):w.scan('a','0')
    assert not s.posts


def test_explicit_user_lookup_has_precedence():
    t=tag();r=resolve_names(t,{'material_names':{t['material_id']:'PETG custom'},'manufacturer_names':{t['material_id']:'My roll'}})
    assert r==dict(material='PETG custom',manufacturer='My roll',lookup_sources={})


@pytest.mark.parametrize('kind',['creality','tigertag'])
def test_automatic_registration_pair_and_restart_without_name_mappings(env,kind):
    o,f,s,w,path=env;a=tag(kind);f.set(a);o.call('save_settings',{'rfid':config([a])},o.call('settings')['revision'])
    first=w.scan('a','0');row=o.call('library_snapshot')['spools'][0]
    assert row['details']['material']=='PLA'
    assert row['details']['manufacturer']==('Creality' if kind=='creality' else 'Bambu Lab')
    assert s.rows['filament'][0]['color_hex']==a['color']
    if kind=='tigertag':assert s.rows['filament'][0]['name']=='Bambu Lab PLA ABCDEF'
    s.rows['spool'][0]['remaining_weight']=623.5;b=tag(kind,1);f.set(b)
    with pytest.raises(ValueError,match='Confirm a new roll'):w.scan('a','0')
    o.call('rfid_pair',o.call('rfid_prepare','a','0'),first['spool_id'],confirmed=True)
    assert w.scan('a','0')['remaining_mg']==623500
    o.close();other=AccountingOwner(path,f)
    try:
        w2=RfidWorker(other,w.allowed_urls,client_factory=s)
        for t in (a,b,a):
            f.set(t);r=w2.scan('a','0');assert r['remaining_mg']==623500 and r['spool_id']==first['spool_id']
        assert len(s.rows['spool'])==1 and not s.puts
    finally:other.close()
