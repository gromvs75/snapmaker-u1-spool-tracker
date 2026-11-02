import copy
import pytest
from motion_allocation import provisional_allocation


def sample():
    heads = [{'head': i, 'net_mm': n} for i, n in enumerate((100, 200, 0, 0))]
    db = {'slots': {'1': 'a', '2': 'b', '3': '', '4': ''}, 'spools': {
        'a': {'name': 'first brand black', 'material': 'PLA', 'calibration': {'identity_mode': 'manual_confirmed', 'uid': None, 'diameter_mm': 1.75, 'density_g_cm3': 1.24}},
        'b': {'name': 'another brand white', 'material': 'PLA', 'calibration': {'identity_mode': 'manual_confirmed', 'uid': None, 'diameter_mm': 1.75, 'density_g_cm3': 1.24}},
    }}
    return heads, db


def test_multiple_generic_untagged_spools_are_assigned_by_slot_not_name():
    heads, db = sample()
    result = provisional_allocation(heads, db, copy.deepcopy(db))
    assert [(x['head'], x['spool_id']) for x in result] == [(0, 'a'), (1, 'b')]
    assert result[0]['estimated_g'] == pytest.approx(.298, abs=.001)
    assert result[1]['estimated_g'] == pytest.approx(.597, abs=.001)
    assert all(x['identity_verified'] is False for x in result)


def test_changed_slot_or_material_is_never_allocated():
    heads, db = sample(); current = copy.deepcopy(db)
    current['slots']['2'] = 'a'
    with pytest.raises(ValueError, match='assignment'): provisional_allocation(heads, db, current)
    current = copy.deepcopy(db); current['spools']['b']['material'] = 'PETG'
    with pytest.raises(ValueError, match='material'): provisional_allocation(heads, db, current)


def test_missing_material_parameters_are_not_invented():
    heads, db = sample(); db['spools']['a'].pop('calibration')
    assert provisional_allocation(heads, db, copy.deepcopy(db))[0]['estimated_g'] is None


def test_generic_slicer_parameters_are_mapped_to_matching_physical_slots():
    heads, db = sample()
    db['spools']['a'].pop('calibration'); db['spools']['b'].pop('calibration')
    profile = {'mapping': [1, 0, 2, 3], 'filament_type': 'PLA;PLA;PLA;PLA', 'logical_weights': [2, 1, 0, 0],
               'parameters': [{'diameter_mm': 1.75, 'density_g_cm3': 1.24} for _ in range(4)]}
    result = provisional_allocation(heads, db, copy.deepcopy(db), profile)
    assert result[0]['estimated_g'] == pytest.approx(.298, abs=.001)
    assert result[1]['estimated_g'] == pytest.approx(.597, abs=.001)
    assert all(x['parameter_source'] == 'slicer_estimate' and not x['identity_verified'] for x in result)
    # A spare physical head has no trustworthy replacement-specific profile.
    profile['mapping'] = [0, 0, 2, 3]
    profile['parameters'][1]['density_g_cm3'] = 1.30
    assert all(x['estimated_g'] is None for x in provisional_allocation(heads, db, copy.deepcopy(db), profile))


def test_replacement_head_uses_common_profile_only_when_all_active_profiles_agree():
    heads, db = sample()
    db['spools']['a'].pop('calibration'); db['spools']['b'].pop('calibration')
    profile = {'mapping': [0, 1, 2, 3], 'filament_type': 'PLA;PLA;PLA;PLA',
               'logical_weights': [10, 0, 0, 0],
               'parameters': [{'diameter_mm': 1.75, 'density_g_cm3': 1.24} for _ in range(4)]}
    result = provisional_allocation(heads, db, copy.deepcopy(db), profile)
    assert result[1]['estimated_g'] == pytest.approx(.597, abs=.001)


def test_slicer_material_label_does_not_block_directly_mapped_parameters():
    heads, db = sample(); db['spools']['a'].pop('calibration');db['spools']['b'].pop('calibration')
    profile = {'mapping': [0, 1, 2, 3], 'filament_type': 'PETG;PLA;PLA;PLA', 'logical_weights': [1, 1, 0, 0],
               'parameters': [{'diameter_mm': 1.75, 'density_g_cm3': 1.24} for _ in range(4)]}
    result = provisional_allocation(heads, db, copy.deepcopy(db), profile)
    assert result[0]['estimated_g'] == pytest.approx(.298, abs=.001)
    assert result[1]['estimated_g'] == pytest.approx(.597, abs=.001)


def test_pla_plus_alias_uses_verified_slicer_parameters_for_physical_head():
    heads = [{'head': i, 'net_mm': 4010.699 if i == 2 else 0} for i in range(4)]
    db = {'slots': {'1': '', '2': '', '3': 'orange', '4': ''},
          'spools': {'orange': {'name': 'Generic', 'material': 'PLA. +', 'remaining_g': 1000}}}
    profile = {'mapping': [0, 1, 2, 3], 'filament_type': 'PLA;PLA;PLA;PLA',
               'logical_weights': [0, 0, 11.27, 0],
               'parameters': [{'diameter_mm': 1.75, 'density_g_cm3': 1.24} for _ in range(4)]}
    allocation = provisional_allocation(heads, db, copy.deepcopy(db), profile)
    assert allocation[0]['estimated_g'] == 11.962
    assert allocation[0]['parameter_source'] == 'slicer_estimate'
    assert allocation[0]['identity_verified'] is False


def test_slicer_tool_parameters_work_without_material_type_or_recognized_label():
    heads, db = sample()
    db['spools']['a'].pop('calibration'); db['spools']['b'].pop('calibration')
    db['spools']['a']['material'] = 'мой пластик'
    db['spools']['b']['material'] = 'custom label'
    profile = {'mapping': [0, 1, 2, 3], 'logical_weights': [1, 1, 0, 0],
               'parameters': [{'diameter_mm': 1.75, 'density_g_cm3': x} for x in (1.24, 1.4, 1.24, 1.24)]}
    result = provisional_allocation(heads, db, copy.deepcopy(db), profile)
    assert result[0]['estimated_g'] == pytest.approx(.298, abs=.001)
    assert result[1]['estimated_g'] == pytest.approx(.673, abs=.001)


def test_replacement_without_verified_parameters_does_not_borrow_unrelated_density():
    heads, db = sample()
    db['spools']['a'].pop('calibration'); db['spools']['b'].pop('calibration')
    db['spools']['b']['material'] = 'неизвестно'
    profile = {'mapping': [0, 1, 2, 3], 'filament_type': 'PLA;PLA;PLA;PLA',
               'logical_weights': [10, 0, 0, 0],
               'parameters': [{'diameter_mm': 1.75, 'density_g_cm3': 1.24} for _ in range(4)]}
    result = provisional_allocation(heads, db, copy.deepcopy(db), profile)
    assert result[0]['estimated_g'] is not None
    assert result[1]['estimated_g'] is None
