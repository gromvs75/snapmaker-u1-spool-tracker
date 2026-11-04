"""Build provisional spool allocations, never modifying inventory.

The slot assignment supplies names, not proof of physical spool continuity.
Spool names and manufacturer do not alter material or identity handling.
"""
import math
from spool_identity import estimate_grams
from tool_mapping import validate_mapping, MappingError
from material_guard import material_family


def provisional_allocation(heads, start, current, profile=None):
    if not all(isinstance(x, dict) for x in (start, current)) or not isinstance(heads, list) or len(heads) != 4:
        raise ValueError('Allocation evidence unavailable')
    slots = start.get('slots')
    if not isinstance(slots, dict) or slots != current.get('slots'):
        raise ValueError('Spool assignment changed')
    before, after = start.get('spools', {}), current.get('spools', {})
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError('Spool data unavailable')
    result = []
    used = set()
    for i, item in enumerate(heads):
        if not isinstance(item, dict) or item.get('head') != i:
            raise ValueError('Head evidence unavailable')
        length = item.get('net_mm')
        if isinstance(length, bool) or not isinstance(length, (int, float)) or not math.isfinite(length):
            raise ValueError('Invalid motion length')
        if length <= 0:
            continue
        spool_id = slots.get(str(i + 1))
        old, new = before.get(spool_id), after.get(spool_id)
        if not isinstance(spool_id, str) or not spool_id or not isinstance(old, dict) or not isinstance(new, dict):
            raise ValueError('Assigned spool unavailable')
        if spool_id in used:
            raise ValueError('One spool is assigned to multiple used heads')
        used.add(spool_id)
        if old.get('material') != new.get('material') or old.get('calibration') != new.get('calibration'):
            raise ValueError('Spool material or calibration changed')
        entry = {'head': i, 'spool_id': spool_id, 'spool_name': new.get('name', ''), 'net_mm': length,
                 'estimated_g': None, 'identity_verified': False}
        try:
            entry['estimated_g'] = round(estimate_grams(length, old.get('calibration')), 3)
        except ValueError:
            entry['reason'] = 'Spool diameter or density unavailable'
            if isinstance(profile, dict):
                try:
                    mapping = validate_mapping(profile.get('mapping'))
                    parameters = profile['parameters']
                    weights = profile['logical_weights']
                    type_text = profile.get('filament_type')
                    types = type_text.split(';') if isinstance(type_text, str) else []
                    if not isinstance(parameters, list) or len(parameters) != 4 or not isinstance(weights, list) or len(weights) != 4:
                        raise ValueError('Incomplete slicer profile')
                    logical = [j for j in range(4) if mapping[j] == i and isinstance(weights[j], (int, float)) and not isinstance(weights[j], bool) and math.isfinite(weights[j]) and weights[j] > 0]
                    if not logical:
                        # A replacement head may have no logical tool in the
                        # original file. Only use a common profile if every
                        # used logical tool agrees on material and parameters.
                        active = [j for j in range(4) if isinstance(weights[j], (int, float)) and not isinstance(weights[j], bool) and math.isfinite(weights[j]) and weights[j] > 0]
                        if (len(types) == 4 and active and material_family(types[active[0]]) is not None
                                and material_family(types[active[0]]) == material_family(old.get('material'))
                                and all(parameters[j] == parameters[active[0]] and material_family(types[j]) == material_family(types[active[0]]) for j in active)):
                            logical = [active[0]]
                    # A directly mapped slicer tool supplies its own physical
                    # parameters. The user's spool label is not a density source.
                    if len(logical) != 1:
                        raise ValueError('Slicer parameters cannot be assigned unambiguously')
                    entry['estimated_g'] = round(estimate_grams(length, parameters[logical[0]]), 3)
                    entry['parameter_source'] = 'slicer_estimate'
                    entry.pop('reason', None)
                except (ValueError, TypeError, KeyError, AttributeError, MappingError):
                    pass
        result.append(entry)
    return result
