"""Offline product suggestions. Never identifies a roll, changes a UID or balance."""
import gzip
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
import re
import zlib

DATA = Path(__file__).with_name('tracker_spoolmandb_data')
FIELDS = ('id', 'manufacturer', 'name', 'material', 'density', 'weight', 'diameter',
          'color_hex', 'color_hexes', 'spool_weight', 'extruder_temp', 'bed_temp')


def normalized(value):
    return re.sub(r'\s+', ' ', str(value or '').strip()).casefold()


def colors(row):
    values = row.get('color_hexes') or ([row['color_hex']] if row.get('color_hex') else [])
    if isinstance(values, str):
        values = values.split(',')
    if not isinstance(values,list) or any(not isinstance(v,str) for v in values):
        raise ValueError('Invalid SpoolmanDB colors')
    return tuple(sorted(v.upper().lstrip('#') for v in values))


def validate(rows):
    if not isinstance(rows, list) or not 0 < len(rows) <= 100000:
        raise ValueError('Invalid SpoolmanDB catalog size')
    ids = set()
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid SpoolmanDB row')
        for key in ('id', 'manufacturer', 'name', 'material'):
            if not isinstance(row.get(key), str) or not 0 < len(row[key]) <= 300:
                raise ValueError('Invalid SpoolmanDB text')
        if row['id'] in ids:
            raise ValueError('Duplicate SpoolmanDB product')
        ids.add(row['id'])
        for key, low, high in (('density', .1, 5), ('diameter', .5, 4), ('weight', 1, 100000)):
            value = row.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError('Invalid SpoolmanDB ' + key)
        if any(not re.fullmatch('[0-9A-F]{6}(?:[0-9A-F]{2})?', c) for c in colors(row)):
            raise ValueError('Invalid SpoolmanDB color')
        result.append({key: row.get(key) for key in FIELDS})
    return result


class Catalog:
    def __init__(self, rows, revision):
        self.revision = revision
        self.index = {}
        for row in validate(rows):
            # Keep the full catalog, but do not invent RGB for missing colors
            # or discard the alpha channel of an eight-digit catalog color.
            if not colors(row) or any(len(c) != 6 for c in colors(row)):
                continue
            key = normalized(row['manufacturer']), normalized(row['material']), colors(row)
            self.index.setdefault(key, []).append(row)

    def match(self, tag, names):
        key = normalized(names.get('manufacturer')), normalized(names.get('material')), tuple(sorted(tag.get('colors') or []))
        candidates = list(self.index.get(key, []))
        criteria = ['manufacturer', 'material', 'colors']
        for field, prop in (('diameter', 'diameter_mm'), ('weight', 'nominal_weight_g')):
            value = tag.get(prop)
            if value is not None:
                candidates = [r for r in candidates if abs(r[field] - value) < .000001]
                criteria.append(field)
        # An exact product name can disambiguate. Never use fuzzy names, a
        # generic material name, chip UID or color similarity as a product ID.
        named = [r for r in candidates if normalized(r['name']) == normalized(tag.get('name'))]
        if named:
            candidates = named
            criteria.append('name')
        candidates.sort(key=lambda r: r['id'])
        return dict(status='suggested' if len(candidates) == 1 else 'ambiguous' if candidates else 'not_found',
                    source='SpoolmanDB', revision=self.revision, criteria=criteria,
                    count=len(candidates), candidates=[dict(r) for r in candidates[:30]],
                    requires_confirmation=True)


@lru_cache(maxsize=1)
def bundled():
    manifest = json.loads((DATA / 'manifest.json').read_text())
    raw = gzip.decompress((DATA / 'filaments.json.gz').read_bytes())
    if hashlib.sha256(raw).hexdigest() != manifest['sha256']:
        raise ValueError('SpoolmanDB snapshot checksum mismatch')
    rows = json.loads(raw)
    if len(rows) != manifest['products']:
        raise ValueError('SpoolmanDB snapshot count mismatch')
    return Catalog(rows, manifest['sha256'])


def suggest(tag, names):
    try:
        return bundled().match(tag, names)
    except (OSError, ValueError, KeyError, TypeError, EOFError, zlib.error):
        # A missing/broken optional catalog must not break RFID or local balances.
        return dict(status='unavailable', source='SpoolmanDB', candidates=[], count=0,
                    requires_confirmation=True)
