"""Check actual isolated Snorca outputs; never connect to a printer or Store."""
import hashlib
import json
from pathlib import Path
import re
import shutil

from slice_observer import completed_weights
from tool_mapping import MappingError, physical_weights


def main():
    root = Path('/tmp/tracker-real-slice-lab')
    assert (root / 'REAL_SLICE_LAB_ONLY').read_text() == 'offline-cli-only\n'
    output = Path(__file__).resolve().parents[1] / 'output/material-mapping-lab'
    output.mkdir(exist_ok=True)
    rows = []
    for index in range(4):
        path = root / 'mapping-output' / f'plate_{index + 1}.gcode'
        data = path.read_bytes()
        weights = completed_weights(data)
        assert weights[index] > 0
        assert all(weight == 0 for i, weight in enumerate(weights) if i != index)
        tools = sorted(set(map(int, re.findall(r'^T(\d+)\s*$', data.decode(), re.M))))
        assert tools == [index]
        scenarios = {}
        for name, mapping in [('identity', [0, 1, 2, 3]),
                              ('permutation', [2, 0, 3, 1]),
                              ('shared_head', [1, 1, 3, 0])]:
            actual = physical_weights(weights, mapping)
            expected = [0.0] * 4
            expected[mapping[index]] = weights[index]
            assert actual == expected
            scenarios[name] = {'mapping': mapping, 'physical_weights': actual}
        try:
            physical_weights(weights, None)
        except MappingError:
            pass
        else:
            raise AssertionError('Unknown mapping must not silently become identity')
        rows.append({'material_number': index + 1, 'logical_tool': index,
                     'weights': weights, 'tool_commands': tools,
                     'sha256': hashlib.sha256(data).hexdigest(),
                     'synthetic_mapping_checks': scenarios})
        shutil.copy2(path, output / path.name)
    shutil.copy2(root / 'mapping-plates.json', output / 'input-plates.json')
    shutil.copy2(root / 'mapping-slice.log', output / 'slice.log')
    # Deliberately different amounts expose reversed mapping and aggregation bugs.
    assert physical_weights([10, 20, 30, 40], [1, 1, 3, 0]) == [40, 30, 0, 30]
    (output / 'report.json').write_text(json.dumps({
        'real_slicing': rows,
        'physical_mapping_source': 'synthetic only; no physical printer queried',
        'shared_head_check': {'logical': [10, 20, 30, 40],
                              'mapping': [1, 1, 3, 0], 'physical': [40, 30, 0, 30]},
    }, indent=2) + '\n')
    print('PASS: four actual material slots; identity/permutation/shared/unknown mappings')


if __name__ == '__main__':
    main()
