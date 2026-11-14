"""Research protocol only, never imported by production accounting."""
from itertools import permutations
import pytest
from dev.labs.uid_autorefill_boundary_bench.barrier_protocol import Source, Receiver


def fixture():
    s=Source();packets=[s.packet(3,1,2,100),s.packet(3,2,3,2),s.packet(1,4,5,20)]
    return s,packets,s.barrier('pause',10)


def test_order_duplicates_and_lost_packets():
    s,packets,b=fixture()
    for order in permutations([*packets,b]):
        r=Receiver(s.epoch)
        for obj in order:
            handler=r.barrier if 'id' in obj else r.packet
            handler(obj);handler(obj)
        assert r.result('pause')['boundary_proven']
        assert not r.result('pause')['authorizes_debit']
    for missing in range(3):
        r=Receiver(s.epoch);r.barrier(b)
        for i,p in enumerate(packets):
            if i!=missing:r.packet(p)
        assert not r.result('pause')['boundary_proven']


@pytest.mark.parametrize('fault',['epoch','clock','head','scope','conflict','overlap','fence'])
def test_invalid_evidence_invalidates_capture(fault):
    s,p,b=fixture();r=Receiver(s.epoch);r.packet(p[0])
    with pytest.raises(ValueError):
        if fault=='epoch':r.packet(dict(p[1],epoch='new'))
        elif fault=='clock':r.packet(dict(p[1],clock='arrival'))
        elif fault=='head':r.packet(dict(p[1],head=7))
        elif fault=='scope':r.barrier(dict(b,heads=[1,3]))
        elif fault=='conflict':r.packet(dict(p[0],length=99))
        elif fault=='overlap':r.packet(dict(p[1],start=1.5))
        else:r.barrier(dict(b,fence=1.5))
    assert r.failure and not r.result('pause')['boundary_proven']


def test_disconnect_revokes_proof_and_cannot_be_repaired_by_replay():
    s,p,b=fixture();r=Receiver(s.epoch)
    for packet in p:r.packet(packet)
    r.barrier(b);assert r.result('pause')['boundary_proven']
    r.disconnect()
    with pytest.raises(ValueError):r.barrier(b)
    with pytest.raises(ValueError):r.packet(p[0])
    assert not r.result('pause')['boundary_proven']


def test_source_barrier_requires_emission_and_locks_earlier_time():
    s=Source();s.packet(3,1,2,1,delayed=True)
    with pytest.raises(ValueError):s.barrier('b',10)
    s.flush();b=s.barrier('b',10)
    assert s.barrier('b',10)==b
    with pytest.raises(ValueError):s.barrier('b',11)
    with pytest.raises(ValueError):s.packet(1,9,11,3)
    s.packet(1,11,12,2);assert s.barrier('b',10)==b
    assert s.barrier('c',20)['last_seq']==2


def test_late_evidence_cannot_contradict_already_certified_fence():
    s,p,b=fixture();r=Receiver(s.epoch)
    for packet in p:r.packet(packet)
    r.barrier(b)
    with pytest.raises(ValueError):r.packet(dict(p[2],seq=4,start=6,end=7))
    assert not r.result('pause')['boundary_proven']
    r=Receiver(s.epoch);r.barrier(b)
    with pytest.raises(ValueError):r.barrier(dict(b,id='other',last_seq=4))
    assert not r.result('pause')['boundary_proven']
