"""A regression on one grouping column also answers "are the groups really
different?": the log-rank test on the data with each group's median, and
every coefficient's standard error and Wald p-value."""

import math

import pandas as pd
import pytest

from backend import fitting

# Two designs, 20 cycles to failure each, every unit failed.
A = [485, 810, 555, 490, 1233, 357, 1207, 340, 168, 934, 503, 663, 860, 1016, 748, 725, 1004, 703, 504, 328]
B = [577, 406, 1664, 918, 747, 967, 1037, 258, 888, 1433, 888, 1646, 329, 633, 1366, 623, 720, 1558, 1259, 842]


def _df():
    return pd.DataFrame({"design": ["A"] * 20 + ["B"] * 20, "cycles": A + B})


def test_log_rank_and_medians_match_the_hand_calculation():
    # By hand: the log-rank chi-square is 5.59 on 1 degree of freedom,
    # p = 0.018; each group's Kaplan-Meier median is its 10th failure
    # (663 and 888 cycles).
    out = fitting.fit("weibull_ph", _df(), {"x": "cycles"}, covariates=["design"], unit="cycles")
    g = out["group_test"]
    assert g["test"] == "Log-rank"
    assert g["statistic"] == pytest.approx(5.59, abs=0.005)
    assert g["dof"] == 1
    assert g["p_value"] == pytest.approx(0.018, abs=0.0005)
    assert g["significant"] is True
    assert [(r["group"], r["median"]) for r in g["groups"]] == [("A", 663.0), ("B", 888.0)]
    assert g["text"].startswith("Design B lasts longer than design A, and the difference is unlikely to be chance")
    assert "p = 0.018" in g["text"]
    assert "design A 663 cycles, design B 888 cycles" in g["text"]


def test_cox_gets_the_same_test():
    out = fitting.fit("cox_ph", _df(), {"x": "cycles"}, covariates=["design"], unit="cycles")
    assert out["group_test"]["p_value"] == pytest.approx(0.018, abs=0.0005)


def test_coefficients_carry_standard_error_and_wald_p():
    out = fitting.fit("weibull_ph", _df(), {"x": "cycles"}, covariates=["design"], unit="cycles")
    coef = out["coefficients"][0]
    assert coef["name"] == "design[T.B]"
    assert coef["se"] > 0
    # The 90% interval is the estimate ± 1.645 standard errors.
    assert coef["ci"][1] - coef["ci"][0] == pytest.approx(2 * 1.6449 * coef["se"], rel=1e-3)
    assert coef["p"] == pytest.approx(math.erfc(abs(coef["value"] / coef["se"]) / math.sqrt(2)))
    assert all(p["se"] is not None and p["se"] > 0 for p in out["params"])


def test_no_group_test_for_a_measurement_or_several_covariates():
    df = _df().assign(load=[float(i % 7) for i in range(40)])
    one_number = fitting.fit("weibull_ph", df, {"x": "cycles"}, covariates=["load"])
    assert "group_test" not in one_number
    two = fitting.fit("weibull_ph", df, {"x": "cycles"}, covariates=["design", "load"])
    assert "group_test" not in two


def test_a_flag_column_counts_as_groups_and_running_units_are_kept():
    df = _df().assign(new=[0] * 20 + [1] * 20, running=[0] * 18 + [1, 1] + [0] * 20)
    out = fitting.fit("weibull_ph", df, {"x": "cycles", "c": "running"}, covariates=["new"])
    g = out["group_test"]
    assert [r["failures"] for r in g["groups"]] == [18, 20]
    assert g["column"] == "new"
