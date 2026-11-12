"""Download as Python for the Test planning calculators.

A test plan isn't a saved model: the download takes the inputs the
calculator was given. They are checked by running the calculator itself
(so a bad input is refused with the calculator's own words), then read the
way the calculator reads them (confidence as a significance level, a
percentage as a share, ...), and the script calls the same SurPyval
``test_planning`` functions with those exact values and prints the plan's
headline numbers.

Kinds: ``demonstration`` (the demonstration test, ``/api/strategy/
demonstration-test``), ``sequential``, ``life``, ``accelerated`` and
``comparison``.
"""

from __future__ import annotations

from typing import Any, Callable

from backend.services import python_export as px
from backend.services import strategy as strategy_service
from backend.services import test_planning as tp_service
from backend.services.strategy import StrategyError, _blank, _demo_count, _demo_positive, _demo_prob

KINDS = ("demonstration", "sequential", "life", "accelerated", "comparison")

_TITLES = {
    "demonstration": "Demonstration test",
    "sequential": "Sequential test",
    "life": "Life test",
    "accelerated": "Accelerated life test",
    "comparison": "Comparison test",
}


#: The test-planning calculators, by kind (MCP's plan actions call them through here).
CALCULATORS = {
    "sequential": tp_service.sequential_test,
    "life": tp_service.life_test,
    "accelerated": tp_service.accelerated_test,
    "comparison": tp_service.comparison,
}


def _run_calculator(kind: str, body: dict) -> dict:
    """The calculator's answer for ``body`` (raises its refusals)."""
    if kind == "demonstration":
        return strategy_service.demonstration_test(**body)
    return CALCULATORS[kind](**body)


def export_python(kind: str, body: dict) -> tuple[str, str]:
    """``(filename, source)``: a SurPyval script that works out the plan for
    ``body`` (the calculator's inputs) and prints it. Raises
    :class:`StrategyError` (or TypeError / ValueError for an unknown field or
    a value of the wrong type) as the calculator does."""
    if kind not in KINDS:
        raise StrategyError(f"kind must be one of: {', '.join(KINDS)}.")
    body = dict(body or {})
    result = _run_calculator(kind, body)
    build: Callable[[dict, dict], tuple[list[str], list[str]]] = _BUILDERS[kind]
    notes, code = build(body, result)
    unit = (result.get("unit") or "").strip()
    head = px.header(_TITLES[kind], "a test plan worked out with SurPyval's test_planning.",
                     notes=notes, unit=unit, lead=_PLAN_LEAD)
    source = px.assemble(
        head,
        ["import numpy as np", "from surpyval import test_planning as tp", ""],
        px.PRINT_HELPERS,
        ["", ""],
        code,
    )
    return px.filename(f"{_TITLES[kind]} plan", "test_plan"), source


#: The header's opening sentence: a test plan is worked out, not refitted.
_PLAN_LEAD = ("Exported from Reliafy. It works out the plan from the inputs you gave the",
              "calculator, with the same SurPyval functions the app uses, and prints the",
              "numbers the page shows.")


def _u(result: dict) -> str:
    return px.literal((result.get("unit") or "").strip())


# ---------------------------------------------------------------------------
# Demonstration test
# ---------------------------------------------------------------------------

