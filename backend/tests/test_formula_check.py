"""Regression formulas: the useful grammar is accepted, anything else is not."""

import pandas as pd
import pytest

from backend.fitting import FitError, fit
from backend.formula_check import FormulaRejected, check_formula

COLS = ["age", "sex", "temp", "my col", "load"]


@pytest.mark.parametrize(
    "formula",
    [
        "age + sex",
        "age + C(sex)",
        "age*C(sex)",
        "age:temp",
        "(age + temp)**2",
        "age - 1",
        "age + 0",
        "log(load) + center(age) + scale(temp)",
        "I(age**2) + age",
        "poly(age, 2)",
        "age + `my col`",
        "  age + sex  ",
    ],
)
def test_accepts_ordinary_formulas(formula):
    assert check_formula(formula, COLS) == formula.strip()


@pytest.mark.parametrize(
    "formula",
    [
        "age + I(__import__('os').getpid())",
        "age + I(open('/etc/passwd'))",
        "np.log(age)",
        "age + eval(sex)",
        "age + sex.__class__",
        "age + age[0]",
        "age + {}",
        "age + `missing`",
        "age + nothere",
        "age + 'text'",
        "age + I(age**1000)",
        "C(sex",
        "age)",
        "age; import os",
        "",
        "a" * 400,
    ],
)
def test_rejects_anything_else(formula):
    with pytest.raises(FormulaRejected):
        check_formula(formula, COLS)


def test_column_named_like_code_cannot_be_called():
    # A CSV header is user-controlled, so a column may be named after a builtin.
    cols = COLS + ["__import__", "eval"]
    assert check_formula("age + __import__", cols)
    with pytest.raises(FormulaRejected):
        check_formula("age + __import__(sex)", cols)


def test_fit_reports_rejected_formula_as_fit_error():
    df = pd.DataFrame(
        {"time": [5.0, 8.0, 12.0, 15.0, 20.0, 25.0], "censored": [0, 0, 1, 0, 0, 1],
         "age": [30, 40, 50, 35, 45, 55], "sex": ["m", "f", "m", "f", "m", "f"]}
    )
    for formula in ("age + I(__import__('os').getpid()*0)", "age + __import__(sex)"):
        with pytest.raises(FitError, match="unsupported character|isn't supported"):
            fit("weibull_ph", df, {"x": "time", "c": "censored"}, formula=formula)
