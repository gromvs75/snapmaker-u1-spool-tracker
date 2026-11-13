import base64
import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from tracker_uid_runtime import AccountingOwner
from tracker_uid_sender import Sender
from test_uid_accounting import snapshot
from test_uid_motion_adapter import evidence
from test_accounting import setup_plan

URL='http://127.0.0.1:18899'
class Fleet:
    def snapshot(self):return {pid:snapshot(pid,{}) for pid in ('a','b')}

class Fake:
    def __init__(self):self.balance=500.;self.writes=[];self.fault='';self.entered=threading.Event();self.release=threading.Event()
    def item(self):return dict(id=42,remaining_weight=self.balance,filament=dict(name='Test',material='PLA'))
    def request(self,method,path,body=None):
        if method=='GET':
            if self.fault=='offline':raise OSError('offline')
            if self.fault=='slow_read':self.entered.set();assert self.release.wait(5)
            return ({'version':'0.27.1'} if path=='/info' else self.item()),{}
        self.writes.append(copy.deepcopy(body))
        if self.fault!='drop_before':self.balance-=body['use_weight']
        if self.fault=='slow_write':self.entered.set();assert self.release.wait(5)
        if self.fault in ('drop_before','drop_after','http_error'):raise OSError('unknown write outcome')
        if self.fault=='bad_reply':return {'id':999},{}
        return self.item(),{}

@pytest.fixture
def bench(tmp_path):
    store,*_=setup_plan(tmp_path);path=tmp_path/'uid.sqlite';owner=AccountingOwner(path,Fleet())
    cache=owner.call('cache_catalog',URL,{'42':dict(id=42,name='Test',material='PLA',color=None,remaining_g=500,archived=False)})
    remote=owner.call('create_spool','Test',500,remote=dict(url=URL,id=42,revision=cache['revision']),assignment=dict(printer_id='a',channel='0',expected_version='',confirmed=True))
    owner.call('register','04112233','RFID preserved',200000)
    owner.call('create_spool','Local B',500,details={'material':'PLA'},assignment=dict(printer_id='b',channel='0',expected_version='',confirmed=True))
    def usage(pid='a',run=0):
        e=evidence(store);e['start']=owner.call('inventory_snapshot',pid);e['capture_id']=f'{pid}-{run}';e['terminal_state']='completed'
        start=1010.+100*run;e['profile']['started_at']=start
        owner.call('start',pid,filename='job.gcode',observed_at=start,capture_id=e['capture_id'],epoch=e['epoch'],start=e['start'],channels=['0'])
        owner.call('terminal',pid,e)
        h=[dict(job_id=f'{pid}-{run}',start_time=start,filename='job.gcode',status='completed')]
        owner.call('history',pid,h)
        return h
    usage();fake=Fake();sender=Sender(owner,[URL],client_factory=lambda url:fake)
    yield owner,fake,sender,usage,path,remote
    sender.stop();owner.close()


def decision(owner,action='approve',row=None,request_id='decision',note='Checked on test server'):
    row=row or owner.call('delivery_list')[0]
    return owner.call('delivery_decide',row['operation_id'],row['revision'],action,note,request_id,True)


def test_send_and_duplicate_event_do_not_double_debit(bench):
    o,f,s,usage,_,remote=bench;before=o.call('inspect');row=decision(o)
    assert s.send_one()=='sent'
    assert s.send_one()=='idle'
    assert f.balance==pytest.approx(499.702) and f.writes==[{'use_weight':.298}]
    for _ in range(3):o.call('history','a',[dict(job_id='a-0',start_time=1010.,filename='job.gcode',status='completed')])
    assert o.call('inspect')==before
    assert len(o.call('delivery_list'))==1
    audit=o.call('delivery_audit');assert [r['state'] for r in audit]==['pending','sending','sent']

@pytest.mark.parametrize('fault',['drop_before','drop_after','http_error','bad_reply'])
def test_unknown_write_never_automatically_retries(bench,fault):
    o,f,s,*_=bench;decision(o);f.fault=fault
    assert s.send_one()=='uncertain'
    f.fault=''
    for _ in range(5):assert s.send_one()=='blocked'
    assert len(f.writes)==1
    assert o.call('inspect')['debits'][0]['delta_mg']==298


def test_unavailable_read_is_safe_to_retry(bench):
    o,f,s,*_=bench;decision(o);f.fault='offline'
    assert s.send_one()=='unavailable' and not f.writes
    assert o.call('delivery_list')[0]['state']=='pending'
    f.fault='';assert s.send_one()=='sent'


def test_manual_applied_does_not_send_or_change_local_usage(bench):
    o,f,s,*_=bench;decision(o);f.fault='drop_after';s.send_one();f.fault=''
    before=o.call('inspect');decision(o,'applied',request_id='resolve')
    assert s.send_one()=='idle' and len(f.writes)==1 and o.call('inspect')==before


