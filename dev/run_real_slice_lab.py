"""Reproduce real Snorca CLI slicing with enforced macOS isolation.

No GUI Snorca, gateway, user presets, uploads or printer commands. Run the
separate TrackerRealSliceLab app to observe live output from these commands.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path('/tmp/tracker-real-slice-lab')
BUNDLE = Path('/Applications/Snapmaker Orca.app')
BINARY = BUNDLE / 'Contents/MacOS/Snapmaker_Orca'
PROFILE = Path(__file__).with_name('snorca_slice_isolation.sb').resolve()


def cube(path, size):
    vertices = [(0, 0, 0), (size, 0, 0), (size, size, 0), (0, size, 0),
                (0, 0, size), (size, 0, size), (size, size, size), (0, size, size)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    lines = ['solid lab_cube']
    for a, b, c in faces:
        x = [vertices[b][i] - vertices[a][i] for i in range(3)]
        y = [vertices[c][i] - vertices[a][i] for i in range(3)]
        normal = [x[1]*y[2]-x[2]*y[1], x[2]*y[0]-x[0]*y[2], x[0]*y[1]-x[1]*y[0]]
        length = sum(v*v for v in normal)**.5
        lines += ['facet normal ' + ' '.join(str(v/length) for v in normal), 'outer loop']
        lines += ['vertex ' + ' '.join(map(str, vertices[i])) for i in (a, b, c)]
        lines += ['endloop', 'endfacet']
    path.write_text('\n'.join(lines + ['endsolid lab_cube']) + '\n')


def prepare():
    if ROOT.is_symlink():
        raise RuntimeError('Lab root must not be a symlink')
    ROOT.mkdir(exist_ok=True)
    marker = ROOT / 'REAL_SLICE_LAB_ONLY'
    if any(ROOT.iterdir()) and not marker.exists():
        raise RuntimeError('Refusing an existing unmarked directory')
    if marker.exists() and marker.read_text() != 'offline-cli-only\n':
        raise RuntimeError('Wrong lab marker')
    marker.write_text('offline-cli-only\n')
    for name in ('data', 'tmp', 'output', 'evidence'):
        (ROOT / name).mkdir(exist_ok=True)
    catalog = {}
    for path in (BUNDLE / 'Contents/Resources/profiles').rglob('*.json'):
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            if isinstance(data, dict) and 'name' in data:
                catalog[data['name']] = data
        except (ValueError, UnicodeError):
            continue

    def flattened(name, seen=()):
        if name in seen:
            raise ValueError('Profile inheritance cycle')
        data = catalog[name]
        result = flattened(data['inherits'], seen + (name,)) if data.get('inherits') else {}
        result.update(data)
        result.pop('inherits', None)
        return result

    profiles = {key: flattened(name) for key, name in [
        ('machine', 'Snapmaker U1 (0.4 nozzle)'),
        ('process', '0.20mm Standard @Snapmaker U1 (0.4 nozzle)'),
        ('filament', 'Generic PLA')]}
    # normalize_fdm dereferences nozzle_diameter when wipe_tower_filament exists,
    # even for a standalone process profile. Copy the matching factory value.
    profiles['process']['nozzle_diameter'] = profiles['machine']['nozzle_diameter']
    for key, field in [('machine', 'printer_settings_id'), ('process', 'print_settings_id'),
                       ('filament', 'filament_settings_id')]:
        data = profiles[key]
        data[field] = [data['name']] if key == 'filament' else data['name']
        data['version'] = '2.4.1.0'
        (ROOT / (key + '.json')).write_text(json.dumps(data, indent=2))
    cube(ROOT / 'cube.stl', 10)
    cube(ROOT / 'cube20.stl', 20)
    plates = [{'plate_name': name, 'need_arrange': False, 'objects': [
        {'path': str(ROOT / file), 'count': 1, 'filaments': [1],
         'pos_x': [100], 'pos_y': [100], 'pos_z': [0]}]}
        for name, file in [('Small', 'cube.stl'), ('Large', 'cube20.stl')]]
    (ROOT / 'two-plates.json').write_text(json.dumps({'plates': plates}, indent=2))


def run(case):
    if (ROOT / 'REAL_SLICE_LAB_ONLY').read_text() != 'offline-cli-only\n':
        raise RuntimeError('Unmarked lab')
    args = ['/usr/bin/sandbox-exec', '-f', str(PROFILE), str(BINARY), '--debug', '3',
            '--datadir', str(ROOT / 'data'), '--load-settings',
            str(ROOT / 'machine.json') + ';' + str(ROOT / 'process.json'),
            '--load-filaments', str(ROOT / 'filament.json'), '--slice', '0',
            '--outputdir', str(ROOT / 'output')]
    if case == 'plates':
        args += ['--load-assemble-list', str(ROOT / 'two-plates.json')]
    else:
        args += [str(ROOT / ('cube20.stl' if case == 'reslice' else 'cube.stl'))]
    env = dict(os.environ, TMPDIR=str(ROOT / 'tmp'))
    with (ROOT / (case + '-reproduce.log')).open('w') as log:
        completed = subprocess.run(args, cwd=ROOT, env=env, stdout=log,
                                   stderr=subprocess.STDOUT, timeout=120)
    completed.check_returncode()
    print(json.dumps({'case': case, 'exit_code': completed.returncode,
                      'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (ROOT / 'output').glob('plate_*.gcode')}}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'first', 'reslice', 'plates'])
    action = parser.parse_args().action
    if action == 'prepare':
        prepare()
    else:
        run(action)
