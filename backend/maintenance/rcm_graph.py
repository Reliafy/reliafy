"""Evidence checks for the RCM on the maintenance positions.

A failure mode's decision on the graph links the saved model or analysis that
justifies it (``evidence`` on the mode), as a decision in an RCM study does.
The check is the study's own (backend/services/rcm.py ``resolve_decision``):
done on every read, never stored, so the RCM tab and a study give the same
answer for the same decision and evidence.
"""

from __future__ import annotations

from backend.services import rcm as rcm_service


def resolve(db, worksheet: dict, owner_id, hidden=frozenset()) -> dict:
    """``worksheet`` (Maintenance.rcm_worksheet) with each decision's evidence
    status, and a rollup per position and for the whole of it (as a study's)."""
    fetch = rcm_service.evidence_fetcher(db, owner_id, hidden)
    total = rcm_service.blank_rollup()
    positions = []
    for p in worksheet["positions"]:
        rollup = rcm_service.blank_rollup()

        def mode_out(mode: dict) -> dict:
            rollup["modes"] += 1
            decision = mode.get("decision")
            if not decision:
                return mode
            rollup["decided"] += 1
            resolved = rcm_service.resolve_decision(decision, fetch)
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
    fetch = rcm_service.evidence_fetcher(db, owner_id, hidden)
    return {**mode, "decision": {**decision, **rcm_service.resolve_decision(decision, fetch)}}


def evidence_refs(decision) -> list[tuple[str, str]]:
    """The (collection, id) a decision links as evidence, for access.check_references."""
    from backend.services import access

    return access.evidence_refs([{"failures": [{"modes": [{"decision": decision or {}}]}]}])
