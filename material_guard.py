"""Conservative material comparison for verified Snapmaker Orca metadata.

This module does not control the printer.  Matching material family never
guarantees temperature, drying, nozzle or other print compatibility.
"""
import math
from tool_mapping import validate_mapping

FAMILIES = frozenset({'PLA', 'PETG', 'ABS', 'ASA', 'TPU', 'PVA', 'PC', 'HIPS'})


def material_family(value):
    if not isinstance(value, str):
        return None
    name = value.strip().upper()
    # Explicit spelling variants identify the broad family only; they do not
    # assert that profiles, temperatures or additives are interchangeable.
    aliases = {'PLA+': 'PLA', 'PLA +': 'PLA', 'PLA. +': 'PLA'}
    return aliases.get(name, name if name in FAMILIES else None)


def compare_materials(metadata, logical_weights, mapping, db):
    """Return per-physical-head observations; unknown data is never a match."""
    result = [{'head': i, 'status': 'unused', 'expected': [], 'candidates': []} for i in range(4)]
    mapping = validate_mapping(mapping)
    if (not isinstance(logical_weights, (list, tuple)) or len(logical_weights) != 4
            or any(isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or w < 0 for w in logical_weights)):
        raise ValueError('Invalid logical weights')
    used_heads = {mapping[i] for i, w in enumerate(logical_weights) if w > 0}
    for head in used_heads:
        result[head]['status'] = 'unknown'
    if not isinstance(metadata, dict) or metadata.get('slicer') != 'SnapmakerOrca':
        return result
    types, weights = metadata.get('filament_type'), metadata.get('filament_weight')
    if not isinstance(types, str) or not isinstance(weights, list) or len(weights) != 4:
        return result
    types = types.split(';')
    if len(types) != 4:
        return result
    if any(isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or w < 0 or abs(w - logical_weights[i]) > .02
           for i, w in enumerate(weights)):
        return result
    for head in used_heads:
        logical = [i for i, grams in enumerate(logical_weights) if grams > 0 and mapping[i] == head]
        expected = [material_family(types[i]) for i in logical]
        if any(item is None for item in expected) or len(set(expected)) != 1:
            continue
        family = expected[0]
        row = result[head]
        row['expected'] = [family]
        assigned = db.get('slots', {}).get(str(head + 1))
        spool = db.get('spools', {}).get(assigned)
        actual = material_family(spool.get('material')) if isinstance(spool, dict) else None
        row['status'] = 'unknown' if actual is None else ('match' if actual == family else 'mismatch')
        if row['status'] != 'match':
            required = sum(logical_weights[i] for i in logical) + db.get('safety_margin_g', 0)
            row['candidates'] = [spool_id for spool_id, item in db.get('spools', {}).items()
                                 if material_family(item.get('material')) == family
                                 and isinstance(item.get('remaining_g'), (int, float))
                                 and item['remaining_g'] >= required]
    return result
