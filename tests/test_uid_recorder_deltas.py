"""Regression: Klipper omits unchanged filename when the same file starts again."""
import pytest
from test_accounting import setup_plan
from tracker_uid_recorder import MotionStreamRecorder,StreamError


@pytest.mark.parametrize('initial,filename,expected',[
    ('complete','job.gcode',1),('cancelled','job.gcode',1),
    ('standby','job.gcode',1),('standby','',0),
    ('printing','job.gcode',0),('paused','job.gcode',0),('error','job.gcode',0),
])
def test_delta_start_uses_only_current_connection_filename(tmp_path,initial,filename,expected):
    run(tmp_path,initial,filename,[{'state':'printing'}],expected)


def test_repeated_same_filename_creates_distinct_observed_starts(tmp_path):
    starts=run(tmp_path,'complete','job.gcode',[
        {'state':'printing'}, {'state':'complete'}, {'state':'printing'},
    ],2)
    assert len({s['capture_id'] for s in starts})==2


def test_explicitly_cleared_filename_cannot_reuse_old_name(tmp_path):
    run(tmp_path,'complete','job.gcode',[{'filename':''},{'state':'printing'}],0)


def run(tmp_path,initial,filename,deltas,expected):
    store,*_=setup_plan(tmp_path);starts=[]
    class Lifecycle:
        def start(self,pid,**kw):starts.append(kw)
        def disconnected(self,*args):pass
    recorder=MotionStreamRecorder(store,Lifecycle(),'a',channels=['0'])
    class Socket:
        messages=[{'id':10,'result':{'status':{'print_stats':{'state':initial,'filename':filename}}}},
            *[{'id':n,'result':{}} for n in range(1,5)],
            *[{'method':'notify_tracker_status','params':{'status':{'print_stats':d}}} for d in deltas]]
        def send(self,payload):pass
        def receive(self):
            if self.messages:return self.messages.pop(0)
            raise StreamError('fixture EOF')
    try:
        before=store.read()
        with pytest.raises(StreamError,match='fixture EOF'):recorder._capture(Socket(),before['printer'])
        assert len(starts)==expected
        assert all(s['filename']=='job.gcode' for s in starts)
        assert store.read()==before
        return starts
    finally:recorder.stop()
