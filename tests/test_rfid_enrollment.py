"""Confirmation at the UI boundary, opaque tickets and protected balances."""
import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import pytest
from test_rfid_bambu import Fleet, Server, tag as bambu
from test_rfid_automatic_lookup import tag as automatic
from test_rfid_all_formats import tag as extra
from test_rfid_multibrand import qidi, anycubic
from tracker_rfid import RfidWorker
from tracker_rfid_enrollment import Enrollment
from tracker_uid_runtime import AccountingOwner
from tracker_uid_sender import Sender

URL='http://127.0.0.1:1'


def decoded(kind,side=0):
    if kind=='bambu':return bambu('04112233' if side==0 else '04AABBCC')
    if kind in ('creality','tigertag'):return automatic(kind,side)
    if kind=='qidi':return qidi('04123456' if side==0 else '04AABBCC')
    if kind=='anycubic':return anycubic('04112233445566' if side==0 else '04AABBCCDDEEFF')
    return extra(kind,side)


@pytest.fixture
def enrollment(tmp_path):
    fleet=Fleet();owner=AccountingOwner(tmp_path/'db',fleet);server=Server()
    owner.call('save_settings',dict(language='ru',spoolman_url=URL,spoolman_mode='send'),owner.call('settings')['revision'])
    service=Enrollment(owner,fleet,lambda pid:'standby',Sender(owner,[URL]),client_factory=server)
    yield service,owner,fleet,server,tmp_path/'db'
    owner.close()


def preview(service,fleet):return service.preview('a','0',fleet.value['a']['channels']['0']['uid'])

def values(p):return dict(remaining_g=840.123,density=1.24,diameter=p['defaults']['diameter'] or 1.75,nominal=p['defaults']['nominal'] or 1000)


@pytest.mark.parametrize('kind',['bambu','qidi','anycubic','creality','elegoo','tigertag','generic-ndef','opentag','openprinttag'])
def test_confirm_pair_return_and_restart(enrollment,kind):
    svc,o,f,s,path=enrollment;f.set(decoded(kind));p=preview(svc,f)
    assert p['available'] and p['can_create'] and p['defaults']['remaining_g'] is None and not s.posts
    worker=RfidWorker(o,[URL],client_factory=s,interactive=True)
    with pytest.raises(ValueError):worker.scan('a','0')
    with pytest.raises(ValueError):svc.confirm(p['review_id'],'new',values=values(p))
    first=svc.confirm(p['review_id'],'new',confirmed=True,values=values(p));assert first['remaining_mg']==840123
    assert svc.confirm(p['review_id'],'new',confirmed=True,values=values(p))==first
    assert len(s.rows['spool'])==1 and s.rows['filament'][0]['material']==p['material']
    s.rows['spool'][0]['remaining_weight']=623.5
    # Reconcile the first side, then show the second side.
    assert worker.scan('a','0')['remaining_mg']==623500
    f.set(decoded(kind,1))
    if kind!='bambu':
        with pytest.raises(ValueError):worker.scan('a','0')
        p=preview(svc,f);assert len(p['candidates'])==1 and p['candidates'][0]['remaining_mg']==623500
        result=svc.confirm(p['review_id'],'pair',spool_id=first['spool_id'],confirmed=True)
        assert result['remaining_mg']==623500
    else:assert worker.scan('a','0')['spool_id']==first['spool_id']
    o.close();other=AccountingOwner(path,f)
    try:
        worker=RfidWorker(other,[URL],client_factory=s,interactive=True)
        for side in (0,1,0):
            f.set(decoded(kind,side));row=worker.scan('a','0');assert (row['spool_id'],row['remaining_mg'])==(first['spool_id'],623500)
        assert len(s.rows['spool'])==1 and not s.puts
    finally:other.close()


@pytest.mark.parametrize('change',['uid','printing','connection','age','settings','unconfirmed','bad_mass','nan','nominal'])
def test_changed_or_invalid_confirmation_has_no_posts(enrollment,change):
    svc,o,f,s,_=enrollment;p=preview(svc,f);v=values(p);confirmed=True
    if change=='uid':f.set(bambu('04998877',identity=2))
    if change=='printing':svc.status_reader=lambda pid:'printing'
    if change=='connection':f.value['a']['generation']+=1
    if change=='age':f.value['a']['channels']['0']['age_seconds']=301
    if change=='settings':o.call('save_settings',{'language':'en'},o.call('settings')['revision'])
    if change=='unconfirmed':confirmed=False
    if change=='bad_mass':v['remaining_g']=-1
    if change=='nan':v['density']=float('nan')
    if change=='nominal':v['nominal']=500
    with pytest.raises(ValueError):svc.confirm(p['review_id'],'new',confirmed=confirmed,values=v)
    assert not s.posts and not o.call('settings')['values'].get('rfid',{}).get('approvals')


def test_lost_response_repreview_adopts_without_duplicate(enrollment):
    svc,o,f,s,_=enrollment;p=preview(svc,f);s.fail='after_spool'
    with pytest.raises(OSError):svc.confirm(p['review_id'],'new',confirmed=True,values=values(p))
    with pytest.raises(ValueError):svc.confirm(p['review_id'],'new',confirmed=True,values=values(p))
    s.fail=None;p=preview(svc,f)
    result=svc.confirm(p['review_id'],'new',confirmed=True,values=values(p))
    assert result['remaining_mg']==840123 and s.posts.count('spool')==1


def test_concurrent_double_submit_one_spool(enrollment):
    svc,o,f,s,_=enrollment;p=preview(svc,f)
    with ThreadPoolExecutor(2) as pool:
        rows=list(pool.map(lambda _:svc.confirm(p['review_id'],'new',confirmed=True,values=values(p)),range(2)))
    assert rows[0]==rows[1] and s.posts.count('spool')==1


def test_second_side_balance_changed_blocks_pair(enrollment):
    svc,o,f,s,_=enrollment;f.set(decoded('creality'));p=preview(svc,f)
    first=svc.confirm(p['review_id'],'new',confirmed=True,values=values(p));f.set(decoded('creality',1));p=preview(svc,f)
    # An actual remote update reconciled through the first side invalidates the cached target.
    f.set(decoded('creality'));s.rows['spool'][0]['remaining_weight']=600
    RfidWorker(o,[URL],client_factory=s,interactive=True).scan('a','0');f.set(decoded('creality',1))
    with pytest.raises(ValueError,match='Остаток'):svc.confirm(p['review_id'],'pair',confirmed=True,spool_id=first['spool_id'])
    assert s.posts.count('spool')==1


def test_new_same_product_still_requires_confirmation(enrollment):
    svc,o,f,s,_=enrollment;p=preview(svc,f);svc.confirm(p['review_id'],'new',confirmed=True,values=values(p))
    f.set(bambu('04998877',identity=2))
    with pytest.raises(ValueError,match='Подтвердите'):RfidWorker(o,[URL],client_factory=s,interactive=True).scan('a','0')
    assert len(s.rows['spool'])==1
