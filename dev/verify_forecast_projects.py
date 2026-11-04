"""Replay saved real slices into a fresh isolated filesystem, never touch originals."""
import json
import os
from pathlib import Path
import tempfile
from forecast_lab_app import ForecastState
from slice_observer import SliceObserver

root = Path(tempfile.mkdtemp(prefix='tracker-project-check-'))
source = Path('/tmp/tracker-gui-slice-lab/tmp/snapmaker_orca_model/Wed_Nov_04/16_35_54#65411#7/Metadata/.65411.0.gcode').read_bytes()
def put(project, plate, stamp):
    p = root/project/'Metadata'/f'.100.{plate}.gcode'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(source)
    os.utime(p, ns=(stamp, stamp))
def poll(observer, state):
    state.accept(observer.poll()); state.accept(observer.poll())
    return state.snapshot()
put('z-old', 0, 1000000000); put('z-old', 1, 1100000000)
put('a-new', 0, 2000000000)
observer = SliceObserver(root, settle_seconds=0); state = ForecastState()
snap = poll(observer,state)
assert snap['project']=='a-new' and len(snap['entries'])==1
put('next',0,3000000000);put('next',1,3100000000)
snap = poll(observer,state)
assert snap['project']=='next' and len(snap['entries'])==2
restart = poll(SliceObserver(root, settle_seconds=0), ForecastState())
assert restart['project']=='next' and len(restart['entries'])==2
Path('output/forecast-verification/project-replay.json').write_text(json.dumps({'root':str(root),'result':snap,'restarted':restart},ensure_ascii=False,indent=2))
print('PASS: real slice replay, older project excluded, two new plates, restart keeps newest project')