def _demonstration(body: dict, result: dict) -> tuple[list[str], list[str]]:
    c = float(result["confidence"])
    alpha = 1.0 - c  # the demonstration engine's significance level
    r = int(result["failures"])
    if result["method"] == "mtbf":
        ft = bool(result.get("failure_terminated"))
        two_risk = bool(result.get("two_risk"))
        lines = [
            *px.comment("The requirement: the MTBF to demonstrate, at this confidence."),
            f"TARGET_MTBF = {px.num(result['mtbf'])}",
            f"ALPHA = {px.num(alpha)}  # 1 - confidence: the chance a design only at the target passes",
            f"UNIT = {_u(result)}",
            "",
        ]
        if two_risk:
            lines += [
                *px.comment("A plan that keeps both risks: a good design (this MTBF) fails at most PRODUCER_RISK "
                            "of the time. The plan chooses the failures allowed and the shortest test."),
                f"GOOD_MTBF = {px.num(result['design_mtbf'])}",
                f"PRODUCER_RISK = {px.num(result['producer_risk_target'])}",
                f"plan = tp.mtbf_demonstration_plan(TARGET_MTBF, GOOD_MTBF, alpha_ci=ALPHA, "
                f"producer_risk=PRODUCER_RISK, max_failures={strategy_service._DEMO_MAX_FAILURES})",
                "failures = int(plan.failures)",
                "total = float(plan.test_time)",
            ]
        else:
            lines += [
                *px.comment("The total test time (across all units) that shows the target with at most this many "
                            "failures" + (" (the test stops at that failure)." if ft else ".")),
                f"failures = {r}",
                "total = float(tp.mtbf_test_time(TARGET_MTBF, failures, alpha_ci=ALPHA"
                + (", failure_terminated=True" if ft else "") + "))",
            ]
        ftk = ", failure_terminated=True" if ft else ""
        lines += [
            "",
            "print_value('Total test time', total, UNIT)",
            "print_value('Failures allowed', failures)",
        ]
        if result.get("units"):
            lines += [f"units = {int(result['units'])}",
                      "print_value('Test time per unit', total / units, UNIT)"]
        lines += [
            "# The consumer's risk: how often a design exactly at the target still passes.",
            f"print_value('Chance a design at the target passes', tp.mtbf_pass_probability(TARGET_MTBF, total, "
            f"failures{ftk}))",
        ]
        if result.get("design_mtbf") is not None:
            if not two_risk:
                lines.append(f"GOOD_MTBF = {px.num(result['design_mtbf'])}")
            lines += [
                "# How often a design with this true MTBF passes (one minus the producer's risk).",
                f"print_value('Chance the good design passes', tp.mtbf_pass_probability(GOOD_MTBF, total, "
                f"failures{ftk}))",
            ]
        return ["A constant failure rate (exponential lifetimes): only the total time on test matters."], lines

    # Attribute (pass/fail) test.
    R = float(result["reliability"])
    k = float(result["test_multiple"])
    beta = result.get("shape")
    pr = result.get("producer_risk_target")
    design = result.get("design_reliability")
    t = result.get("mission_time")
    lines = [
        *px.comment("The requirement: the reliability over one mission to demonstrate, at this confidence."),
        f"TARGET_RELIABILITY = {px.num(R)}",
        f"ALPHA = {px.num(alpha)}  # 1 - confidence: the chance a design only at the target passes",
        f"SHAPE = {px.num(beta)}  # the Weibull shape (beta) of the life, when the test isn't one mission long",
        f"UNIT = {_u(result)}",
    ]
    if t is not None:
        lines.append(f"MISSION_TIME = {px.num(t)}")
    lines.append("")
    if result["solve_for"] == "test_time":
        lines.append(f"units = {int(result['units'])}")
        if pr is not None:
            lines += [
                *px.comment("A plan that keeps both risks: the plan chooses the failures allowed and the "
                            "shortest test per unit."),
                f"GOOD_RELIABILITY = {px.num(design)}",
                f"plan = tp.demonstration_plan(TARGET_RELIABILITY, GOOD_RELIABILITY, alpha_ci=ALPHA, "
                f"producer_risk={px.num(pr)}, n=units, test_multiple=1.0, shape=SHAPE, "
                f"max_failures={strategy_service._DEMO_MAX_FAILURES})",
                "TEST_MULTIPLE, failures = float(plan.test_multiple), int(plan.failures)",
            ]
        else:
            lines += [
                *px.comment("How long each unit must run (as a multiple of the mission) to show the target."),
                f"failures = {r}",
                "TEST_MULTIPLE = float(tp.demonstration_test_multiple(TARGET_RELIABILITY, units, failures, "
                "shape=SHAPE, alpha_ci=ALPHA))",
            ]
    else:
        lines.append(f"TEST_MULTIPLE = {px.num(k)}  # how many missions each unit runs")
        if pr is not None:
            lines += [
                *px.comment("A plan that keeps both risks: the plan chooses the failures allowed and the fewest "
                            "units."),
                f"GOOD_RELIABILITY = {px.num(design)}",
                f"plan = tp.demonstration_plan(TARGET_RELIABILITY, GOOD_RELIABILITY, alpha_ci=ALPHA, "
                f"producer_risk={px.num(pr)}, n=None, test_multiple=TEST_MULTIPLE, shape=SHAPE, "
                f"max_failures={strategy_service._DEMO_MAX_FAILURES})",
                "units, failures = int(plan.n), int(plan.failures)",
            ]
        else:
            lines += [
                *px.comment("The units to test, each for TEST_MULTIPLE missions, allowing this many failures."),
                f"failures = {r}",
                "units = int(tp.demonstration_sample_size(TARGET_RELIABILITY, failures, alpha_ci=ALPHA, "
                "test_multiple=TEST_MULTIPLE, shape=SHAPE))",
            ]
    # The calculator passes the Weibull shape only when the test isn't one mission long.
    if result["solve_for"] == "test_time":
        lines.append("EXT = {'test_multiple': TEST_MULTIPLE, 'shape': SHAPE} if TEST_MULTIPLE != 1.0 else {}")
    else:
        lines.append("EXT = {'test_multiple': TEST_MULTIPLE, 'shape': SHAPE}" if k != 1.0 else "EXT = {}")
    lines += [
        "",
        "print_value('Units to test', units)",
        "print_value('Failures allowed', failures)",
        "print_value('Test length per unit (missions)', TEST_MULTIPLE)",
    ]
    if t is not None:
        lines += ["print_value('Test time per unit', TEST_MULTIPLE * MISSION_TIME, UNIT)",
                  "print_value('Total test time', TEST_MULTIPLE * MISSION_TIME * units, UNIT)"]
    lines += [
        "# The reliability this test shows if it passes.",
        "print_value('Reliability demonstrated', tp.demonstrated_reliability(units, failures, alpha_ci=ALPHA, "
        "**EXT))",
        "# The consumer's risk: how often a design exactly at the target still passes.",
        "print_value('Chance a design at the target passes', tp.demonstration_pass_probability("
        "TARGET_RELIABILITY, units, failures, **EXT))",
    ]
    if design is not None:
        if pr is None:
            lines.append(f"GOOD_RELIABILITY = {px.num(design)}")
        lines += [
            "# How often a design with this true reliability passes (one minus the producer's risk).",
            "print_value('Chance the good design passes', tp.demonstration_pass_probability(GOOD_RELIABILITY, "
            "units, failures, **EXT))",
        ]
    return ["Each unit passes or fails its mission independently (a binomial, pass/fail test)."], lines


