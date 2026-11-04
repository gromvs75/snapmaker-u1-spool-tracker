"""Conservative local summaries from Tracker's job ledger.

Only committed estimated head allocations are attributable to heads. Manual
per-spool reconciliations do not record a head and must never be guessed.
"""
from datetime import datetime, timezone


def summarize_prints(db):
    result = {"counts": {key: 0 for key in ("active", "committed", "cancelled", "error", "review")},
              "head_estimated_g": [0.0] * 4, "manual_spool_g": {}, "motion_spool_g": {}, "weighed_records": [], "by_month": {}}
    for run in db.get("runs", {}).values():
        status = run.get("status")
        if status not in result["counts"]:
            continue
        result["counts"][status] += 1
        if status != "committed":
            continue
        try:
            month = datetime.fromtimestamp(run["start_time"], timezone.utc).strftime("%Y-%m")
        except (ValueError, OverflowError, OSError, TypeError, KeyError):
            continue
        bucket = result["by_month"].setdefault(month, {"committed": 0, "estimated_g": 0.0, "manual_g": 0.0, "motion_g": 0.0})
        bucket["committed"] += 1
        if run.get("accounting_method") == "manual_review":
            for spool_id, grams in run.get("manual_consumption", {}).items():
                result["manual_spool_g"][spool_id] = result["manual_spool_g"].get(spool_id, 0.0) + grams
                bucket["manual_g"] += grams
            for spool_id, pair in run.get('manual_measurements', {}).items():
                head_ids, weights = run.get('physical_spool_ids'), run.get('physical_weights')
                original_estimate = None
                if isinstance(head_ids, list) and len(head_ids) == 4 and isinstance(weights, list) and len(weights) == 4:
                    original_estimate = round(sum(weight for ident, weight in zip(head_ids, weights) if ident == spool_id), 3)
                result['weighed_records'].append({'filename': run.get('filename', ''), 'start_time': run['start_time'],
                    'spool_id': spool_id, 'weighed_g': round(pair['before_g'] - pair['after_g'], 3),
                    'initial_gcode_estimate_g': original_estimate,
                    'estimate_may_be_affected_by_replacement': bool(run.get('replenishment_observed') or 'replenish' in run.get('review_reason', '').lower())})
        elif run.get("accounting_method") == "motion_estimate":
            for spool_id, grams in run.get("motion_consumption", {}).items():
                result["motion_spool_g"][spool_id] = result["motion_spool_g"].get(spool_id, 0.0) + grams
                bucket["motion_g"] += grams
        else:
            weights = run.get("physical_weights")
            if isinstance(weights, list) and len(weights) == 4:
                for index, grams in enumerate(weights):
                    result["head_estimated_g"][index] += grams
                    bucket["estimated_g"] += grams
    result["head_estimated_g"] = [round(x, 3) for x in result["head_estimated_g"]]
    result["manual_spool_g"] = {key: round(value, 3) for key, value in result["manual_spool_g"].items()}
    result["motion_spool_g"] = {key: round(value, 3) for key, value in result["motion_spool_g"].items()}
    for bucket in result["by_month"].values():
        bucket["estimated_g"] = round(bucket["estimated_g"], 3)
        bucket["manual_g"] = round(bucket["manual_g"], 3)
        bucket["motion_g"] = round(bucket["motion_g"], 3)
    return result
