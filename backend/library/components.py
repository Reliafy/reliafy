"""Components as sets of failure modes (NRC/INL industry averages).

The NRC/INL report splits a component into failure modes by what sets them off (INL/EXT-21-65055,
Table 1 and the Appendix A data sheets):

- **per demand**: fails to start, to open, to close (a probability on each demand, a beta);
- **per hour of running**: fails to run, often split into the first hour of running (FTR≤1H, "fail
  to run for 1 hour of operation") and after it (FTR>1H, "fail to run after 1 hour of operation";
  abbreviations, p. xviii), or fails to load and run early (FTLR) and fails to run after;
- **per calendar hour**: leaks, spurious operation, plugging, fails to operate: exposure counted in
  reactor-year hours, whether the plant was running or shut down (§1.2.1 item 5, p. 3).

A component here is one equipment type in one of the report's pooling groups (normally standby,
normally running, a system such as service water, a rating, a service): its modes brought together.
Records are grouped by their name and qualifier (``conditions``: operating mode, system, rating,
plant type, service), a generic mode (no qualifier) joining every group of its name that has no mode
of its own in the same family; :data:`ALTERNATIVES` names the irregular ones by hand. A component
with fewer than two modes isn't listed: it's the record itself.

How the modes combine, over a period with ``demands`` (D), ``running_hours`` (H) and
``calendar_hours`` (T): the modes are independent competing risks, so the component survives the
period only if every mode does::

    R = Π (1 − q_d)^D × exp(−[Σ λ_1h × h1 + Σ λ_>1h × (H − h1) + Σ λ_run × H + Σ λ_cal × T])
    P(fails over the period) = 1 − R

where h1 = min(H, D × 1 h) is the first hour of each run (at least one start when it runs). For small
numbers this is the plain sum the NRC's risk models use for a standby component over a mission,
P ≈ D·q(FTS) + λ(FTR≤1H) × 1 h + λ(FTR>1H) × (t − 1 h) + λ(leak) × t (NUREG/CR-6928's convention: a
rare-event sum of the modes): both are shown. As a constant rate for an RBD block, the component's
average hazard over the period, −ln R ÷ T per calendar hour.

Two pairs aren't added: a valve's "fails to open or close" (FTOC) pools its fails-to-open and
fails-to-close over the same demands (Table 1: AOV-FTOC counts 83 failures in the 165,942 demands
FTO's 50 and FTC's 27 come from), so where FTOC is given FTO and FTC are its more specific
alternatives. A sensor's "fails to operate" has both a demand and a calendar contribution (A-7.3.2,
p. A-85), so both of those are added.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import Any, Optional

from backend.library import schema

SOURCE = "nrc-inl-2020"
#: The qualifiers that make a pooling group, in the order they're named.
QUALIFIERS = ("operating_mode", "system", "rating", "plant_type", "service")
MODE_WORDS = {"standby": "normally standby", "running": "normally running"}
#: Failure-mode codes in one family: a group's own mode replaces the generic one of its family.
FAMILIES = {"FTS": "start", "FTR": "run", "FTR<1H": "run", "FTR>1H": "run", "FTLR": "run",
            "FTO": "open_close", "FTC": "open_close", "FTOC": "open_close"}
#: Records that are another's narrower alternative in the same group, by source code: they're listed
#: with the component but not added (the report gives both; one includes the other).
ALTERNATIVES = {
    "STR-FLTSC-PG-EE-SSW": ("STR-FLTSC-PG-SSW", "plugging from the environment only: part of “plugs”"),
    "HTX-PG-NE-CCW": ("HTX-PG-CCW", "plugging outside extreme environments only: part of “plugs”"),
    # A reactor trip breaker's parts (mechanical, shunt trip, undervoltage trip) beside the whole
    # breaker's fails to open or close: the parts are inside the whole, so only the whole counts (and,
    # with one mode left, the breaker is its record, not a component).
    "RTB-FTOC-BME": ("RTB-FTOC", "the breaker's mechanism only: part of the whole breaker's"),
    "RTB-FTOP-BSN": ("RTB-FTOC", "the shunt trip only: part of the whole breaker's"),
    "RTB-FTOP-BUV": ("RTB-FTOC", "the undervoltage trip only: part of the whole breaker's"),
}
#: Labels the qualifiers don't read well as, fixed by hand (checked by eye, 9 Nov 2026).
LABELS = {
    ("Self-cleaning strainer", "running", (("system", "Service water (normally running)"),)):
        "Self-cleaning strainer (service water, normally running)",
    ("Turbine-driven pump", "standby", (("system", "High-pressure coolant injection / Reactor core isolation cooling"),)):
        "Turbine-driven pump (normally standby, high-pressure coolant injection or reactor core isolation cooling)",
    ("Circuit breaker", None, (("rating", "High voltage (13.8 and 16 kV)"),)): "Circuit breaker, high voltage (13.8 and 16 kV)",
    ("Circuit breaker", None, (("rating", "Medium voltage (4160 V and 6.9 kV)"),)):
        "Circuit breaker, medium voltage (4,160 V and 6.9 kV)",
    ("Circuit breaker", None, (("rating", "Low voltage (480 V)"),)): "Circuit breaker, low voltage (480 V)",
    ("Circuit breaker", None, (("rating", "DC"),)): "Circuit breaker (DC)",
    ("Filter", None, (("system", "Raw (untreated) water"),)): "Filter (raw, untreated water)",
}
#: Triggers, in words, in the order a component lists them.
TRIGGERS = {
    "demand": "Per demand",
    "first_hour": "Per hour of running, the first hour of each run",
    "after_first_hour": "Per hour of running, after the first hour",
    "running": "Per hour of running",
    "calendar": "Per calendar hour",
}
DEMANDS, RUNNING, CALENDAR, LENGTH = "demands", "running_hours", "calendar_hours", "length_ft"
DRAWS = 4000


class ComponentNotFound(LookupError):
    pass


def _code(rec: dict) -> str:
    return (rec.get("failure_mode") or {}).get("code") or ""


def _family(rec: dict) -> str:
    return FAMILIES.get(_code(rec), _code(rec))


def _op_mode(rec: dict) -> Optional[str]:
    """normally standby / normally running: said by the record, or implied by a first-hour split
    (the report gives FTR≤1H and FTR>1H for standby equipment)."""
    m = (rec.get("conditions") or {}).get("operating_mode")
    if m:
        return m
    if _code(rec) in ("FTR<1H", "FTR>1H"):
        return "standby"
    return None


def _context(rec: dict) -> tuple:
    cond = rec.get("conditions") or {}
    return tuple((k, cond[k]) for k in QUALIFIERS[1:] if cond.get(k))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _trigger(rec: dict, has_first_hour: bool) -> str:
    if rec.get("kind") == "per_demand":
        return "demand"
    if (rec.get("units") or {}).get("time_basis") == "calendar":
        return "calendar"
    code = _code(rec)
    if code in ("FTR<1H", "FTLR"):
        return "first_hour"
    if code == "FTR>1H" or (code == "FTR" and has_first_hour):
        return "after_first_hour"
    return "running"


def _lower_first(text: str) -> str:
    """'Service water' → 'service water'; 'DC' stays."""
    t = str(text)
    return t[:1].lower() + t[1:] if len(t) > 1 and t[1:2].islower() else t


def _variant_name(name: str, mode: Optional[str], context: tuple) -> str:
    if (name, mode, context) in LABELS:
        return LABELS[(name, mode, context)]
    words = ([MODE_WORDS.get(mode, mode)] if mode else []) + [_lower_first(v) for _, v in context]
    return f"{name} ({', '.join(words)})" if words else name


def _pick(records: list[dict], mode: Optional[str], context: tuple, generic: list[dict]) -> list[dict]:
    """A group's records: its own (this context, and this operating mode or none), then the generic
    ones (no qualifier) in families it has no mode of, for this operating mode or none."""
    own = [r for r in records if _context(r) == context and _op_mode(r) in (mode, None)]
    covered = {_family(r) for r in own}
    extra = [r for r in generic if r not in own and _family(r) not in covered and _op_mode(r) in (mode, None)]
    return own + extra


def _modes(records: list[dict]) -> list[dict]:
    """The group's records as modes: each with its trigger, whether it's added (FTO and FTC beside
    an FTOC, and the hand-named narrower ones, aren't) and why not."""
    codes = {_code(r) for r in records}
    by_code = {r["source_code"]: r for r in records}
    has_first = any(_code(r) in ("FTR<1H", "FTLR") for r in records)
    out = []
    for r in records:
        counted, why = True, None
        if _code(r) in ("FTO", "FTC") and "FTOC" in codes:
            counted, why = False, "pooled into “fails to open or close”, which is added"
        alt = ALTERNATIVES.get(r["source_code"])
        if alt and alt[0] in by_code:
            counted, why = False, alt[1]
        out.append({"record_id": r["id"], "code": r["source_code"], "mode_code": _code(r),
                    "mode": r["failure_mode"]["name"], "trigger": _trigger(r, has_first), "counted": counted,
                    **({"not_added": why} if why else {})})
    order = list(TRIGGERS)
    out.sort(key=lambda m: (not m["counted"], order.index(m["trigger"])))
    return out


@lru_cache(maxsize=1)
def _components() -> dict[str, dict]:
    from backend.library import service as library

    records = [r for r in library._library()["records"] if r["source"] == SOURCE]
    by_name: dict[str, list[dict]] = {}
    for r in records:
        by_name.setdefault(r["name"], []).append(r)
    out: dict[str, dict] = {}
    for name, recs in by_name.items():
        generic = [r for r in recs if not _context(r)]
        contexts = sorted({_context(r) for r in recs}, key=lambda c: (len(c), c))
        if () not in contexts:
            contexts.insert(0, ())
        for ctx in contexts:
            pool = [r for r in recs if _context(r) == ctx] if ctx else generic
            modes = sorted({_op_mode(r) for r in pool} - {None}) or [None]
            for mode in modes:
                group = _pick(recs, mode, ctx, generic)
                listed = _modes(group)
                if sum(m["counted"] for m in listed) < 2:
                    continue  # one mode is the record itself
                label = _variant_name(name, mode, ctx)
                cid = f"{SOURCE}:component:{_slug(label)}"
                if cid in out:
                    continue
                out[cid] = {"id": cid, "source": SOURCE, "name": name, "label": label, "operating_mode": mode,
                            "context": dict(ctx), "equipment_type": group[0]["equipment_type"], "modes": listed}
    return out


def all_components(source: Optional[str] = None) -> list[dict]:
    """Every component (of ``source``), in the source's own order."""
    rows = list(_components().values())
    return [c for c in rows if source in (None, c["source"])]


def is_component_id(cid: str) -> bool:
    return ":component:" in str(cid or "")


def get(cid: str) -> dict:
    c = _components().get(str(cid or "").strip())
    if c is None:
        raise ComponentNotFound(f"Library component '{cid}' not found. List them with the source's components.")
    return c


def _record(rid: str) -> dict:
    from backend.library import service as library

    return library.get(rid)


def inputs(comp: dict) -> list[dict]:
    """The component's covariates (the shape NSWC-11's inputs have): demands, running hours and
    calendar hours over the period, and a pipe's length for a rate per foot."""
    triggers = {m["trigger"] for m in comp["modes"] if m["counted"]}
    out = []
    positive = [{"min": 0, "severity": "refuse", "why": "it can't be negative"}]
    if "demand" in triggers:
        out.append({"key": DEMANDS, "name": DEMANDS, "kind": "number", "label": "Demands in the period",
                    "unit": "demands", "role": "use", "group": None, "limits": positive,
                    "help": "Starts, openings, closings or trips in the period: each can fail on demand."})
    if triggers & {"first_hour", "after_first_hour", "running"}:
        out.append({"key": RUNNING, "name": RUNNING, "kind": "number", "label": "Running hours in the period",
                    "unit": "hours", "role": "use", "group": None, "limits": positive,
                    "help": "Hours it runs in the period, in total: fails-to-run modes count these."})
    if any(_record(m["record_id"])["units"]["value"] == "per_hour_per_foot" for m in comp["modes"]):
        out.append({"key": LENGTH, "name": LENGTH, "kind": "number", "label": "Pipe length", "unit": "ft",
                    "role": "design", "group": None,
                    "limits": [{"min": 0, "exclusive": True, "severity": "refuse", "why": "a pipe has some length"}],
                    "help": "The source's leak rates are per foot of pipe."})
    out.append({"key": CALENDAR, "name": CALENDAR, "kind": "number", "label": "Calendar hours in the period",
                "unit": "hours", "role": "use", "group": None, "default": 8760.0, "default_basis": "year",
                "limits": [{"min": 0, "exclusive": True, "severity": "refuse", "why": "a period has some length"}],
                "help": "How long the period is (8,760 hours is a year): leaks and spurious operation count these, "
                        "running or not."})
    return out


class ComponentError(ValueError):
    def __init__(self, problems: list[str], missing: Optional[list[str]] = None):
        self.problems, self.missing = list(problems), list(missing or [])
        super().__init__(" ".join(self.problems))


def _read(comp: dict, values: Optional[dict]) -> dict:
    ins = inputs(comp)
    given = {k: v for k, v in (values or {}).items() if v is not None and v != ""}
    known = {i["key"] for i in ins}
    problems, missing, out = [], [], {}
    unknown = sorted(k for k in given if k not in known)
    if unknown:
        problems.append(f"Unknown covariate{'s' if len(unknown) != 1 else ''} {', '.join(unknown)}: "
                        f"{comp['label']} reads {', '.join(sorted(known))}.")
    for i in ins:
        raw = given.get(i["key"], i.get("default"))
        if raw is None:
            problems.append(f"{i['label']} is needed, in {i['unit']}: there's no default.")
            missing.append(i["key"])
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            problems.append(f"{i['label']} must be a number, not '{raw}'.")
            continue
        lim = i["limits"][0]
        if not math.isfinite(v) or v < lim["min"] or (lim.get("exclusive") and v == lim["min"]):
            problems.append(f"{i['label']} must be {'more than' if lim.get('exclusive') else 'at least'} "
                            f"{lim['min']:g}: {lim['why']}.")
            continue
        out[i["key"]] = v
    if RUNNING in out and CALENDAR in out and out[RUNNING] > out[CALENDAR]:
        problems.append("Running hours can't be more than the calendar hours in the period.")
    if problems or missing:
        raise ComponentError(problems, missing)
    return out


def _params(rec: dict) -> tuple[str, dict]:
    d = rec["distribution"]
    return d["family"], schema.param_dict(d)


def _exposures(v: dict) -> dict:
    d, h, t = v.get(DEMANDS, 0.0), v.get(RUNNING, 0.0), v[CALENDAR]
    h1 = min(h, max(d, 1.0) * 1.0) if h > 0 else 0.0
    return {"demand": d, "first_hour": h1, "after_first_hour": h - h1, "running": h, "calendar": t}


def evaluate(cid_or_comp: Any, values: Optional[dict] = None, draws: int = DRAWS) -> dict:
    """P(the component fails over the period), each mode's share, the rare-event sum and the
    equivalent constant rate per calendar hour, with a 5–95% range from the modes' own
    distributions (the source's spread from plant to plant: independent draws, seed fixed).
    Raises :class:`ComponentError` naming what's missing."""
    import numpy as np

    comp = cid_or_comp if isinstance(cid_or_comp, dict) else get(cid_or_comp)
    v = _read(comp, values)
    exp = _exposures(v)
    feet = v.get(LENGTH, 1.0)
    rng = np.random.default_rng(20201)
    log_r = 0.0
    log_r_draws = np.zeros(draws)
    rows = []
    rare = 0.0
    for m in comp["modes"]:
        rec = _record(m["record_id"])
        family, p = _params(rec)
        mean = schema.mean_of(family, p)
        e = exp[m["trigger"]]
        scale = feet if rec["units"]["value"] == "per_hour_per_foot" else 1.0
        row = {**m, "label": rec["label"], "mean": mean * scale,
               "unit": "per demand" if m["trigger"] == "demand" else (
                   "per hour per foot" if scale != 1.0 else "per hour"),
               "exposure": e, "exposure_unit": "demands" if m["trigger"] == "demand" else "hours"}
        if not m["counted"]:
            rows.append(row)
            continue
        if m["trigger"] == "demand":
            contrib = -e * math.log1p(-mean) if mean < 1 else math.inf
            expected = e * mean
            if family == "beta":
                q = rng.beta(p["alpha"], p["beta"], draws)
            elif family == "lognormal":
                q = np.minimum(rng.lognormal(p["mu"], p["sigma"], draws), 1 - 1e-12)
            else:
                q = np.full(draws, mean)
            log_r_draws -= e * np.log1p(-q)
        else:
            lam = mean * scale
            contrib = lam * e
            expected = contrib
            if family == "gamma":
                d = rng.gamma(p["alpha"], 1 / p["beta"], draws) * scale
            elif family == "lognormal":
                d = rng.lognormal(p["mu"], p["sigma"], draws) * scale
            else:
                d = np.full(draws, lam)
            log_r_draws += d * e
        log_r += contrib
        rare += expected
        row.update(expected_failures=expected, probability=-math.expm1(-contrib))
        rows.append(row)
    p_fail = -math.expm1(-log_r)
    pd = -np.expm1(-log_r_draws)
    counted = [r for r in rows if r["counted"]]
    for r in counted:
        r["share"] = (r["expected_failures"] / rare) if rare > 0 else 0.0
    t = v[CALENDAR]
    rate = log_r / t
    return {"component_id": comp["id"], "label": comp["label"], "covariates": v, "exposures": exp,
            "probability": p_fail, "reliability": math.exp(-log_r), "rare_event_sum": rare,
            "bounds": {"p05": float(np.quantile(pd, 0.05)), "p95": float(np.quantile(pd, 0.95))},
            "rate_per_calendar_hour": rate, "bounds_rate": {"p05": float(np.quantile(log_r_draws, 0.05)) / t,
                                                             "p95": float(np.quantile(log_r_draws, 0.95)) / t},
            "modes": rows, "words": _words(comp, v, exp, p_fail, rare)}


def _words(comp: dict, v: dict, exp: dict, p: float, rare: float) -> str:
    def n(x: float) -> str:
        return f"{float(f'{x:.3g}'):g}"

    bits = []
    if DEMANDS in v:
        bits.append(f"{n(v[DEMANDS])} demands")
    if RUNNING in v:
        bits.append(f"{n(v[RUNNING])} running hours (the first {n(exp['first_hour'])} of them first hours of a run)"
                    if any(m["trigger"] == "first_hour" and m["counted"] for m in comp["modes"])
                    else f"{n(v[RUNNING])} running hours")
    bits.append(f"{n(v[CALENDAR])} calendar hours")
    return (f"Over {', '.join(bits)}, the chance it fails is {n(p)} (the modes as competing risks; their plain "
            f"sum, the rare-event approximation, is {n(rare)}).")


def brief(comp: dict) -> dict:
    """A component in a list: its modes in a few words."""
    counted = [m for m in comp["modes"] if m["counted"]]
    return {"id": comp["id"], "label": comp["label"], "name": comp["name"], "source": comp["source"],
            "equipment_type": comp["equipment_type"], "operating_mode": comp["operating_mode"],
            "context": comp["context"], "modes": len(counted), "alternatives": len(comp["modes"]) - len(counted),
            "triggers": sorted({m["trigger"] for m in counted}, key=list(TRIGGERS).index),
            "mode_names": [m["mode"] for m in counted]}


def detail(cid: str) -> dict:
    """A component in full: its modes (each record in brief, with its trigger), its covariates, and
    how they combine."""
    from backend.library import service as library

    comp = get(cid)
    modes = []
    for m in comp["modes"]:
        rec = _record(m["record_id"])
        modes.append({**m, "record": library.brief(rec), "trigger_words": TRIGGERS[m["trigger"]]})
    src = library._library()["sources"].get(comp["source"], {})
    return {**brief(comp), "modes": modes, "inputs": inputs(comp), "how": HOW,
            "citation": f"{src.get('report') or src.get('name')}, Table 1 and Appendix A",
            "caveats": src.get("caveats") or []}


#: How the modes combine, in words first (shown on the component page).
HOW = ("The component survives the period only if no mode fails: each mode is a competing risk. Every demand can "
       "fail to start, open or close; each hour of running can fail to run (the first hour of each run at its own "
       "rate where the source gives one); each calendar hour can leak or operate spuriously, running or not. "
       "P(fails) = 1 − Π(1 − q)^demands × exp(−Σ λ × its hours). For small numbers that's close to the plain sum "
       "the NRC's risk models use for a mission (fails to start + fails to run in the first hour × 1 h + after the "
       "first hour × the rest + leaks × the period). As a constant rate for an RBD block: −ln(R) ÷ calendar hours.")
