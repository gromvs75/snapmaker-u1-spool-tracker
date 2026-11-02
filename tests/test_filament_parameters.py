from io import BytesIO
import pytest
from gcode import parse_filament_parameters_handle


def parse(text):
    return parse_filament_parameters_handle(BytesIO(text.encode()))


def test_reads_per_tool_generic_pla_parameters_without_brand_assumptions():
    assert parse('; filament_density = 1.24,1.24\n; filament_diameter = 1.75,1.75\n') == [
        {'diameter_mm': 1.75, 'density_g_cm3': 1.24}, {'diameter_mm': 1.75, 'density_g_cm3': 1.24}]


@pytest.mark.parametrize('text', [
    '', '; filament_density = 1.24\n',
    '; filament_density = 1.24,1.24\n; filament_diameter = 1.75\n',
    '; filament_density = nan\n; filament_diameter = 1.75\n',
    '; filament_density = 1.24\n; filament_density = 1.3\n; filament_diameter = 1.75\n',
    '; filament_density = 1.24\n; filament_diameter = 99\n',
])
def test_missing_conflicting_or_invalid_settings_return_unknown(text):
    assert parse(text) is None


def test_inspection_reads_parameters_from_the_verified_file():
    import json
    from moonraker import MoonrakerClient
    payload = (b'; filament used [g] = 1,2,0,0\n'
               b'; filament_density = 1.24,1.24,1.24,1.24\n'
               b'; filament_diameter = 1.75,1.75,1.75,1.75\n')
    metadata = {'size': len(payload), 'modified': 1234.0, 'slicer': 'SnapmakerOrca',
                'filament_type': 'PLA;PLA;PLA;PLA', 'filament_weight': [1, 2, 0, 0]}
    class Opener:
        def open(self, url, timeout):
            return BytesIO(json.dumps({'result': metadata}).encode()) if '/metadata?' in url else BytesIO(payload)
    client = MoonrakerClient('example.local', 7125, opener=Opener())
    _, _, weights = client.inspect_gcode('test.gcode')
    assert weights == [1, 2, 0, 0]
    assert client.last_inspection_metadata['filament_parameters'][0]['density_g_cm3'] == 1.24
    assert client.last_inspection_metadata['filament_parameters'][1]['diameter_mm'] == 1.75
