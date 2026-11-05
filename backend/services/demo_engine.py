"""The demonstration-test engine: SurPyval's ``test_planning``, called the way
the calculator has always called it.

The demonstration-test calculator (:func:`backend.services.strategy.demonstration_test`)
was written against RePyability's ``demonstration`` module, which takes the
confidence level positionally (``confidence=0.95``). SurPyval 0.25 moved the
same functions into ``surpyval.test_planning`` with SurPyval's convention, the
significance level ``alpha_ci`` (``0.05`` for 95%) as a keyword. These
wrappers keep the old signatures, so the calculator's code (and
:mod:`backend.services.demo_shape`, which is handed this module) didn't have
to change, and ``backend/tests/test_test_planning_demo.py`` can run the
calculator on either engine and check the answers are the same.
"""
from __future__ import annotations

from typing import Optional

from surpyval import test_planning as _tp


def _alpha(confidence: float) -> float:
    return 1.0 - float(confidence)


def demonstration_sample_size(reliability, confidence=0.95, failures=0, *, test_multiple=1.0,
                              shape: Optional[float] = None):
    return _tp.demonstration_sample_size(reliability, failures, alpha_ci=_alpha(confidence),
                                         test_multiple=test_multiple, shape=shape)


def demonstrated_reliability(n, confidence=0.95, failures=0, *, test_multiple=1.0,
                             shape: Optional[float] = None):
    return _tp.demonstrated_reliability(n, failures, alpha_ci=_alpha(confidence),
                                        test_multiple=test_multiple, shape=shape)


def demonstration_test_multiple(reliability, n, confidence=0.95, failures=0, *, shape: float):
    return _tp.demonstration_test_multiple(reliability, n, failures, shape=shape, alpha_ci=_alpha(confidence))


def demonstration_pass_probability(reliability, n, failures=0, *, test_multiple=1.0,
                                   shape: Optional[float] = None):
    return _tp.demonstration_pass_probability(reliability, n, failures, test_multiple=test_multiple,
                                              shape=shape)


def mtbf_test_time(mtbf, confidence=0.95, failures=0, *, failure_terminated=False):
    return _tp.mtbf_test_time(mtbf, failures, alpha_ci=_alpha(confidence),
                              failure_terminated=failure_terminated)


def demonstrated_mtbf(test_time, confidence=0.95, failures=0, *, failure_terminated=False):
    return _tp.demonstrated_mtbf(test_time, failures, alpha_ci=_alpha(confidence),
                                 failure_terminated=failure_terminated)


def mtbf_pass_probability(mtbf, test_time, failures=0, *, failure_terminated=False):
    return _tp.mtbf_pass_probability(mtbf, test_time, failures, failure_terminated=failure_terminated)


def demonstration_plan(reliability, good_reliability, confidence=0.95, producer_risk=0.2, *, n=None,
                       test_multiple=1.0, shape: Optional[float] = None, max_failures=1000):
    return _tp.demonstration_plan(reliability, good_reliability, alpha_ci=_alpha(confidence),
                                  producer_risk=producer_risk, n=n, test_multiple=test_multiple, shape=shape,
                                  max_failures=max_failures)


def mtbf_demonstration_plan(mtbf, good_mtbf, confidence=0.95, producer_risk=0.2, *, max_failures=1000):
    return _tp.mtbf_demonstration_plan(mtbf, good_mtbf, alpha_ci=_alpha(confidence),
                                       producer_risk=producer_risk, max_failures=max_failures)
