"""Pure preflight comparison for T0 through T3."""

def check(weights, db):
    margin = db["safety_margin_g"]
    rows = []
    for index, required in enumerate(weights):
        spool_id = db["slots"].get(str(index + 1), "")
        spool = db["spools"].get(spool_id)
        remaining = spool["remaining_g"] if spool else None
        if required == 0:
            status = "unused"
        elif spool is None:
            status = "unassigned"
        elif remaining < required + margin:
            status = "insufficient"
        else:
            status = "ok"
        rows.append({"tool": f"T{index}", "spool_id": spool_id,
                     "spool_name": spool["name"] if spool else None,
                     "required_g": required, "remaining_g": remaining,
                     "check_g": required + margin if required else 0,
                     "status": status})
    return rows


def has_problem(rows):
    return any(row["status"] in ("unassigned", "insufficient") for row in rows)