# ---------------------------------------------------------------------------
# Sequential test
# ---------------------------------------------------------------------------

_KEEP_RISKS = [
    "def keeping_risks(build, alpha, beta):",
    '    """The sequential test, stopped at the fixed-length test, that keeps the risks asked for.',
    "",
    "    Stopping early moves the risks a little, so the lines are drawn tighter,",
    '    a step at a time, until a design at the target passes at most alpha of the time',
    '    and a good design fails at most beta of the time (as the app does)."""',
    "    a, b = alpha, beta",
    "    test = build(a, b)",
    "    for _ in range(60):",
    f"        over_c = float(test.consumer_risk) > alpha + {px.num(tp_service._RISK_TOL)}",
    f"        over_p = float(test.producer_risk) > beta + {px.num(tp_service._RISK_TOL)}",
    "        if not (over_c or over_p):",
    "            break",
    "        a = a * 0.95 if over_c else a",
    "        b = b * 0.95 if over_p else b",
    "        try:",
    "            test = build(a, b)",
    "        except ValueError:",
    "            break",
    "    return test",
    "",
]


def _sequential(body: dict, result: dict) -> tuple[list[str], list[str]]:
    alpha = tp_service._alpha(body.get("confidence"))
    beta = float(result["producer_risk_target"])
    lines = [*_KEEP_RISKS,
             f"ALPHA = {px.num(alpha)}  # consumer's risk asked: 1 - confidence",
             f"BETA = {px.num(beta)}  # producer's risk asked: the chance a good design fails", ""]
    decision = result.get("decision")
    if result["method"] == "mtbf":
        lines += [
            f"TARGET_MTBF = {px.num(result['mtbf'])}",
            f"GOOD_MTBF = {px.num(result['good_mtbf'])}",
            f"UNIT = {_u(result)}",
            "",
            "test = keeping_risks(lambda a, b: tp.sequential_mtbf_test(TARGET_MTBF, GOOD_MTBF, alpha_ci=a, "
            "producer_risk=b), ALPHA, BETA)",
            "# The fixed-length test with the same risks, for comparison.",
            "fixed = tp.mtbf_demonstration_plan(TARGET_MTBF, GOOD_MTBF, alpha_ci=ALPHA, producer_risk=BETA)",
            "at_target, at_good = (float(v) for v in np.atleast_1d(test.expected_test_time([TARGET_MTBF, "
            "GOOD_MTBF])))",
            "",
            "print_value('Chance a design at the target passes', test.consumer_risk)",
            "print_value('Chance a good design fails', test.producer_risk)",
            "print_value('Average test time, good design', at_good, UNIT)",
            "print_value('Average test time, design at the target', at_target, UNIT)",
            "print_value('Fixed-length test time', fixed.test_time, UNIT)",
            "print_value('Fixed-length test failures', fixed.failures)",
            "print_value('Longest it runs', test.max_time, UNIT)",
            "print_value('Most failures', test.max_failures)",
            "# The accept and reject lines: after each failure count, the total test time that passes",
            "# (accept) or, if the failure comes sooner, fails (reject) the design.",
            "lines = test.to_dict()['boundaries']",
            "for f, acc, rej in zip(lines['failures'], lines['accept_time'], lines['reject_time']):",
            "    print(f\"  {f} failures: accept after {fmt(acc)}, reject before {fmt(rej) if rej and rej > 0 "
            "else 'none'}\")",
        ]
        if decision:
            lines += ["", "# What the test says now.",
                      f"print('Decision:', test.decide({int(decision['failures'])}, {px.num(decision['test_time'])}))"]
    else:
        lines += [
            f"TARGET_RELIABILITY = {px.num(result['reliability'])}",
            f"GOOD_RELIABILITY = {px.num(result['good_reliability'])}",
            "",
            "test = keeping_risks(lambda a, b: tp.sequential_demonstration_test(TARGET_RELIABILITY, "
            "GOOD_RELIABILITY, alpha_ci=a, producer_risk=b), ALPHA, BETA)",
            "# The fixed-length test with the same risks, for comparison.",
            "fixed = tp.demonstration_plan(TARGET_RELIABILITY, GOOD_RELIABILITY, alpha_ci=ALPHA, "
            "producer_risk=BETA)",
            "at_target, at_good = (float(v) for v in np.atleast_1d(test.expected_units([TARGET_RELIABILITY, "
            "GOOD_RELIABILITY])))",
            "",
            "print_value('Chance a design at the target passes', test.consumer_risk)",
            "print_value('Chance a good design fails', test.producer_risk)",
            "print_value('Average units tested, good design', at_good)",
            "print_value('Average units tested, design at the target', at_target)",
            "print_value('Fixed-length test units', fixed.n)",
            "print_value('Fixed-length test failures', fixed.failures)",
            "print_value('Most units', test.max_units)",
            "print_value('Most failures', test.max_failures)",
        ]
        if decision:
            lines += ["", "# What the test says now.",
                      f"print('Decision:', test.decide({int(decision['units'])}, {int(decision['failures'])}))"]
    return ["A sequential (Wald) test, stopped at the fixed-length test with the same risks."], lines


