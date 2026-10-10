"""Refit the runtime quote's machine factors from logged runs (#286).

Every finished availability simulation logs its time against the quote's
model (``rbd_runtime_log``). This refits each machine's factor from them
(:func:`backend.services.runtime_quote.refit_factor`): SurPyval's
log-normal on the actual-over-predicted ratios, its median the new factor.

    # Dry run (default): each machine's logged runs, its factor now and the refit.
    python -m backend.scripts.refit_runtime_factor [--machine compute]

    # Store the refits (the quotes use them at once).
    python -m backend.scripts.refit_runtime_factor --apply

The same is ``GET /api/admin/runtime-quote`` and ``POST
/api/admin/runtime-quote/refit`` for operators. It uses the MONGODB_URI
environment of wherever it runs.
"""

from __future__ import annotations

import argparse


def main(argv=None) -> int:
    from backend.db import get_db
    from backend.services import runtime_quote

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--machine", help="only this machine type (default: every one with logged runs)")
    ap.add_argument("--apply", action="store_true", help="store the refitted factors")
    a = ap.parse_args(argv)
    db = get_db()
    machines = [a.machine] if a.machine else sorted(m for m in db.rbd_runtime_log.distinct("machine") if m)
    if not machines:
        print("No logged runs yet.")
        return 0
    for machine in machines:
        cal = runtime_quote.calibration(db, machine)
        out = runtime_quote.refit_factor(db, machine, apply=a.apply)
        within = "—" if cal["within_ceiling"] is None else format(cal["within_ceiling"], ".0%")
        print(f"{machine}: {cal['runs']} runs ({cal['observed']} observed), factor now {cal['factor']:.3g}, "
              f"within the quoted ceiling {within}")
        if out["refitted"]:
            note = " (stored)" if out["applied"] else " (dry run: --apply stores it)"
            print(f"  refit: {out['factor']:.3g}{note}")
        else:
            print(f"  not refitted: {out['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
