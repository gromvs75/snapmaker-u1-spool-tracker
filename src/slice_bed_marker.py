"""Bed identity emitted by the slicer, attached to the observed G-code bytes.

This is display metadata, never permission to debit or a physical tool mapping.
The profile template uses Snorca's plate_number (one based, zero padded).
"""
import re

PROFILE_COMMENT = '; TRACKER_BED_V1 = {plate_number}'


def embedded_bed_identity(content):
    """Return (number, source); malformed/duplicate markers fail closed.

Only the executable block is inspected. Snorca also stores the unexpanded
profile template in CONFIG_BLOCK; that is not evidence of the sliced bed.
Call after the observer has validated completion and block uniqueness.
"""
    body = content.split(b'; EXECUTABLE_BLOCK_START', 1)[-1].split(
        b'; EXECUTABLE_BLOCK_END', 1)[0]
    markers = [line.strip() for line in body.splitlines()
               if line.strip().startswith(b'; TRACKER_BED_')]
    if not markers:
        return None, 'absent'
    if len(markers) != 1:
        return None, 'invalid_marker'
    match = re.fullmatch(rb'; TRACKER_BED_V1 = ([0-9]{1,4})', markers[0])
    if not match or not 1 <= int(match[1]) <= 9999:
        return None, 'invalid_marker'
    return int(match[1]), 'gcode_marker_v1'