# ---------------------------------------------------------------------------
# Life test
# ---------------------------------------------------------------------------

def _dist_line(d: str) -> str:
    return "from surpyval import Weibull as DIST" if d == "weibull" else "from surpyval import LogNormal as DIST"


def _life(body: dict, result: dict) -> tuple[list[str], list[str]]:
    d = result["distribution_id"]
    pv = tp_service._params(d, body.get("params"))
    p, what = tp_service._quantity(body.get("quantity"), body.get("b_life", 10))
    alpha = tp_service._alpha(body.get("confidence"))
    names = tp_service._PARAM_NAMES[d]
    solve = result["solve_for"]
    end = result["test_end"]
    kw = "p=P, quantity=QUANTITY, alpha_ci=ALPHA"
    lines = [
        _dist_line(d),
        "",
        *px.comment(f"Planning values: your best guess of the life before the test ({names[0]}, {names[1]})."),
        f"PLANNING_VALUES = ({px.num(pv[0])}, {px.num(pv[1])})",
        *px.comment(f"What the test estimates: {what}."),
        f"P = {px.num(p if p is not None else 0.1)}",
        f"QUANTITY = {'mean' if p is None else 'quantile'!r}",
        f"ALPHA = {px.num(alpha)}  # 1 - confidence",
        f"UNIT = {_u(result)}",
        "",
    ]
    if solve == "precision":
        if result.get("failures") is not None and end == "failures":
            args = f"failures={int(result['failures'])}"
        elif end == "time":
            args = f"censor_time={px.num(result['censor_time'])}"
        else:
            args = ""
        lines += [*px.comment("How precise the estimate is with this many units on test."),
                  f"plan = tp.life_test_precision(DIST, PLANNING_VALUES, {int(result['n'])}, "
                  f"{args + ', ' if args else ''}{kw})"]
    elif solve == "units":
        R = tp_service._precision_factor(body.get("precision"))
        if end == "time":
            args = f"censor_time={px.num(result['censor_time'])}, "
        elif end == "failures":
            args = f"failure_fraction={px.num(float(body.get('failure_fraction')))}, "
        else:
            args = ""
        lines += [*px.comment("The fewest units that estimate it to within the precision factor asked "
                              "(1.2 is within about ±20%)."),
                  f"plan = tp.life_test_sample_size(DIST, PLANNING_VALUES, {px.num(R)}, {args}{kw})"]
    else:
        R = tp_service._precision_factor(body.get("precision"))
        n = _demo_count(body.get("units"), "Units on test", 2, tp_service._MAX_UNITS)
        lines += [*px.comment("How long these units must run to reach the precision asked."),
                  f"plan = tp.life_test_length(DIST, PLANNING_VALUES, {n}, {px.num(R)}, "
                  f"failure_censored={end == 'failures'}, {kw})"]
    lines += [
        "",
        "print_value('Units on test', plan.n)",
        "print_value('Test stops at', plan.censor_time, UNIT)",
        "print_value('Test stops at failure', plan.failures)",
        "print_value('Expected failures', plan.expected_failures)",
        f"print_value('Estimate ({what})', plan.estimate, UNIT)",
        "# The precision factor: the confidence interval will run from about",
        "# estimate / precision to estimate x precision.",
        "print_value('Precision factor', plan.precision)",
        "print_value('Interval from', plan.estimate / plan.precision, UNIT)",
        "print_value('Interval to', plan.estimate * plan.precision, UNIT)",
    ]
    return ["The precision is a large-sample approximation from the test's expected information."], lines