def test_manual_not_applied_explicitly_releases_one_new_attempt(bench):
    o,f,s,*_=bench;decision(o);f.fault='drop_before';s.send_one();old=o.call('delivery_list')[0]
    receipt=decision(o,'not_applied',old,'resolve')
    assert decision(o,'not_applied',old,'resolve')==receipt
    f.fault='';assert s.send_one()=='sent' and len(f.writes)==2
    assert f.balance==pytest.approx(499.702)
    assert decision(o,'not_applied',old,'resolve')==receipt
    assert s.send_one()=='idle'
    with pytest.raises(ValueError):decision(o,'not_applied',old,'different-request')
    with pytest.raises(ValueError):decision(o,'applied',old,'resolve')


def test_unconfirmed_or_empty_note_cannot_release(bench):
    o,*_=bench;row=o.call('delivery_list')[0]
    for confirmed,note in ((False,'checked'),(True,''),(True,'  ')):
        with pytest.raises(ValueError):o.call('delivery_decide',row['operation_id'],row['revision'],'approve',note,'x',confirmed)
    assert o.call('delivery_list')[0]['state']=='held'


def test_global_uncertainty_blocks_next_printer_but_local_accounting_continues(bench):
    o,f,s,usage,*_=bench;decision(o);f.fault='drop_after';s.send_one()
    usage('b');usage('a',1)
    second=o.call('delivery_list')[1];decision(o,row=second,request_id='next')
    assert s.send_one()=='blocked' and len(f.writes)==1
    assert len(o.call('inspect')['debits'])==3
    assert next(s for s in o.call('inspect')['spools'] if s['uid'])['remaining_mg']==200000

@pytest.mark.parametrize('snapshot_state',['held','pending','sending','sent'])
def test_reopened_backup_cannot_replay_old_operations(bench,tmp_path,snapshot_state):
    o,f,s,_,path,*_=bench
    if snapshot_state!='held':decision(o)
    if snapshot_state=='sending':
        row=o.call('delivery_list')[0];o.call('delivery_claim',row['operation_id'],row['revision'])
    if snapshot_state=='sent':s.send_one()
    backup=o.call('export_backup')
    if snapshot_state in ('held','pending'):
        if snapshot_state=='held':decision(o)
        assert s.send_one()=='sent'
    restored=tmp_path/'restored.sqlite';restored.write_bytes(base64.b64decode(backup['base64']))
    other=AccountingOwner(restored,Fleet());worker=Sender(other,[URL],client_factory=lambda _:f)
    try:
        before=len(f.writes)
        assert worker.send_one()==('idle' if snapshot_state=='sent' else 'blocked')
        assert len(f.writes)==before
        assert other.call('delivery_list')[0]['state']==('sent' if snapshot_state=='sent' else 'uncertain')
    finally:worker.stop();other.close()


def test_restart_after_durable_claim_blocks_and_stale_completion_rejected(bench):
    o,f,s,_,path,*_=bench;decision(o);row=o.call('delivery_list')[0]
    claim=o.call('delivery_claim',row['operation_id'],row['revision']);o.close()
    restarted=AccountingOwner(path,Fleet())
    try:
        with pytest.raises(ValueError):restarted.call('delivery_finish',row['operation_id'],claim['attempt'],True)
        assert Sender(restarted,[URL],client_factory=lambda _:f).send_one()=='blocked'
        assert not f.writes
    finally:restarted.close()


def test_two_workers_claim_once_and_network_does_not_block_sqlite(bench):
    o,f,s,usage,*_=bench;decision(o);f.fault='slow_write'
    second=Sender(o,[URL],client_factory=lambda _:f)
    with ThreadPoolExecutor(2) as pool:
        future=pool.submit(s.send_one);assert f.entered.wait(3)
        assert second.send_one()=='blocked'
        usage('b');assert len(o.call('inspect')['debits'])==2
        with pytest.raises(ValueError):decision(o,'applied',request_id='during-flight')
        f.release.set();assert future.result(3)=='sent'
    assert len(f.writes)==1


def test_cancel_resolution_does_not_refund_local_balance(bench):
    o,f,s,*_=bench;decision(o);f.fault='drop_after';s.send_one();before=o.call('inspect')
    decision(o,'cancel',request_id='cancel');assert s.send_one()=='idle'
    assert o.call('inspect')==before and o.call('delivery_list')[0]['state']=='resolved'


def test_allowlist_prevents_writes_to_unapproved_server(bench):
    o,f,*_=bench;decision(o)
    assert Sender(o,['http://127.0.0.1:19999'],client_factory=lambda _:f).send_one()=='idle'
    assert not f.writes
