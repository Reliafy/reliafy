"""Evidence checks for the RCM on the maintenance positions.

A failure mode's decision on the graph links the saved model or analysis that
justifies it (``evidence`` on the mode). The check is
``backend/maintenance/rcm_decisions.py`` ``resolve_decision``: done on every
read, never stored.
"""

from __future__ import annotations

from backend.maintenance import rcm_decisions


def resolve(db, worksheet: dict, owner_id, hidden=frozenset()) -> dict:
    """``worksheet`` (Maintenance.rcm_worksheet) with each decision's evidence
    status, and a rollup per position and for the whole of it (as a study's)."""
    fetch = rcm_decisions.evidence_fetcher(db, owner_id, hidden)
    total = rcm_decisions.blank_rollup()
    positions = []
    for p in worksheet["positions"]:
        rollup = rcm_decisions.blank_rollup()

        def mode_out(mode: dict) -> dict:
            rollup["modes"] += 1
            decision = mode.get("decision")
            if not decision:
                return mode
            rollup["decided"] += 1
            resolved = rcm_decisions.resolve_decision(decision, fetch)
            status = resolved.get("status")
            if status in rollup:
                rollup[status] += 1
            return {**mode, "decision": {**decision, **resolved}}

        functions = [{**fn, "failures": [{**ff, "modes": [mode_out(m) for m in ff["modes"]]}
                                         for ff in fn["failures"]]} for fn in p["functions"]]
        unassigned = [mode_out(m) for m in p["unassigned"]]
        for k, v in rollup.items():
            total[k] += v
        positions.append({**p, "functions": functions, "unassigned": unassigned, "rollup": rollup})
    return {**worksheet, "positions": positions, "rollup": total}


def mode_status(db, mode: dict, owner_id, hidden=frozenset()) -> dict:
    """One failure mode (Maintenance.rcm_mode) with its evidence status."""
    decision = mode.get("decision")
    if not decision:
        return mode
    fetch = rcm_decisions.evidence_fetcher(db, owner_id, hidden)
    return {**mode, "decision": {**decision, **rcm_decisions.resolve_decision(decision, fetch)}}


def evidence_refs(decision) -> list[tuple[str, str]]:
    """The (collection, id) a decision links as evidence, for access.check_references."""
    from backend.services import access

    return access.refs_of_decision(decision)


# What an RCM still needs, as short lists (an agent's "which modes have no
# task?", the RCM tab's chips): from a resolved worksheet (resolve above).
GAPS_LIMIT = 200
_CHECK = ("contradicted", "inconclusive", "stale")


def gaps(sheet: dict, limit: int = GAPS_LIMIT) -> dict:
    """Each list names the things by id with where they are: failure modes
    with no decision (undecided), with no task (no_task: every live mode with
    none, with its outcome, so a run-to-failure one shows as such), hidden
    ones with no failure-finding task, decisions whose evidence needs a look
    (contradicted, inconclusive or gone); functions with no functional
    failure, performance standards no functional failure breaches, and
    functional failures with no failure modes and nothing linked below. At
    most ``limit`` rows a list (counts are always whole)."""
    lists: dict[str, list] = {k: [] for k in (
        "undecided", "no_task", "hidden_without_failure_finding", "evidence_to_check", "functions_without_failure",
        "standards_without_failure", "functional_failures_empty")}

    def mode_row(mode, pos, ff):
        d = mode.get("decision") or {}
        row = {"id": mode["id"], "text": mode["text"], "position": pos,
               "functional_failure": {"id": ff["id"], "text": ff["text"]} if ff else None,
               "consequence": mode.get("consequence"), "outcome": d.get("outcome")}
        if not d:
            lists["undecided"].append(row)
        tasks = mode.get("tasks") or []
        if not tasks:
            lists["no_task"].append(row)
        if mode.get("consequence") == "hidden" and not any(t.get("outcome") == "failure_finding" for t in tasks):
            lists["hidden_without_failure_finding"].append(
                row | {"tasks": [{"id": t["id"], "name": t["name"], "outcome": t.get("outcome")} for t in tasks]})
        if d.get("status") in _CHECK:
            lists["evidence_to_check"].append(row | {"status": d["status"], "reason": d.get("reason") or d.get("summary")})

    for p in sheet.get("positions") or []:
        pos = {"id": p["id"], "name": p["name"]}
        for fn in p.get("functions") or []:
            fn_ref = {"id": fn["id"], "text": fn["text"]}
            if not fn.get("failures"):
                lists["functions_without_failure"].append({**fn_ref, "position": pos})
            for st in fn.get("standards") or []:
                if not st.get("failures"):
                    lists["standards_without_failure"].append(
                        {"id": st["id"], "text": st["text"], "function": fn_ref, "position": pos})
            for ff in fn.get("failures") or []:
                if not ff.get("modes") and not ff.get("causes"):
                    lists["functional_failures_empty"].append(
                        {"id": ff["id"], "text": ff["text"], "function": fn_ref, "position": pos})
                for mode in ff.get("modes") or []:
                    mode_row(mode, pos, ff)
        for mode in p.get("unassigned") or []:
            mode_row(mode, pos, None)
    out: dict = {"counts": {k: len(v) for k, v in lists.items()},
                 "positions": len(sheet.get("positions") or []),
                 "modes": (sheet.get("rollup") or {}).get("modes", 0)}
    for k, v in lists.items():
        out[k] = v[:limit]
    if any(len(v) > limit for v in lists.values()):
        out["truncated"] = f"Each list shows at most {limit}: narrow it to a position (it and what's inside it)."
    return out
