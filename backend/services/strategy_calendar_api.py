"""The web side of replacement over a shutdown calendar: which method runs
where, and who may run it. The calculation itself is
:mod:`backend.services.strategy_calendar` (no database, so the compute
service can run it too).

- ``dp`` and ``integration`` are exact and free: they answer at once, here.
- ``sampling`` is Pro (it can take a minute): 402 for anyone else; with the
  compute queue configured it is a job (202, poll ``/api/rbd-jobs/{id}``),
  otherwise (self-hosted) it runs here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from backend.services import compute_core
from backend.services import rbd_jobs as rbd_jobs_service
from backend.services import strategy_calendar

SAMPLING_PRO_PAYLOAD = {
    "detail": ("Sampling runs the calendar many times on Reliafy's calculation service, so it's part of Pro. "
               "The exact methods are free."),
    "code": "pro_required",
    "upgrade": True,
}


def run(db, user: dict, inputs: dict, *, entitled: bool) -> tuple[int, dict]:
    """``(status, payload)`` for a calendar-replacement request (the
    endpoint body as ``inputs``). Raises ``StrategyError`` for the user's
    inputs (and ``AnalysisError`` from an in-process sampled run)."""
    method = str(inputs.get("method") or "dp").strip().lower()
    # One "today" for the whole run (and the job's cache key).
    inputs = {**inputs, "today": inputs.get("today") or date.today().isoformat()}
    if method != "sampling":
        args = {k: v for k, v in inputs.items() if k not in ("distribution_id", "params")}
        return 200, strategy_calendar.calendar_replacement(inputs.get("distribution_id"), inputs.get("params") or [],
                                                           **args)
    if not entitled:
        return 402, dict(SAMPLING_PRO_PAYLOAD)
    # Checked here, before anything is queued: a bad date fails at once.
    checked = {k: v for k, v in inputs.items() if k not in ("distribution_id", "params")}
    strategy_calendar.check_inputs(inputs.get("distribution_id"), inputs.get("params") or [], **checked)
    request = compute_core.calendar_request(inputs)
    key = "calendar|" + hashlib.sha256(json.dumps(request, sort_keys=True, default=str).encode()).hexdigest()
    return rbd_jobs_service.run_calendar(db, uid=user.get("uid") or "", request=request, cache_key=key)
