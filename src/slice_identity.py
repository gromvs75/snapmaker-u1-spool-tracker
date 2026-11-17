"""Read explicit Snorca bed identities; cache file counters are not bed numbers.

Snorca v2.4.1 model_settings.config stores one-based plater_id and gcode_file.
Only local, bounded, fresh metadata with an exact file reference is accepted.
This is a saved project identity, not evidence of the GUI's selected bed.
"""
import io
from functools import lru_cache
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from slice_observer import read_snapshot, fingerprint

MAX_XML = 2 * 1024 * 1024
MAX_ARCHIVE = 16 * 1024 * 1024


def _xml(path):
    return _read_xml(path, fingerprint(path.lstat()))


@lru_cache(maxsize=32)
def _read_xml(path, expected_signature):
    limit = MAX_XML if path.suffix == '.config' else MAX_ARCHIVE
    if path.stat().st_size > limit:
        raise ValueError('Metadata too large')
    raw, signature = read_snapshot(path)
    if signature != expected_signature:
        raise ValueError('Metadata changed during read')
    if len(raw) > limit:
        raise ValueError('Metadata too large')
    if path.suffix != '.config':
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            matches = [m for m in members if m.filename == 'Metadata/model_settings.config']
            if len(members) > 256 or len(matches) != 1 or matches[0].file_size > MAX_XML:
                raise ValueError('Ambiguous or oversized metadata')
            raw = archive.read(matches[0])
    # Do not resolve entities from a project supplied by another person.
    if b'\0' in raw or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('XML declarations unsupported')
    return ET.fromstring(raw), signature[3]


def bed_identity(path, completed_at_ns):
    """Return a proven one-based saved bed number, or None. Never rank files."""
    path = Path(path)
    metadata = path.parent
    project = metadata.parent
    candidates = [metadata / 'model_settings.config', project / '.3mf']
    candidates += sorted(metadata.glob('.*_config.3mf'))
    candidates += sorted(project.glob('*.3mf'))
    candidates += sorted(project.glob('.*.3mf'))
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) > 32 or metadata.is_symlink() or project.is_symlink():
        return None
    numbers = set()
    invalid = False
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            if candidate.is_symlink():
                raise ValueError('Linked metadata')
            tree, stamp = _xml(candidate)
            if stamp < completed_at_ns:
                continue
            for plate in tree.findall('./plate'):
                values = {}
                for item in plate.findall('metadata'):
                    key = item.get('key')
                    if key in values:
                        raise ValueError('Duplicate metadata key')
                    values[key] = item.get('value', '')
                reference = values.get('gcode_file', '').replace('\\', '/')
                # Exact absolute or project-relative reference; no basename guessing.
                accepted = {path.as_posix(), 'Metadata/' + path.name, path.name}
                if os.path.normcase(reference) not in {os.path.normcase(p) for p in accepted}:
                    continue
                number = values.get('plater_id', '')
                if not re.fullmatch(r'[1-9][0-9]{0,3}', number):
                    raise ValueError('Invalid bed number')
                numbers.add(int(number))
        except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
            invalid = True
    return next(iter(numbers)) if len(numbers) == 1 and not invalid else None
