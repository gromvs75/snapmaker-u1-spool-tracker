import pytest
from material_guard import compare_materials, material_family


def inventory():
    return {'slots': {'1': 'black', '2': 'white', '3': '', '4': ''},
            'spools': {'black': {'material': 'PLA', 'remaining_g': 100},
                       'white': {'material': 'PETG', 'remaining_g': 100},
                       'spare': {'material': 'PLA', 'remaining_g': 200}}, 'safety_margin_g': 5}


def test_verified_logical_materials_are_checked_against_physical_head():
    meta = {'slicer': 'SnapmakerOrca', 'filament_type': 'PLA;PLA;PLA;PLA', 'filament_weight': [0, 3.85, 0, 0]}
    rows = compare_materials(meta, [0, 3.85, 0, 0], [0, 1, 2, 3], inventory())
    assert rows[1]['status'] == 'mismatch'
    assert set(rows[1]['candidates']) == {'black', 'spare'}
    mapped = compare_materials(meta, [0, 3.85, 0, 0], [1, 0, 2, 3], inventory())
    assert mapped[0]['status'] == 'match'
    assert mapped[1]['status'] == 'unused'


def test_missing_ambiguous_or_conflicting_metadata_never_produces_match():
    db = inventory()
    weight = [1, 0, 0, 0]
    for meta in [{}, {'slicer': 'OrcaSlicer', 'filament_type': 'PLA;PLA;PLA;PLA', 'filament_weight': weight},
                 {'slicer': 'SnapmakerOrca', 'filament_type': 'PLA', 'filament_weight': weight},
                 {'slicer': 'SnapmakerOrca', 'filament_type': 'PLA;PLA;PLA;PLA', 'filament_weight': [5, 0, 0, 0]}]:
        assert compare_materials(meta, weight, [0, 1, 2, 3], db)[0]['status'] == 'unknown'
    db['spools']['black']['material'] = 'PLA-like'
    meta = {'slicer': 'SnapmakerOrca', 'filament_type': 'PLA;PLA;PLA;PLA', 'filament_weight': weight}
    assert compare_materials(meta, weight, [0, 1, 2, 3], db)[0]['status'] == 'unknown'


def test_two_different_materials_on_one_physical_head_are_unknown():
    meta = {'slicer': 'SnapmakerOrca', 'filament_type': 'PLA;PETG;PLA;PLA', 'filament_weight': [1, 1, 0, 0]}
    assert compare_materials(meta, [1, 1, 0, 0], [0, 0, 2, 3], inventory())[0]['status'] == 'unknown'


@pytest.mark.parametrize('value', ['PLA+', 'PLA +', 'PLA. +', ' pla. + '])
def test_explicit_pla_plus_aliases_only_identify_family(value):
    assert material_family(value) == 'PLA'
    assert material_family('PLA-like') is None
    assert material_family('PLA+PETG') is None
