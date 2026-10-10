"""Time one availability job, in a process of its own (see run.py).

Reads ``{"graph", "options", "cap_s"}`` as JSON on stdin and writes one JSON
line: ``status`` ok / censored / nosim / error, the job's wall and CPU
seconds, the replications it reported, and the exact-only time of the same
diagram (the part of the job that doesn't depend on the replications).

The job is exactly what the compute service runs
(``compute_core.run_availability``). A warm-up on a small diagram first keeps
one-time import and set-up costs out of the timing. A run still going at
``cap_s`` is stopped there: right-censored at the cap.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time

for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(var, "1")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


class _Cap(BaseException):
    """The cap. A BaseException, so the analysis's own ``except Exception``
    blocks can't swallow it and carry on past the cap."""


def _alarm(signum, frame):
    raise _Cap


def _warm_up(compute_core):
    from tools.quote_bench.generate import design
    small = design(0, master_seed=1)
    small["options"]["n_simulations"] = 20
    try:
        compute_core.run_availability({"graph": small["graph"], "options": small["options"]})
    except Exception:  # noqa: BLE001 - a warm-up only
        pass


def main() -> None:
    req = json.load(sys.stdin)
    from backend.services import compute_core, rbd_analysis

    _warm_up(compute_core)
    cap = float(req.get("cap_s") or 60.0)
    out: dict = {"cap_s": cap}
    signal.signal(signal.SIGALRM, _alarm)
    w0, c0 = time.perf_counter(), time.process_time()
    try:
        signal.setitimer(signal.ITIMER_REAL, cap)
        result = compute_core.run_availability({"graph": req["graph"], "options": req["options"]})
        signal.setitimer(signal.ITIMER_REAL, 0)
        out.update(seconds=time.perf_counter() - w0, cpu_seconds=time.process_time() - c0)
        if out["seconds"] >= cap:  # past the cap without the alarm landing: censored all the same
            raise _Cap
        n = result.get("n_simulations") or (result.get("simulation") or {}).get("n_simulations")
        has_sim = bool(result.get("precision") or result.get("availability_curve") or n)
        out.update(status="ok" if has_sim else "nosim", replications=n,
                   ccf_included=(result.get("common_cause") or {}).get("included"))
    except _Cap:
        out.update(status="censored", seconds=cap, cpu_seconds=time.process_time() - c0)
    except Exception as exc:  # noqa: BLE001
        signal.setitimer(signal.ITIMER_REAL, 0)
        out.update(status="error", seconds=time.perf_counter() - w0, error=f"{type(exc).__name__}: {exc}"[:300])
    # The part that doesn't scale with replications: the exact figures alone.
    if out["status"] in ("ok", "censored"):
        try:
            signal.setitimer(signal.ITIMER_REAL, cap)
            t0 = time.perf_counter()
            rbd_analysis.analyze_availability(req["graph"], resolve_model=compute_core._no_saved_models,
                                              t_simulation=req["options"].get("t_simulation"), simulate=False)
            out["exact_seconds"] = time.perf_counter() - t0
        except _Cap:
            out["exact_seconds"] = None
        except Exception:  # noqa: BLE001
            out["exact_seconds"] = None
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
    print(json.dumps(out, default=str))


if __name__ == "__main__":
    main()
