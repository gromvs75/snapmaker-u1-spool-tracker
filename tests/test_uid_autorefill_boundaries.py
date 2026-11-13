"""Synthetic research cases, plus reported aggregate reproduction through UID queue."""
from dataclasses import replace
import pytest
from dev.labs.uid_autorefill_boundary_bench.model import Checkpoint, printing_interval, automatic_boundary, reported_drift
from motion_analysis import HeadMotionSummary, MotionDataError
from tracker_uid_runtime import AccountingOwner
from test_uid_accounting import snapshot
from test_uid_motion_adapter import evidence
from test_accounting import setup_plan


def point(heads,printer,fence):return Checkpoint(tuple(heads),printer,'proven-motion-clock',fence,True,('s0','s1','s2','s3'),'epoch1')

def boundary(a,b,**kwargs):
    return automatic_boundary(a,b,source_head=3,target_head=1,runout=True,mapping=[0,1,2,1],**kwargs)


def test_reported_persistent_offset_is_not_late_final_packet_or_authorization():
    report=reported_drift()
    assert report['resume_offset_mm']==pytest.approx(12.15997)
    assert abs(report['offset_change_mm'])<1e-8
    assert report['post_resume_counter_delta_mm']==pytest.approx(report['post_resume_motion_delta_mm'])
    assert not report['boundary_proven'] and not report['authorizes_debit']


def test_equal_post_boundary_deltas_do_not_explain_service_motion():
    a=point([0,0,0,100],100,10);b=point([0,20,0,105],112.84003,20)
    c=point([0,120,0,105],212.84003,30)
    assert printing_interval(b,c)['consistent']
    result=boundary(a,b)
    assert not result['consistent'] and not result['authorizes_debit']

@pytest.mark.parametrize('fault',['arrival_clock','late_packet','reconnect','identity_change','unknown_uid','same_fence','reset'])
def test_unproven_windows_reject(fault):
    a=point([0,0,0,100],100,10);b=point([0,100,0,100],200,20)
    if fault=='arrival_clock':b=replace(b,clock='status-receive-time')
    if fault=='late_packet':b=replace(b,settled=False)
    if fault=='reconnect':b=replace(b,epoch='new')
    if fault=='identity_change':b=replace(b,identity=('s0','replacement','s2','s3'))
    if fault=='unknown_uid':b=replace(b,identity=('s0','','s2','s3'))
    if fault=='same_fence':b=replace(b,fence=10)
    if fault=='reset':b=replace(b,printer=0)
    with pytest.raises(ValueError):printing_interval(a,b)


def test_two_independently_explained_transitions_still_not_production_authorization():
    a=point([0,0,0,100],100,10);b=point([0,20,0,105],112,20);c=point([0,120,0,105],212,30)
    d=point([0,125,12,105],220,40)
    first=boundary(a,b,service_heads=(0,20,0,5),service_counter=12,provenance='synthetic_ground_truth')
    second=automatic_boundary(c,d,source_head=1,target_head=2,runout=True,mapping=[0,2,2,2],service_heads=(0,5,12,0),service_counter=8,provenance='synthetic_ground_truth')
    assert first['consistent'] and second['consistent'] and printing_interval(b,c)['consistent']
    assert not first['authorizes_debit'] and not second['authorizes_debit']
    bad=boundary(a,b,service_heads=(0,19,0,6),service_counter=12,provenance='synthetic_ground_truth')
    assert not bad['consistent'] # matching grand total cannot hide head swaps


def test_duplicate_overlap_and_late_arrival_use_event_time():
    summary=HeadMotionSummary();row=[10,1,100,0,[0,0,0],[1,0,0]]
    summary.add(3,[row]);summary.add(1,[[1,1,20,0,[0,0,0],[1,0,0]]])
    # Different head's delayed arrival is not proof of belonging to paused phase.
    assert summary.result()[1]['net_mm']==20
    with pytest.raises(MotionDataError):summary.add(3,[row])


@pytest.mark.parametrize('terminal',['completed','cancelled'])
def test_reported_offset_never_debits_local_or_remote_and_replay_is_safe(tmp_path,terminal):
    store,*_=setup_plan(tmp_path)
    class Fleet:
        def snapshot(self):return {'a':snapshot('a',{})}
    path=tmp_path/'uid.sqlite';owner=AccountingOwner(path,Fleet())
    try:
        cache=owner.call('cache_catalog','http://127.0.0.1:18899',{'42':dict(id=42,name='Bench remote',material='PLA',color=None,remaining_g=500,archived=False)})
        owner.call('create_spool','T3',500,details={'material':'PLA'},assignment=dict(printer_id='a',channel='3',expected_version='',confirmed=True))
        owner.call('create_spool','T1',500,remote=dict(url='http://127.0.0.1:18899',id=42,revision=cache['revision']),assignment=dict(printer_id='a',channel='1',expected_version='',confirmed=True))
        e=evidence(store);e['start']=owner.call('inventory_snapshot','a');e['terminal_state']=terminal
        summary=HeadMotionSummary()
        # Synthetic segments reproduce reported rounded head totals, not raw private packets.
        summary.add(3,[[1,1,6173.473,0,[0,0,0],[1,0,0]]])
        summary.add(1,[[2,1,5555.317,0,[0,0,0],[1,0,0]]])
        e['heads']=summary.result();e['comparison']=summary.compare_printer_total(11716.630119980022)
        assert not e['comparison']['matches']
        owner.call('start','a',filename='job.gcode',observed_at=1010.,capture_id=e['capture_id'],epoch=e['epoch'],start=e['start'],channels=['1','3'])
        owner.call('terminal','a',e)
        history=[dict(job_id='auto-refill',start_time=1010.,filename='job.gcode',status=terminal)]
        for _ in range(3):owner.call('history','a',history)
        report=owner.call('inspect')
        assert not report['debits'] and all(s['remaining_mg']==500000 for s in report['spools'])
        assert any('Motion differs' in r['reason'] for r in report['reviews'])
        assert not owner.call('library_snapshot')['remote_outbox']
    finally:owner.close()
    owner=AccountingOwner(path,Fleet())
    try:
        owner.call('history','a',history)
        assert not owner.call('inspect')['debits'] and not owner.call('library_snapshot')['remote_outbox']
    finally:owner.close()


def test_event_time_partition_is_order_invariant_but_not_debit_evidence():
    from itertools import permutations
    from dev.labs.uid_autorefill_boundary_bench.model import partition_motion
    packets=[dict(id=str(i),head=h,start=t,end=t+1,length=n,clock='motion',epoch='same') for i,(h,t,n) in enumerate([(3,2,2),(3,10,5),(1,11,20),(1,21,100)])]
    for order in permutations(packets):
        r=partition_motion([*order,order[0]],pause_fence=10,resume_fence=20,clock='motion',epoch='same')
        assert sum(p['length'] for p in r['groups']['service'])==25
        assert r['fully_partitioned'] and not r['authorizes_debit']


def test_fence_crossing_cannot_be_split_proportionally_or_replayed_conflictingly():
    from dev.labs.uid_autorefill_boundary_bench.model import partition_motion
    p=dict(id='crossing',head=3,start=9,end=11,length=10,clock='motion',epoch='same')
    kw=dict(pause_fence=10,resume_fence=20,clock='motion',epoch='same')
    assert not partition_motion([p],**kw)['fully_partitioned']
    for other in [dict(p,length=11),dict(p,id='overlap',start=10,end=12),dict(p,epoch='reconnected')]:
        with pytest.raises(ValueError):partition_motion([p,other],**kw)
