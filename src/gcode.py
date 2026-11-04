"""OrcaSlicer filament metadata parser. Never interpret missing data as zero."""

import math
import re

METADATA = re.compile(r"^\s*;\s*filament\s+used\s*\[g\]\s*=\s*(.*?)\s*$", re.IGNORECASE)


class GCodeError(ValueError):
    pass


def _parse_line(line):
    match = METADATA.match(line)
    if not match:
        return None
    parts = match.group(1).split(",")
    if not 1 <= len(parts) <= 4:
        raise GCodeError("Expected one to four per-tool filament weights")
    try:
        values = [float(part.strip()) for part in parts]
    except ValueError as exc:
        raise GCodeError("Invalid filament weight in G-code") from exc
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise GCodeError("Filament weights must be finite and non-negative")
    return values + [0.0] * (4 - len(values))


def parse_u1_gcode_handle(handle, tail_bytes=1024 * 1024):
    """Read per-tool usage from a seekable binary G-code stream."""
    handle.seek(0, 2)
    size = handle.tell()
    handle.seek(max(0, size - tail_bytes))
    tail = handle.read().decode("utf-8", errors="replace")
    if size > tail_bytes:
        tail = tail.partition("\n")[2]
    for line in reversed(tail.splitlines()):
        result = _parse_line(line)
        if result is not None:
            return result
    # Older slicer output can place metadata before a large appended section.
    handle.seek(0)
    found = None
    for raw in handle:
        result = _parse_line(raw.decode("utf-8", errors="replace"))
        if result is not None:
            found = result
    if found is not None:
        return found
    raise GCodeError("Per-tool '; filament used [g] = ...' metadata was not found")


def parse_u1_gcode(filepath, tail_bytes=1024 * 1024):
    try:
        with open(filepath, "rb") as handle:
            return parse_u1_gcode_handle(handle, tail_bytes)
    except OSError as exc:
        raise GCodeError(f"Cannot read G-code: {exc}") from exc


def parse_filament_parameters_handle(handle, tail_bytes=1024 * 1024):
    """Read per-logical-tool slicer parameters as estimates, or return None.

    Do not supply defaults, extrapolate to replacement heads, or treat these
    slicer settings as independently measured spool parameters.
    """
    handle.seek(0, 2)
    size = handle.tell()
    handle.seek(max(0, size - tail_bytes))
    tail = handle.read().decode('utf-8', errors='replace')
    if size > tail_bytes:
        tail = tail.partition('\n')[2]
    found = {}
    for line in tail.splitlines():
        match = re.match(r'^\s*;\s*filament_(density|diameter)\s*=\s*(.*?)\s*$', line, re.IGNORECASE)
        if match:
            key = match.group(1).lower()
            if key in found:
                return None
            try:
                found[key] = [float(x.strip()) for x in match.group(2).split(',')]
            except (ValueError, OverflowError):
                return None
    if set(found) != {'density', 'diameter'}:
        return None
    if len(found['density']) != len(found['diameter']) or not 1 <= len(found['density']) <= 4:
        return None
    output = []
    for density, diameter in zip(found['density'], found['diameter']):
        if not math.isfinite(density) or not math.isfinite(diameter) or not 0.1 <= density <= 5 or not 0.5 <= diameter <= 4:
            return None
        output.append({'diameter_mm': diameter, 'density_g_cm3': density})
    return output
