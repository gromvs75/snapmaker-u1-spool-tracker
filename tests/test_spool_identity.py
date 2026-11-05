import math

import pytest

from backup import create_backup, parse_backup
from spool_identity import calibration, estimate_grams, read_tag_uids, tag_uid
from storage import Store, StorageError


def test_tag_scanner_never_guesses_missing_busy_or_invalid_tags():
    data = {'info': [{'CARD_UID': [1, 2, 3, 4]}, {'CARD_UID': 0},
                     {'CARD_UID': [5, 6, 7, 8]}, {'CARD_UID': [1, 2, 3, 999]}], 'state': [0, 0, 1, 0]}
    assert read_tag_uids(data) == ['01020304', None, None, None]
    assert tag_uid('01:02:03:04') == '01020304'
    assert calibration({'identity_mode': 'manual_confirmed'})['identity_mode'] == 'manual_confirmed'
    with pytest.raises(ValueError):
        calibration({'identity_mode': 'manual_confirmed', 'uid': '01020304'})


def test_calibrated_weight_is_volume_density_estimate_and_requires_inputs():
    value = {'uid': None, 'diameter_mm': 1.75, 'density_g_cm3': 1.24}
    assert estimate_grams(1000, value) == pytest.approx(math.pi * .875**2 * 1.24)
    with pytest.raises(ValueError):
        estimate_grams(1000, {'diameter_mm': 1.75})
    for density in [0, float('inf'), float('nan'), True, -1]:
        with pytest.raises(ValueError):
            calibration({'density_g_cm3': density})


def test_binding_roundtrips_backup_and_duplicate_tags_fail_closed(tmp_path):
    store = Store(tmp_path / 'data')
    def seed(db):
        db['spools']['a'] = {'name': 'A', 'material': 'PLA', 'remaining_g': 100,
                             'calibration': {'uid': '01:02:03:04', 'diameter_mm': 1.75, 'density_g_cm3': 1.24}}
    store.update(seed)
    assert store.read()['spools']['a']['calibration']['uid'] == '01020304'
    document = create_backup(store, 'test')
    import json
    path = tmp_path / 'backup.json'
    path.write_text(json.dumps(document))
    assert parse_backup(path)['spools']['a']['calibration']['density_g_cm3'] == 1.24
    def duplicate(db):
        db['spools']['b'] = {'name': 'B', 'material': 'PLA', 'remaining_g': 100,
                             'calibration': {'uid': '01020304'}}
    with pytest.raises(StorageError, match='multiple spools'):
        store.update(duplicate)
    assert 'b' not in store.read()['spools']


def test_version_two_backup_is_migrated_and_new_schema_is_distinct(tmp_path):
    import json
    store = Store(tmp_path / 'data')
    document = create_backup(store, 'old')
    document['data']['schema_version'] = 2
    path = tmp_path / 'old.json'
    path.write_text(json.dumps(document))
    restored = parse_backup(path)
    assert restored['schema_version'] == 5
