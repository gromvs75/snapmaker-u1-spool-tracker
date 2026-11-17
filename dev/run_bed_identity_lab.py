"""Real Snorca engine -> embedded bed identity -> Tracker, offline macOS lab.

Uses factory profiles only. Does not modify the installed slicer or user presets.
All children run under sandbox-exec with network denied and writes limited to
a freshly created temporary directory. No upload/start command is invoked.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
import run_real_slice_lab as lab
from slice_bed_marker import PROFILE_COMMENT
from slice_observer import SliceObserver


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix='tracker-bed-engine-')).resolve()
    lab.ROOT = root
    # prepare() requires its marker before reusing an existing directory.
    (root/'REAL_SLICE_LAB_ONLY').write_text('offline-cli-only\n')
    lab.prepare()
    machine = json.loads((root/'machine.json').read_text())
    original_start = machine['machine_start_gcode']
    machine['machine_start_gcode'] = PROFILE_COMMENT+'\n'+original_start
    (root/'marked-machine.json').write_text(json.dumps(machine))
    assembly = json.loads((root/'two-plates.json').read_text())
    small, large = assembly['plates']
    # Identical names and two identical geometries must not conflate identities.
    assembly['plates'] = [dict(p, plate_name='Same') for p in (small, large, small)]
    (root/'three.json').write_text(json.dumps(assembly))
    reordered = dict(plates=list(reversed(assembly['plates'][:2]))+[assembly['plates'][2]])
    (root/'reordered.json').write_text(json.dumps(reordered))
    profile = root/'isolation.sb'
    profile.write_text('''(version 1)
(allow default)
(deny network*)
(deny file-write*)
(allow file-write* (subpath (param "LAB_ROOT")) (literal "/dev/null"))
(deny file-read* (subpath "/Users/viktor/Library/Application Support"))
''')
    # Prove the policy is active before invoking the slicer.
    isolation = ['/usr/bin/sandbox-exec', '-D', 'LAB_ROOT='+str(root), '-f', str(profile)]
    probe = '''import socket
try:
 s=socket.socket();s.bind(('127.0.0.1',0))
except PermissionError: pass
else: raise AssertionError('Network was not blocked')
try:
 open('/private/tmp/tracker-bed-denied-write-probe','x')
except PermissionError: pass
else: raise AssertionError('Outside writes were not blocked')
'''
    subprocess.run(isolation+[sys.executable,'-c',probe],check=True,cwd=root)
    report = dict(root=str(root), isolation_verified=True, cases={})
    cases = [('all',0,'three.json',True), ('only2',2,'three.json',True),
             ('only3',3,'three.json',True), ('reslice3',3,'three.json',True),
             ('reorder',0,'reordered.json',True), ('baseline',0,'three.json',False)]
    for name, selected, project, marked in cases:
        dest = root/name; dest.mkdir()
        command = isolation+[str(lab.BINARY),'--datadir',str(root/'data'),
            '--load-settings',str(root/('marked-machine.json' if marked else 'machine.json'))+';'+str(root/'process.json'),
            '--load-filaments',str(root/'filament.json'),'--slice',str(selected),
            '--outputdir',str(dest),'--load-assemble-list',str(root/project)]
        with (root/(name+'.log')).open('w') as log:
            subprocess.run(command,env=dict(os.environ,TMPDIR=str(root/'tmp')),cwd=root,
                           stdout=log,stderr=subprocess.STDOUT,timeout=120,check=True)
        observer_root = root/('observer-'+name)
        folder = observer_root/'project'/'Metadata';folder.mkdir(parents=True)
        expected = [selected] if selected else [1,2,3]
        files = sorted(dest.glob('plate_*.gcode'))
        assert len(files)==len(expected), (name, files)
        for i,source in enumerate(files):
            # Simulate GUI cache naming independently of the actual bed number.
            (folder/f'.900.{47+i}.gcode').write_bytes(source.read_bytes())
        observer = SliceObserver(observer_root,settle_seconds=0)
        observer.poll();entries=observer.poll()
        assert len(entries)==len(expected), (name, observer.entries)
        actual=[e['plate'] for e in entries]
        assert actual==(expected if marked else [None]*len(expected)), (name,actual)
        assert observer.poll()==[]
        report['cases'][name]=dict(plates=actual,weights=[e['weights'] for e in entries],
            hashes=[e['sha256'] for e in entries], no_repeat_event=True)
        print(name,actual,flush=True)
    # Metadata adds no executable printer command or changed movement.
    def commands(path):
        return [s for line in path.read_text().splitlines()
                if (s:=line.split(';',1)[0].strip())]
    for n in [1,2,3]:
        assert commands(root/'all'/f'plate_{n}.gcode')==commands(root/'baseline'/f'plate_{n}.gcode')
    assert report['cases']['all']['weights'][0]==report['cases']['reorder']['weights'][1]
    assert report['cases']['all']['weights'][1]==report['cases']['reorder']['weights'][0]
    report['executable_commands_unchanged']=True
    report['binary_sha256']=hashlib.sha256(lab.BINARY.read_bytes()).hexdigest()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(args.report)


if __name__=='__main__':
    main()
