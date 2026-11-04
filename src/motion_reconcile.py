"""Fail-closed conversion of prototype motion captures into spool estimates.

The printer-side prototype currently never asserts identity_verified. This
module is therefore preparation only, and must not be used to book inventory
until identity continuity is independently established on physical U1s.
"""
import math
from spool_identity import calibration, estimate_grams, tag_uid


class MotionEvidenceError(ValueError):
    pass


def estimate_capture(start, end, job, start_spools, current_spools, start_calibrations, current_calibrations):
    if not isinstance(start, dict) or not isinstance(end, dict) or not isinstance(job, dict):
        raise MotionEvidenceError('Capture or job unavailable')
    if (start.get('state') != 'active' or end.get('state') != 'completed'
            or start.get('valid') is not True or end.get('valid') is not True
            or start.get('identity_verified') is not True or end.get('identity_verified') is not True
            or job.get('status') != 'completed'):
        raise MotionEvidenceError('Completion or spool identity is not verified')
    for key in ('epoch', 'capture_id', 'filename'):
        if not isinstance(start.get(key), str) or not start[key] or start[key] != end.get(key):
            raise MotionEvidenceError('Capture identity changed')
    if end['filename'] != job.get('filename'):
        raise MotionEvidenceError('Capture filename does not match the printer job')
    begin, job_start = start.get('started_at'), job.get('start_time')
    if (any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (begin, job_start))
            or abs(begin - job_start) > 10):
        raise MotionEvidenceError('Capture start does not match the printer job')
    finished = end.get('finished_at')
    if (end.get('started_at') != begin or isinstance(finished, bool) or not isinstance(finished, (int, float))
            or not math.isfinite(finished) or finished < begin):
        raise MotionEvidenceError('Capture timestamps are inconsistent')
    if (not isinstance(start_spools, list) or len(start_spools) != 4 or start_spools != current_spools
            or not isinstance(start_calibrations, dict) or start_calibrations != current_calibrations):
        raise MotionEvidenceError('Spool assignment or calibration changed')
    tags, end_tags = start.get('initial_tag_uids'), end.get('initial_tag_uids')
    if not isinstance(tags, list) or len(tags) != 4 or tags != end_tags:
        raise MotionEvidenceError('Spool tags changed or are unavailable')
    final_tags = end.get('final_tag_uids')
    if not isinstance(final_tags, list) or len(final_tags) != 4:
        raise MotionEvidenceError('Final spool tag snapshot is unavailable')
    inserted = end.get('spool_insert_events')
    if not isinstance(inserted, list) or len(inserted) != 4 or any(type(x) is not bool for x in inserted):
        raise MotionEvidenceError('Spool insertion evidence is unavailable')
    lengths = end.get('head_mm')
    if (not isinstance(lengths, list) or len(lengths) != 4
            or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 for x in lengths)):
        raise MotionEvidenceError('Physical head motion is invalid')
    used_ids = [start_spools[i] for i, value in enumerate(lengths) if value > 0]
    if len(used_ids) != len(set(used_ids)):
        raise MotionEvidenceError('The same spool cannot be used on two physical heads')
    totals = {}
    for head, length in enumerate(lengths):
        if length == 0:
            continue
        spool_id = start_spools[head]
        value = start_calibrations.get(spool_id)
        if not isinstance(spool_id, str) or not spool_id or inserted[head] or tags[head] != final_tags[head]:
            raise MotionEvidenceError('Spool identity cannot be guaranteed')
        try:
            item = calibration(value)
            uid = tag_uid(tags[head])
            if item['identity_mode'] == 'tag':
                if uid is None or item['uid'] != uid:
                    raise MotionEvidenceError('Tag is missing or does not match the bound spool')
            elif item['identity_mode'] == 'manual_confirmed':
                manual = end.get('manual_continuity')
                if (uid is not None or not isinstance(manual, list) or len(manual) != 4
                        or any(type(x) is not bool for x in manual) or manual[head] is not True):
                    raise MotionEvidenceError('Untagged spool continuity is unverified')
            else:
                raise MotionEvidenceError('Spool identity is unverified')
            grams = estimate_grams(length, item)
        except (ValueError, TypeError) as exc:
            raise MotionEvidenceError(str(exc)) from exc
        totals[spool_id] = totals.get(spool_id, 0.0) + grams
    if not totals:
        raise MotionEvidenceError('No accountable motion was captured')
    return {spool_id: round(grams, 3) for spool_id, grams in totals.items()}
