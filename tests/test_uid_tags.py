"""Observed registration: atomic identity changes, stale decisions and replay."""
import copy
import time
import pytest
from test_uid_accounting import snapshot
from tracker_uid_runtime import AccountingOwner
from tracker_uid_catalog import UidCatalog

class Fleet:
    def __init__(self):
        self.value={'a':snapshot('a',{'0':'04112233'}),'b':snapshot('b',{})}
        for s in self.value.values():s.update(client_session='test',generation=1,epoch='epoch')
        self.value['a']['channels']['0']['sequence']=1
    def snapshot(self):return copy.deepcopy(self.value)

@pytest.fixture
def env(tmp_path):
    f=Fleet();o=AccountingOwner(tmp_path/'db',f)
    yield o,f,tmp_path/'db'
    o.close()

def proof(f,state='standby'):
    return dict(state=state,checked_at=time.monotonic(),connection_token=UidCatalog.connection_token(f.value['a']))

def decision(o,f,**extra):
    p=o.call('tag_preview','a','0','04112233',observation=proof(f))
    return dict(printer_id='a',channel='0',uid=p['uid'],expected_observation=p['observation_revision'],request_id='once',confirmed=True,**extra)

def test_create_and_replay_survives_restart(env):
    o,f,path=env;d=decision(o,f,name='New PLA',material='PLA',remaining_g='500.123')
    r=o.call('tag_register',**d,observation=proof(f))
    assert r['remaining_mg']==500123
    assert o.call('tag_register',**d,observation=proof(f))==r
    o.close();other=AccountingOwner(path,f)
    try:
        assert other.call('tag_register',**d,observation=proof(f))==r
        assert len(other.call('inspect')['spools'])==1
        with pytest.raises(ValueError):other.call('tag_register',**dict(d,name='Changed'),observation=proof(f))
    finally:other.close()

@pytest.mark.parametrize('fault',['offline','absent','uid','sequence','generation','duplicate','printing','paused','unknown','old_proof','wrong_connection'])
def test_changed_observation_blocks_atomic_commit(env,fault):
    o,f,_=env;d=decision(o,f,name='PLA',material='PLA',remaining_g=100);obs=proof(f)
    if fault=='offline':f.value['a']['state']='offline'
    elif fault=='absent':f.value['a']['channels']['0']['state']='absent'
    elif fault=='uid':f.value['a']['channels']['0']['uid']='04AABBCC'
    elif fault in ('sequence',):f.value['a']['channels']['0']['sequence']=2
    elif fault=='generation':f.value['a']['generation']=2;obs=proof(f)
    elif fault=='duplicate':f.value['b']=snapshot('b',{'1':'04112233'})
    elif fault=='old_proof':obs['checked_at']-=10
    elif fault=='wrong_connection':obs['connection_token']='wrong'
    else:obs['state']=fault
    with pytest.raises(ValueError):o.call('tag_register',**d,observation=obs)
    assert o.call('inspect')['spools']==[]

@pytest.mark.parametrize('bad',[{'confirmed':False},{'remaining_g':-1},{'name':''},{'material':''},{'remaining_g':'NaN'}])
def test_invalid_input_creates_nothing(env,bad):
    o,f,_=env;d=decision(o,f,name='PLA',material='PLA',remaining_g=10);d.update(bad)
    with pytest.raises(ValueError):o.call('tag_register',**d,observation=proof(f))
    assert o.call('inspect')['spools']==[]

def test_bind_manual_keeps_balance_details_and_identity(env):
    o,f,path=env
    f.value['a']['channels']['0']={'state':'absent','uid':None}
    o.call('register_manual','Existing',123456,spool_id='existing',details={'material':'PETG','color':'#123456'})
    o.call('assign_manual','a','0','existing',confirmed=True)
    f.value['a']['channels']['0']={'state':'present','uid':'04112233','sequence':2}
    p=o.call('tag_preview','a','0','04112233',observation=proof(f))
    assert not p['can_create'];assert len(p['candidates'])==1
    c=p['candidates'][0]
    d=decision(o,f,spool_id='existing',expected_spool=c['revision'])
    r=o.call('tag_register',**d,observation=proof(f))
    assert (r['spool_id'],r['name'],r['remaining_mg'])==('existing','Existing',123456)
    assert o.call('inspect')['manual_assignments']==[]
    assert o.call('library_snapshot')['spools'][0]['details']['material']=='PETG'
    assert o.call('inspect')['debits']==[]

