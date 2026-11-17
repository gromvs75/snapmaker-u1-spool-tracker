import json
import zipfile

import pytest

from dev.prepare_bed_marker_project import CONFIG, prepare
from slice_bed_marker import PROFILE_COMMENT


def test_only_comment_in_new_project_changes(tmp_path):
    original = tmp_path/'input.3mf'; target = tmp_path/'output.3mf'
    settings = dict(machine_start_gcode='PRINT_START\nG28\n', other=['unchanged'])
    with zipfile.ZipFile(original, 'w') as z:
        z.writestr(CONFIG,json.dumps(settings))
        z.writestr('3D/model.model',b'model bytes')
    before=original.read_bytes()
    prepare(original,target)
    assert original.read_bytes()==before
    with zipfile.ZipFile(target) as z:
        changed=json.loads(z.read(CONFIG))
        assert changed==dict(settings,machine_start_gcode=PROFILE_COMMENT+'\n'+settings['machine_start_gcode'])
        assert z.read('3D/model.model')==b'model bytes'
    with pytest.raises(ValueError):prepare(original,original)
    with pytest.raises(ValueError):prepare(original,target)
    # Re-preparing a marked copy doesn't add a duplicate marker.
    second=tmp_path/'second.3mf';prepare(target,second)
    with zipfile.ZipFile(second) as z:assert json.loads(z.read(CONFIG))==changed


def test_refuse_literal_or_conflicting_existing_marker(tmp_path):
    source=tmp_path/'input.3mf'
    with zipfile.ZipFile(source,'w') as z:
        z.writestr(CONFIG,json.dumps(dict(machine_start_gcode='; TRACKER_BED_V1 = 1\nG28')))
    with pytest.raises(ValueError):prepare(source,tmp_path/'output.3mf')
    assert not (tmp_path/'output.3mf').exists()