# ---------------------------------------------------------------------------
# Accelerated life test
# ---------------------------------------------------------------------------

def _accelerated(body: dict, result: dict) -> tuple[list[str], list[str]]:
    d = result["distribution_id"]
    alpha = tp_service._alpha(body.get("confidence"))
    lm_key = result["life_model"]  # SurPyval's name for the life-stress model
    common = (f"use_stress=USE_STRESS, censor_time=TEST_LENGTH, p={px.num(result['p'])}, alpha_ci=ALPHA")
    lines = [
        _dist_line(d),
        "from surpyval.univariate.regression import accelerated_life",
        "",
        f"# The {result['life_model_name']} life-stress model, and its planning values.",
        f"LIFE_MODEL = accelerated_life.LIFE_MODELS[{lm_key!r}]",
        f"LIFE_PARAMS = {px.literal({k: float(v) for k, v in result['life_params'].items()})}",
        f"SHAPE = {px.num(result['shape'])}  # Weibull beta or lognormal sigma, the same at every stress",
        f"USE_STRESS = {px.num(result['use_stress'])}  # where the life is estimated",
        f"TEST_LENGTH = {px.num(result['censor_time'])}  # every unit runs this long",
        f"ALPHA = {px.num(alpha)}  # 1 - confidence",
        f"UNIT = {_u(result)}",
        "",
    ]
    if result["mode"] == "plan":
        hi = tp_service._stress(body.get("high_stress"), "Highest stress")
        n = _demo_count(body.get("units"), "Units on test", 2, 100_000)
        k = len(result["stresses"])
        alloc = body.get("allocation")
        shares = None
        if not _blank(alloc):
            raw = [_demo_positive(a, "Share of units") for a in alloc]
            shares = [s / sum(raw) for s in raw]
        mf = 0.2 if _blank(body.get("middle_fraction")) else _demo_prob(body.get("middle_fraction"),
                                                                         "Share at the middle stresses")
        lines += [
            *px.comment("The plan: the lowest stress to test at and the units at each, up to the highest stress."),
            f"plan = tp.accelerated_test_plan(DIST, LIFE_MODEL, LIFE_PARAMS, SHAPE, high_stress={px.num(hi)}, "
            f"n={n}, levels={k}, allocation={px.literal(shares)}, middle_fraction={px.num(mf)}, {common})",
        ]
    else:
        lines += [
            *px.comment("The precision of the test you propose: these stresses, these units at each."),
            f"plan = tp.accelerated_test_precision(DIST, LIFE_MODEL, LIFE_PARAMS, SHAPE, "
            f"stresses={px.literal([float(s) for s in result['stresses']])}, "
            f"units={px.literal([int(u) for u in result['units']])}, {common})",
        ]
    lines += [
        "",
        "for i, (s, u, f) in enumerate(zip(plan.stresses, plan.units, plan.expected_failures), start=1):",
        "    print_value(f'Stress {i}', s)",
        "    print_value(f'Units at stress {i}', u)",
        "    print_value(f'Expected failures at stress {i}', f)",
        "print_value('Expected failures in all', sum(plan.expected_failures))",
        f"print_value('Estimate (B{result['b_life']:g} at the use stress)', plan.estimate, UNIT)",
        "print_value('Precision factor', plan.precision)",
        "print_value('Interval from', plan.estimate / plan.precision, UNIT)",
        "print_value('Interval to', plan.estimate * plan.precision, UNIT)",
    ]
    for alt in result.get("alternatives") or []:
        lv = int(alt["levels"])
        lines += [
            f"# For comparison: the same test with {lv} stress levels.",
            f"other = tp.accelerated_test_plan(DIST, LIFE_MODEL, LIFE_PARAMS, SHAPE, high_stress={px.num(hi)}, "
            f"n={n}, levels={lv}, middle_fraction={px.num(mf)}, {common})",
            f"print_value('Precision factor with {lv} stress levels', other.precision)",
        ]
    return ["The precision is a large-sample approximation from the test's expected information."], lines


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def _comparison(body: dict, result: dict) -> tuple[list[str], list[str]]:
    conf = body.get("confidence", 0.90)
    alpha = tp_service._alpha(0.95 if _blank(conf) else conf)
    pw = float(result["power_target"])
    alt = result["alternative"]
    lines = [
        f"ALPHA = {px.num(alpha)}  # 1 - confidence",
        f"POWER = {px.num(pw)}  # the chance the test detects a real change of this size",
        f"ALTERNATIVE = {alt!r}",
        "",
    ]
    if result["kind"] == "logrank":
        lines += [
            *px.comment("Two groups (new and old design) followed together; the new design's failure rate is "
                        "HAZARD_RATIO times the old's."),
            f"HAZARD_RATIO = {px.num(result['hazard_ratio'])}",
            f"EVENT_PROBABILITY = {px.num(result['event_probability'])}  # chance a unit fails during the study",
            f"RATIO = {px.num(result['allocation_ratio'])}  # new units per old unit",
            "",
            "events = int(tp.logrank_events(HAZARD_RATIO, POWER, alpha_ci=ALPHA, ratio=RATIO, "
            "alternative=ALTERNATIVE))",
        ]
        if result["solve_for"] == "sample_size":
            lines += ["n_new, n_old = (int(v) for v in tp.logrank_sample_size(HAZARD_RATIO, EVENT_PROBABILITY, "
                      "POWER, alpha_ci=ALPHA, ratio=RATIO, alternative=ALTERNATIVE))"]
        else:
            lines += [f"n_old = {int(result['units_old'])}",
                      "n_new = max(2, int(round(RATIO * n_old)))"]
        lines += [
            "power = float(tp.logrank_power(HAZARD_RATIO, (n_new, n_old), EVENT_PROBABILITY, alpha_ci=ALPHA, "
            "alternative=ALTERNATIVE))",
            "",
            "print_value('Failures needed in all', events)",
            "print_value('New units', n_new)",
            "print_value('Old units', n_old)",
            "print_value('Power', power)",
        ]
        return ["A log-rank test of two groups, old and new, run side by side."], lines

    unit = _u(result)
    lines += [
        *px.comment("One fleet's failure rate before and after a change."),
        f"FAILURES_BEFORE = {int(result['failures_before'])}",
        f"EXPOSURE_BEFORE = {px.num(result['exposure_before'])}  # operating time before the change",
        "RATE_BEFORE = FAILURES_BEFORE / EXPOSURE_BEFORE",
        f"UNIT = {unit}",
        "",
        "print_value('Failure rate before', RATE_BEFORE)",
    ]
    kw = "alpha_ci=ALPHA, alternative=ALTERNATIVE"
    solve = result["solve_for"]
    if solve == "exposure":
        lines += [
            f"RATE_RATIO = {px.num(result['rate_ratio'])}  # the rate after over before (0.5 halves it)",
            "# The operating time after the change needed to detect it.",
            f"need = float(tp.rate_ratio_exposure(RATE_RATIO, RATE_BEFORE, EXPOSURE_BEFORE, POWER, {kw}))",
            "print_value('Operating time needed after the change', need if np.isfinite(need) else None, UNIT)",
        ]
    elif solve == "detectable":
        lines += [
            f"EXPOSURE_AFTER = {px.num(result['exposure_after'])}",
            "# The smallest change (rate after over before) this much running can detect.",
            f"r = float(tp.rate_ratio_detectable(RATE_BEFORE, EXPOSURE_BEFORE, EXPOSURE_AFTER, POWER, {kw}))",
            "print_value('Smallest detectable rate ratio', r if np.isfinite(r) else None)",
        ]
    else:
        lines += [
            f"RATE_RATIO = {px.num(result['rate_ratio'])}  # the rate after over before (0.5 halves it)",
            f"EXPOSURE_AFTER = {px.num(result['exposure_after'])}",
            f"power = float(tp.rate_ratio_power(RATE_RATIO, RATE_BEFORE, EXPOSURE_BEFORE, EXPOSURE_AFTER, {kw}))",
            "print_value('Power', power)",
        ]
    return ["The exact conditional test of two Poisson rates (steady failure rates before and after)."], lines


_BUILDERS: dict[str, Any] = {
    "demonstration": _demonstration,
    "sequential": _sequential,
    "life": _life,
    "accelerated": _accelerated,
    "comparison": _comparison,
}
