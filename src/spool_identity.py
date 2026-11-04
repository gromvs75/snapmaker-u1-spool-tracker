"""Explicit spool tag bindings and calibrated length-to-mass estimates."""
import math
import re


def tag_uid(value):
    if value is None or value == '':
        return None
    if isinstance(value, list):
        if len(value) not in (4, 7, 10) or any(type(x) is not int or not 0 <= x <= 255 for x in value) or not any(value):
            raise ValueError('Invalid RFID tag UID')
        return ''.join(f'{x:02x}' for x in value)
    if not isinstance(value, str):
        raise ValueError('Invalid RFID tag UID')
    cleaned = value.strip().lower().replace(':', '').replace('-', '')
    if len(cleaned) not in (8, 14, 20) or not re.fullmatch('[0-9a-f]+', cleaned) or not int(cleaned, 16):
        raise ValueError('Invalid RFID tag UID')
    return cleaned


def calibration(value):
    if not isinstance(value, dict) or set(value) - {'uid', 'diameter_mm', 'density_g_cm3', 'identity_mode'}:
        raise ValueError('Invalid spool calibration')
    result = {'uid': tag_uid(value.get('uid'))}
    mode = value.get('identity_mode', 'tag' if result['uid'] else 'unverified')
    if mode not in ('tag', 'manual_confirmed', 'unverified'):
        raise ValueError('Invalid spool identity mode')
    if (mode == 'tag' and not result['uid']) or (mode != 'tag' and result['uid']):
        raise ValueError('Tag binding and identity mode are inconsistent')
    result['identity_mode'] = mode
    for field, low, high in [('diameter_mm', 0.5, 4.0), ('density_g_cm3', 0.1, 5.0)]:
        val = value.get(field)
        if val is None or val == '':
            result[field] = None
            continue
        if isinstance(val, bool):
            raise ValueError(f'Invalid {field}')
        try:
            val = float(val)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f'Invalid {field}') from exc
        if not math.isfinite(val) or not low <= val <= high:
            raise ValueError(f'Invalid {field}')
        result[field] = val
    return result


def estimate_grams(length_mm, value):
    """Volume-density estimate from commanded motion, not a physical weighing."""
    if isinstance(length_mm, bool) or not isinstance(length_mm, (int, float)) or not math.isfinite(length_mm) or length_mm < 0:
        raise ValueError('Invalid commanded filament length')
    item = calibration(value)
    if item['diameter_mm'] is None or item['density_g_cm3'] is None:
        raise ValueError('Known filament diameter and density are required')
    return math.pi * (item['diameter_mm'] / 2) ** 2 * length_mm * item['density_g_cm3'] / 1000


def read_tag_uids(status):
    """Only idle scanner channels may provide a current tag; missing stays unknown."""
    info = status.get('info') if isinstance(status, dict) else None
    state = status.get('state') if isinstance(status, dict) else None
    if not isinstance(info, list) or len(info) != 4 or not isinstance(state, list) or len(state) != 4:
        raise ValueError('Tag scanner status unavailable')
    result = []
    for item, phase in zip(info, state):
        try:
            if type(phase) is not int or phase != 0 or not isinstance(item, dict):
                result.append(None)
            else:
                result.append(tag_uid(item.get('CARD_UID')))
        except ValueError:
            result.append(None)
    return result
