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


def parse_u1_gcode(filepath, tail_bytes=1024 * 1024):
    try:
        with open(filepath, "rb") as handle:
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
    except OSError as exc:
        raise GCodeError(f"Cannot read G-code: {exc}") from exc
    raise GCodeError("Per-tool '; filament used [g] = ...' metadata was not found")
