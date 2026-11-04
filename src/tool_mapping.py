"""Translate logical G-code tools into physical Snapmaker U1 toolheads."""

import math


class MappingError(ValueError):
    pass


def validate_mapping(value):
    # U1 may expose more than four logical entries; this tracker parses four.
    if not isinstance(value, list) or len(value) < 4:
        raise MappingError("U1 tool mapping is unavailable or incomplete")
    result = value[:4]
    if any(isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 3 for item in result):
        raise MappingError("U1 tool mapping contains an invalid physical toolhead")
    return result


def physical_weights(logical_weights, mapping):
    mapping = validate_mapping(mapping)
    if not isinstance(logical_weights, (list, tuple)) or len(logical_weights) != 4:
        raise MappingError("Expected four logical filament weights")
    if any(isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or w < 0
           for w in logical_weights):
        raise MappingError("Invalid logical filament weights")
    try:
        result = [math.fsum(logical_weights[i] for i in range(4) if mapping[i] == physical)
                  for physical in range(4)]
    except OverflowError as exc:
        raise MappingError("Combined filament weight is too large") from exc
    if any(not math.isfinite(value) for value in result):
        raise MappingError("Combined filament weight is not finite")
    return result
