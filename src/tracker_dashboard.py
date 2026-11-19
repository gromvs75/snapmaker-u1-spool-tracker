"""Display-only print telemetry. Never feeds accounting or printer commands."""
import math


def number(value, maximum=None):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return None
    return value if maximum is None or value <= maximum else None


def telemetry(status):
    def obj(key):
        value = status.get(key)
        return value if isinstance(value, dict) else {}
    stats = obj('print_stats'); state = stats.get('state')
    result = dict(progress=None, elapsed_seconds=None, remaining_seconds=None,
                  eta_source=None, current_layer=None, total_layers=None)
    if not stats.get('filename') or state not in ('printing','paused','complete','cancelled','error'):
        return result
    elapsed = number(stats.get('print_duration'), 366*86400)
    result['elapsed_seconds'] = elapsed
    progress = number(obj('display_status').get('progress'), 1)
    if progress is None: progress = number(obj('virtual_sdcard').get('progress'), 1)
    result['progress'] = 1 if state == 'complete' else progress
    info = stats.get('info') if isinstance(stats.get('info'), dict) else {}
    current, total = info.get('current_layer'), info.get('total_layer')
    if type(current) is int and type(total) is int and 0 <= current <= total and total > 0:
        result.update(current_layer=current, total_layers=total)
    # Early byte/progress extrapolation is unstable. Pauses have no finish time.
    if state == 'printing' and elapsed is not None and elapsed >= 60 and progress is not None and .01 <= progress < 1:
        remaining = elapsed * (1-progress) / progress
        if remaining <= 30*86400:
            result.update(remaining_seconds=round(remaining), eta_source='progress_estimate')
    return result
