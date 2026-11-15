"""Warnings are collected and quietened per execution context
(``backend/warn_capture.py``): work running at the same time in another
thread neither adds to this work's warnings nor hides them."""
from __future__ import annotations

import contextvars
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor

import anyio
import numpy as np
import pytest
from starlette.concurrency import run_in_threadpool

from backend.fitting import reissue_deprecations
from backend.services import strategy_calendar as sc
from backend.warn_capture import collect_warnings, ignore_warnings

TIMEOUT = 10


def _both(first, second):
    """Run two callables in two threads at once; re-raise either's error."""
    errors = []

    def run(fn):
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(fn,)) for fn in (first, second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(TIMEOUT)
    if errors:
        raise errors[0]


@pytest.mark.parametrize("other_collects", [True, False])
def test_another_threads_warning_is_not_collected_here(other_collects):
    inside, warned = threading.Event(), threading.Event()
    mine, theirs = [], []

    def quiet_work():
        with collect_warnings() as caught:
            inside.set()
            assert warned.wait(TIMEOUT)
        mine.extend(caught)

    def noisy_work():
        assert inside.wait(TIMEOUT)
        if other_collects:
            with collect_warnings() as caught:
                warnings.warn("someone else's fit", UserWarning)
            theirs.extend(caught)
        else:
            with warnings.catch_warnings():  # keep the uncollected one off the test's output
                warnings.simplefilter("ignore")
                warnings.warn("someone else's fit", UserWarning)
        warned.set()

    _both(quiet_work, noisy_work)
    assert mine == []
    if other_collects:
        assert [str(w.message) for w in theirs] == ["someone else's fit"]


def test_collected_every_time_with_the_fields_the_call_sites_read():
    for _ in range(3):
        with collect_warnings() as caught:
            warnings.warn("again", UserWarning)
            np.log(np.array([-1.0]))
        assert [w.category for w in caught] == [UserWarning, RuntimeWarning]
        w = caught[0]
        assert str(w.message) == "again" and w.filename == __file__ and w.lineno > 0


def test_ignoring_here_does_not_hide_another_threads_warnings():
    inside, warned = threading.Event(), threading.Event()
    theirs = []

    def ignoring_work():
        with ignore_warnings():
            inside.set()
            assert warned.wait(TIMEOUT)

    def collecting_work():
        assert inside.wait(TIMEOUT)
        with collect_warnings() as caught:
            warnings.warn("still seen", UserWarning)
        theirs.extend(caught)
        warned.set()

    _both(ignoring_work, collecting_work)
    assert [str(w.message) for w in theirs] == ["still seen"]


def test_ignore_inside_a_collection_drops_only_what_it_names():
    with collect_warnings() as caught:
        with ignore_warnings(RuntimeWarning):
            np.log(np.array([-1.0]))
            warnings.warn("kept", UserWarning)
        with ignore_warnings(UserWarning, message="common-cause group"):
            warnings.warn("Common-cause group [a, b] is past its range", UserWarning)
            warnings.warn("another note", UserWarning)
    assert [str(w.message) for w in caught] == ["kept", "another note"]


def test_a_collection_for_one_category_still_gets_the_rest_unless_filtered():
    with collect_warnings(RuntimeWarning) as caught:
        np.log(np.array([-1.0]))
        with ignore_warnings(UserWarning):
            warnings.warn("dropped", UserWarning)
    assert [w.category for w in caught] == [RuntimeWarning]


def test_outside_any_block_the_global_filters_still_apply():
    with warnings.catch_warnings(record=True) as shown:
        warnings.simplefilter("default")
        with collect_warnings():
            pass  # installs the hook
        for _ in range(2):
            warnings.warn("once per place", UserWarning)
        warnings.filterwarnings("ignore", message="hidden")
        warnings.warn("hidden", UserWarning)
        warnings.filterwarnings("error", message="fatal")
        with pytest.raises(UserWarning):
            warnings.warn("fatal", UserWarning)
    assert [str(w.message) for w in shown] == ["once per place"]


def test_a_library_recording_inside_the_block_keeps_its_warnings():
    with collect_warnings() as caught:
        with warnings.catch_warnings(record=True) as library:
            warnings.simplefilter("always")
            warnings.warn("the library's own", UserWarning)
        warnings.warn("ours", UserWarning)
    assert [str(w.message) for w in library] == ["the library's own"]
    assert [str(w.message) for w in caught] == ["ours"]


def test_deprecations_are_collected_and_reissued_to_the_filters():
    with warnings.catch_warnings():
        warnings.filterwarnings("error", category=DeprecationWarning)
        with collect_warnings() as caught:
            warnings.warn("old name", DeprecationWarning)  # collected, not raised
        assert [w.category for w in caught] == [DeprecationWarning]
        with pytest.raises(DeprecationWarning):
            reissue_deprecations(caught)


def test_the_context_follows_work_into_worker_threads():
    def warn():
        warnings.warn("from the worker", UserWarning)

    async def via_threadpool():
        with collect_warnings() as caught:
            await run_in_threadpool(warn)
            await anyio.to_thread.run_sync(warn)
        return caught

    caught = anyio.run(via_threadpool)
    assert [str(w.message) for w in caught] == ["from the worker"] * 2

    with collect_warnings() as caught, ThreadPoolExecutor(1) as pool:
        pool.submit(contextvars.copy_context().run, warn).result(TIMEOUT)
    assert [str(w.message) for w in caught] == ["from the worker"]


def test_a_calendar_replacement_keeps_only_its_own_notes():
    """The calendar's notes once ended with a warning from another request."""
    inside, warned = threading.Event(), threading.Event()

    class Part:
        def optimal_calendar_policy(self, cal, **kwargs):
            warnings.warn("its own note", UserWarning)
            inside.set()
            assert warned.wait(TIMEOUT)
            return "policy"

    out = {}

    def calendar_work():
        out["result"] = sc._solve(Part(), None, method="grid", max_age=None, mc_samples=0, seed=0)

    def other_request():
        assert inside.wait(TIMEOUT)
        with collect_warnings():
            warnings.warn("someone else's degradation fit", UserWarning)
        warned.set()

    _both(calendar_work, other_request)
    policy, notes = out["result"]
    assert policy == "policy"
    assert notes == ["its own note"]


def test_a_library_hook_wrapped_around_ours_does_not_lose_warnings():
    """SurPyval 0.27 wraps ``warnings._showwarnmsg`` the first time one of its
    collecting blocks runs, around whatever hook is there (ours); our next
    block wraps it again. The chain loops back to our hook, which used to drop
    every warning shown outside a block from then on."""
    from surpyval.utils import warnings as sv_warnings

    with collect_warnings():
        pass
    with sv_warnings.collecting_warnings():
        pass
    with collect_warnings():
        pass
    with warnings.catch_warnings(record=True) as shown:
        warnings.simplefilter("default")
        for _ in range(2):
            warnings.warn("still shown, once", UserWarning)
    assert [str(w.message) for w in shown] == ["still shown, once"]
    with sv_warnings.collecting_warnings() as theirs:
        warnings.warn("surpyval's", UserWarning)
    assert [str(w.message) for w in theirs] == ["surpyval's"]
    with collect_warnings() as ours:
        warnings.warn("ours", UserWarning)
    assert [str(w.message) for w in ours] == ["ours"]
