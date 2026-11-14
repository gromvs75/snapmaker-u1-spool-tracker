from copy import deepcopy
import pytest
from tracker_uid_collectors import ProfileHistory,ReadOnlyMoonraker,create_workers
from tracker_uid_recorder import MotionStreamRecorder


class Client:
    def __init__(self):
        self.job=dict(job_id='1',start_time=100.,filename='same.gcode',status='in_progress')
        self.state='printing';self.map=[0,1,2,3];self.replenished=[0,1,2,3];self.calls=0;self.fault=None
    def history(self):return [dict(self.job)]
    def status(self):return dict(print_stats=dict(state=self.state,filename=self.job['filename']),print_task_config=dict(extruder_map_table=self.map,extruders_replenished=self.replenished))
    def inspect(self,filename):
        self.calls+=1
        if self.fault=='error':raise ValueError('Invalid G-code')
        if self.fault=='restart':self.job['start_time']+=1
        if self.fault=='mapping':self.map=[1,0,2,3]
        return dict(logical_weights=[1]*4,parameters=[dict(diameter_mm=1.75,density_g_cm3=1.24)]*4,filament_type='PLA;PLA;PLA;PLA',file_sha256='test')


def test_verified_profile_is_bound_to_history_identity_and_reused():
    from types import SimpleNamespace
    store=SimpleNamespace();c=Client();reader=ProfileHistory(c,store)
    reader();profile=store._motion_slicer_profile;reader()
    assert store._motion_slicer_profile is profile and c.calls==1
    c.job.update(job_id='2',start_time=150.)
    reader();assert store._motion_slicer_profile is not profile and c.calls==2
    assert store._motion_slicer_profile['started_at']==150.
    c.state='complete';c.job['status']='completed';reader()
    assert store._motion_slicer_profile is not None


@pytest.mark.parametrize('fault',['error','restart','mapping'])
def test_changed_or_unverifiable_profile_never_available(fault):
    from types import SimpleNamespace
    store=SimpleNamespace();c=Client();c.fault=fault;reader=ProfileHistory(c,store)
    with pytest.raises(ValueError):reader()
    assert store._motion_slicer_profile is None


def test_auto_transition_clears_profile_without_relaxing_accounting():
    from types import SimpleNamespace
    store=SimpleNamespace();c=Client();reader=ProfileHistory(c,store);reader()
    c.replenished=[0,1,2,1]
    with pytest.raises(ValueError,match='Automatic'):reader()
    assert store._motion_slicer_profile is None


def test_file_hash_and_parameters_require_stable_metadata():
    from io import BytesIO
    raw=b'; filament used [g] = 1,0,0,0\n; filament_density = 1.24\n; filament_diameter = 1.75\n'
    metadata=dict(size=len(raw),modified=10.,filament_type='PLA',slicer='OrcaSlicer')
    class Opener:
        def open(self,request,timeout):
            assert request.get_method()=='GET'
            return BytesIO(raw)
    client=ReadOnlyMoonraker('http://127.0.0.1:7125');client.opener=Opener();client.read=lambda path:dict(metadata)
    assert client.inspect('test.gcode')['parameters']==[dict(diameter_mm=1.75,density_g_cm3=1.24),None,None,None]
    calls=[]
    def changed(path):
        calls.append(path);return dict(metadata,modified=float(len(calls)))
    client.read=changed
    with pytest.raises(ValueError,match='changed'):client.inspect('test.gcode')


def test_recorder_has_no_legacy_write_path_and_logs_are_isolated(tmp_path):
    from types import SimpleNamespace
    import inspect
    assert 'from accounting import' not in inspect.getsource(MotionStreamRecorder)
    a=MotionStreamRecorder(SimpleNamespace(directory=tmp_path/'a'),object(),'a')
    b=MotionStreamRecorder(SimpleNamespace(directory=tmp_path/'b'),object(),'b')
    try:
        a._write('only_a');b._write('only_b')
        assert 'only_b' not in (tmp_path/'a/motion-diagnostic.jsonl').read_text()
        assert 'only_a' not in (tmp_path/'b/motion-diagnostic.jsonl').read_text()
    finally:a.stop();b.stop()


def test_replacement_mode_change_is_not_silently_ignored():
    from types import SimpleNamespace
    class ModeClient(Client):
        mode=True
        def status(self):
            value=super().status();value['print_task_config']['auto_replenish_filament']=self.mode;return value
    saved=[];c=ModeClient();store=SimpleNamespace();reader=ProfileHistory(c,store,lambda job,p:saved.append(p))
    reader();assert saved[-1]['auto_replenish'] is True
    c.mode=False
    with pytest.raises(ValueError,match='mode changed'):reader()
    assert saved[-1]['auto_replenish'] is False and store._motion_slicer_profile is None
