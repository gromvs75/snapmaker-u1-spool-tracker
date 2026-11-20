import io
import json
import time
from types import SimpleNamespace
import pytest
from tracker_uid_session import Session
from tracker_uid_collectors import ProfileHistory
from tracker_uid_guard import execute
from test_desktop_services import Fleet


@pytest.fixture
def guard(tmp_path):
    s=Session(tmp_path,fleet_factory=Fleet,allowed_urls=['http://127.0.0.1:19101'])
    s.call('save_settings',values=dict(printers=[dict(id='a',name='A',url='http://127.0.0.1:19101')],guard_modes={'a':'strict'}),expected_revision=s.call('settings')['revision'])
    s.call('connect_printers',confirmed=True)
    sid=s.call('create_spool','PLA',1,details={'material':'PLA'},assignment=dict(printer_id='a',channel='0',expected_version='',confirmed=True))['spool_id']
    s.call('guard_arm','a')
    job=dict(job_id='1',start_time=time.time(),filename='one.gcode',status='in_progress')
    profile=dict(file_sha256='a'*64,logical_weights=[10,0,0,0],mapping=[0,1,2,3])
    yield s,job,profile,sid
    s.close()


class Client:
    def __init__(self,job):self.job=dict(job);self.state='printing';self.writes=[];self.lost=False;self.url='http://127.0.0.1:19101';self.opener=self
    def check_stop(self):pass
    def status(self):return dict(print_stats=dict(state=self.state,filename=self.job['filename']))
    def history(self):return [self.job]
    def open(self,request,timeout):
        action=request.full_url.rsplit('/',1)[1];self.writes.append(action)
        self.state={'pause':'paused','resume':'printing','cancel':'cancelled'}[action]
        if self.lost:raise TimeoutError('Response lost after command')
        return io.BytesIO(b'{"result":"ok"}')


def test_strict_pause_resume_is_once_and_never_consumes(guard):
    s,job,p,sid=guard;c=Client(job)
    ticket=s.call('guard_check','a',job,p)
    assert ticket['state']=='pause_requested'
    assert execute(s,'a',c,ticket)['state']=='paused'
    assert c.writes==['pause']
    assert s.call('desktop_snapshot')['monitor']['state']=='paused'
    assert s.call('guard_check','a',job,p)['state']=='paused'
    row=s.call('guard_snapshot','a')['guard']
    decision=s.call('guard_decision','a',row['revision'],'resume',True)
    assert execute(s,'a',c,decision)['state']=='resumed'
    with pytest.raises(ValueError):s.call('guard_decision','a',row['revision'],'resume',True)
    assert c.writes==['pause','resume'] and not s.call('inspect')['debits']
    assert next(x for x in s.call('inspect')['spools'] if x['spool_id']==sid)['remaining_mg']==1000


@pytest.mark.parametrize('fault',['lost','different_job','already_paused'])
def test_unknown_or_changed_printer_never_retries(guard,fault):
    s,job,p,_=guard;c=Client(job);ticket=s.call('guard_check','a',job,p)
    if fault=='lost':c.lost=True
    if fault=='different_job':c.job['start_time']+=1
    if fault=='already_paused':c.state='paused'
    assert execute(s,'a',c,ticket)['state']=='pause_failed'
    c.lost=False
    execute(s,'a',c,ticket)
    assert c.writes==(['pause'] if fault=='lost' else [])
    assert s.call('guard_check','a',job,p)['state']=='pause_failed'


def test_actual_remap_with_repeated_unused_entries_keeps_start_profile(guard):
    s, job, _, _ = guard
    client = Client(job)
    client.status = lambda: dict(print_stats=dict(state='printing', filename=job['filename']),
        print_task_config=dict(extruder_map_table=[2, 0, 2, 3], extruders_replenished=[0, 1, 2, 3]))
    client.inspect = lambda filename: dict(file_sha256='a' * 64, logical_weights=[15.08, 2.36, 0, 0])
    store = SimpleNamespace()
    collect = ProfileHistory(client, store, guard_sink=lambda job, profile: s.call('guard_check', 'a', job, profile))
    collect()
    assert store._motion_slicer_profile['mapping'] == [2, 0, 2, 3]
    assert [row['required_g'] for row in s.call('guard_snapshot', 'a')['guard']['rows']] == [2.36, 0, 15.08, 0]
    assert not s.call('inspect')['debits']


def test_late_start_restore_and_off_do_not_arm_pause(guard):
    s,job,p,_=guard
    job['start_time']-=30
    assert s.call('guard_check','a',job,p)['state']=='warning'
    package=s.call('backup_package');s.call('disconnect_printers',confirmed=True)
    checked=s.call('validate_backup',package=package)
    s.call('restore_backup',package=package,expected_revision=checked['current_revision'],confirmed=True)
    assert s.call('guard_check','a',job,p)['attempt'] is None
    s.call('save_settings',values={'guard_modes':{'a':'off'}},expected_revision=s.call('settings')['revision'])
    job['job_id']='2';job['start_time']=time.time()
    assert s.call('guard_check','a',job,p) is None
    assert not s.call('inspect')['debits']


def test_old_backup_without_guard_table_is_additive(guard,tmp_path):
    import sqlite3,base64,hashlib
    s,*_=guard;s.call('disconnect_printers',confirmed=True);package=s.call('backup_package')
    path=tmp_path/'old.sqlite';path.write_bytes(base64.b64decode(package['base64']))
    db=sqlite3.connect(path);db.execute('DROP TABLE uid_start_checks');db.commit();db.close();raw=path.read_bytes()
    package.update(base64=base64.b64encode(raw).decode(),sha256=hashlib.sha256(raw).hexdigest())
    checked=s.call('validate_backup',package=package);assert checked['migrated_tables']==['uid_start_checks']