def test_changed_candidate_and_other_head_assignment_rejected(env):
    o,f,_=env;o.call('register_manual','Existing',100000,spool_id='existing')
    p=o.call('tag_preview','a','0','04112233',observation=proof(f))
    d=decision(o,f,spool_id='existing',expected_spool=p['candidates'][0]['revision'])
    o.call('assign_manual','b','1','existing',confirmed=True)
    with pytest.raises(ValueError):o.call('tag_register',**d,observation=proof(f))
    assert o.call('inspect')['spools'][0]['uid'] is None

def test_parallel_duplicate_requests_create_once(env):
    o,f,_=env;d=decision(o,f,name='PLA',material='PLA',remaining_g=100)
    futures=[o.submit('tag_register',**d,observation=proof(f)) for _ in range(8)]
    assert len({v.result()['spool_id'] for v in futures})==1
    assert len(o.call('inspect')['spools'])==1

def test_active_job_and_temporary_unlock_block_registration(env):
    from tracker_uid_accounting import UidAccounting
    from tracker_uid_library import Library
    from tracker_uid_delivery import Delivery
    from tracker_uid_tags import Tags
    o,f,path=env;o.close()
    c=UidCatalog(path);a=UidAccounting(c);Library(a);Delivery(a);t=Tags(a)
    try:
        c.register('04AABBCC','Printing',100000)
        f.value['a']['channels']['1']={'state':'present','uid':'04AABBCC'}
        k=a.begin('a','job','start',['1'],'capture',f.snapshot())
        with pytest.raises(ValueError):t.preview('a','0','04112233',fleet=f.snapshot(),observation=proof(f))
        a.apply(k,1,{'1':0},state='cancelled',source='capture',basis='executed_gcode')
        c.db.execute("INSERT INTO uid_unlock_windows VALUES(?,'15_minutes',?,0,1)",(k,time.time()+900));c.db.commit()
        with pytest.raises(ValueError):t.preview('a','0','04112233',fleet=f.snapshot(),observation=proof(f))
    finally:c.close()

def test_existing_remote_link_and_ledger_survive_binding(env):
    from tracker_uid_accounting import UidAccounting
    from tracker_uid_library import Library
    from tracker_uid_delivery import Delivery
    from tracker_uid_tags import Tags
    o,f,path=env;o.close()
    c=UidCatalog(path);a=UidAccounting(c);Library(a);Delivery(a);t=Tags(a)
    try:
        c.register_manual('Linked',120000,spool_id='linked')
        # A historical manual job already debited this spool.
        absent=copy.deepcopy(f.value);absent['a']['channels']['0']={'state':'absent','uid':None}
        a.assign_manual('a','0','linked',fleet=absent,confirmed=True)
        k=a.begin('a','old','start',['0'],'capture',absent)
        a.apply(k,1,{'0':1234},state='completed',source='capture',basis='executed_gcode')
        c.db.execute("INSERT INTO uid_remote_links VALUES('linked','http://127.0.0.1:9999',42)");c.db.commit()
        before=list(c.db.execute('SELECT * FROM uid_debits'))
        p=t.preview('a','0','04112233',fleet=f.snapshot(),observation=proof(f))
        r=t.register('a','0','04112233',p['observation_revision'],'bind',fleet=f.snapshot(),observation=proof(f),confirmed=True,spool_id='linked',expected_spool=p['candidates'][0]['revision'])
        assert tuple(c.db.execute('SELECT * FROM uid_remote_links').fetchone())==('linked','http://127.0.0.1:9999',42)
        assert r['remaining_mg']==118766
        assert list(c.db.execute('SELECT * FROM uid_debits'))==before
        assert a.apply(k,1,{'0':1234},state='completed',source='capture',basis='executed_gcode')=='duplicate'
    finally:c.close()
