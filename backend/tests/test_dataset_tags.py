"""Dataset tags (planning #261): what a dataset holds, detected from its columns."""

import pandas as pd

from backend.services.datasets import detect_tags


def tags(rows, cols):
    return detect_tags(pd.DataFrame(rows, columns=cols))


def test_life_data_with_and_without_covariates():
    plain = tags([[f"P-{i}", 100 + i, i % 2] for i in range(10)], ["pump", "hours", "censored"])
    assert plain["tags"] == ["Non-repairable"]
    assert plain["use_for"][0] == "Non-repairable model"
    cov = tags([[f"P-{i}", 100 + i, i % 2, 60 + i % 3, "North"] for i in range(10)],
               ["pump", "hours", "censored", "load_pct", "site"])
    assert cov["tags"] == ["Non-repairable", "Covariates"]
    assert cov["use_for"][0] == "Non-repairable model with covariates"


def test_interval_data_has_two_time_columns_and_no_covariates():
    # A saved Bayesian update's dataset (shortest / longest / censored), and SurPyval's xl / xr:
    # the second column is the interval's end, not a covariate.
    out = tags([[3.4387, 3.4387, 1], [1.2, 1.8, 2]], ["shortest", "longest", "censored"])
    assert out["tags"] == ["Non-repairable"]
    assert out["use_for"][0] == "Non-repairable model"
    out = tags([[100, 120, 2], [150, 150, 1], [90, 110, 2]], ["xl", "xr", "c"])
    assert out["tags"] == ["Non-repairable"]


def test_recurrent_events():
    rows = [[f"HT-{u}", 1000 * k + 37 * u, 0 if k < 3 else 1, 180 + 40 * (u % 2)] for u in range(4) for k in range(1, 4)]
    out = tags(rows, ["truck", "engine_hours", "censored", "payload_t"])
    assert out["tags"] == ["Repairable", "Covariates"]
    assert out["use_for"] == ["Repairable model with covariates"]


def test_readings_are_measurements():
    rows = [[f"B-{u}", 1000 * k, 2.0 + 0.1 * k + u] for u in range(4) for k in range(4)]
    out = tags(rows, ["bearing", "hours", "vibration_mm_s"])
    assert out["tags"] == ["Measurements"]  # no failure times: not life data
    assert out["use_for"] == ["Degradation model", "Condition and life model (once life data is added)"]


def test_start_stop_rows_with_changing_load():
    rows = [[f"TX-{u}", 2000 * k, 2000 * (k + 1), 1 if k < 2 else 0, [55, 70, 85][(u + k) % 3]]
            for u in range(4) for k in range(3)]
    out = tags(rows, ["transformer", "start_hours", "stop_hours", "censored", "load_pct"])
    assert out["tags"] == ["Non-repairable", "Time-varying covariates"]
    assert out["use_for"] == ["Non-repairable model with time-varying covariates"]


def test_repairable_without_a_status_column():
    """Events with a cause and an observed-to time per unit (the slurry pumps sample)."""
    rows = [[f"P-{u}", 1000 * k + u, "Coastal" if u % 2 else "Inland", 60 + 10 * u, ["seal", "bearing"][k % 2], 8760]
            for u in range(4) for k in range(1, 4)]
    out = tags(rows, ["pump", "hours", "site", "duty_pct", "cause", "observed_to"])
    assert out["tags"] == ["Repairable", "Covariates"]


def test_summary_counts_units_by_their_own_name():
    life = tags([[f"P-{i}", 100 + i, i % 2] for i in range(10)], ["pump", "hours", "censored"])
    assert life["summary"] == "10 pumps · 5 failed"
    rows = [[f"HT-{u}", 1000 * k + 37 * u, 0 if k < 3 else 1] for u in range(4) for k in range(1, 4)]
    assert tags(rows, ["truck", "engine_hours", "censored"])["summary"] == "4 trucks · 8 failures"
    rows = [[f"B-{u}", 1000 * k, 2.0 + 0.1 * k + u] for u in range(4) for k in range(4)]
    assert tags(rows, ["bearing", "hours", "vibration_mm_s"])["summary"] == "4 bearings · 16 readings"
    assert tags([[1.0], [2.0], [3.5]], ["x"])["summary"] == "3 units · all failed"


def test_time_unit_from_the_time_column():
    rows = [[f"HT-{u}", 1000 * k + 37 * u, 0] for u in range(3) for k in range(1, 3)]
    assert tags(rows, ["truck", "engine_hours", "censored"])["time_unit"] == "hour"
    assert tags([[1.0, 0], [2.0, 1]], ["x", "c"])["time_unit"] is None


def test_time_unit_reads_the_column_words_with_pint():
    """SurPyval 0.27 keeps a unit label as typed, so the app compares each
    word with its units (``same_unit``) rather than reading a normalised name."""
    from backend.services.datasets import _time_unit

    assert _time_unit(["odometer_km"]) == "kilometer"
    assert _time_unit(["cycles"]) == "cycle"
    assert _time_unit(["age (years)"]) == "year"
    assert _time_unit(["Days"]) == "day"
    assert _time_unit(["time_to_failure"]) is None


def test_outcome_once_per_unit_with_readings_is_life_data_with_measurements():
    rows = [[f"B-{u}", 1000 * k, 2.0 + 0.1 * k + u, None if k < 3 else u % 2] for u in range(4) for k in range(4)]
    out = tags(rows, ["bearing", "hours", "vibration_mm_s", "censored"])
    assert out["tags"] == ["Non-repairable", "Measurements"]
    assert "Non-repairable model" in out["use_for"]
    # Status on every row means the readings are changing covariates instead.
    every = [[f"B-{u}", 1000 * k, 2.0 + 0.1 * k + u, 1 if k < 3 else 0] for u in range(4) for k in range(4)]
    assert "Time-varying covariates" in tags(every, ["bearing", "hours", "vibration_mm_s", "censored"])["tags"]


def test_summary_counts_failures_when_the_flag_means_1_failed():
    """A "failed" column (1 = failed) is counted the way the fit wizard reads
    it (it inverts such columns by name), not as Reliafy's 0 = failed."""
    rows = [[f"M-{i}", 100 + 10 * i, 1 if i < 14 else 0] for i in range(20)]
    assert (
        tags(rows, ["unit", "flight_hours", "failed"])["summary"]
        == "20 units · 14 failed"
    )
    for name in ("Failure", "event", "status", "is_failed", "dead", "failed_flag"):
        assert (
            tags(rows, ["unit", "flight_hours", name])["summary"]
            == "20 units · 14 failed"
        ), name
    # Columns named the Reliafy way round stay 0 = failed.
    for name in ("censored", "c", "suspended"):
        assert (
            tags(rows, ["unit", "flight_hours", name])["summary"]
            == "20 units · 6 failed"
        ), name
    # Left- and interval-censored flags are kept as they are: those units were
    # found failed, with the time known only as a range.
    rows = [["M-0", 10, 1], ["M-1", 20, 0], ["M-2", 30, -1], ["M-3", 40, 2]]
    assert tags(rows, ["unit", "hours", "failed"])["summary"] == "4 units · 1 failed · 2 failed between inspections"


def test_summary_reads_a_status_column_of_words():
    """"F" / "S" (or Failed / Running) says which units failed: it is counted,
    and it isn't a covariate."""
    rows = [[f"P{i:02d}", 1000 + 100 * i, "F" if i < 8 else "S"] for i in range(20)]
    out = tags(rows, ["unit", "hours", "status"])
    assert out["summary"] == "20 units · 8 failed"
    assert out["tags"] == ["Non-repairable"]
    rows = [[f"P{i:02d}", 1000 + 100 * i, "Running" if i % 4 else "Failed"] for i in range(20)]
    assert tags(rows, ["pump", "hours", "Status"])["summary"] == "20 pumps · 5 failed"
    # "running: yes" is a unit still running; "failed: yes" is a failure.
    rows = [[100 + i, "yes" if i < 3 else "no"] for i in range(10)]
    assert tags(rows, ["hours", "running"])["summary"] == "10 units · 7 failed"
    assert tags(rows, ["hours", "failed"])["summary"] == "10 units · 3 failed"


def test_summary_counts_inspection_data_with_survivors():
    windows = [(0, 200)] * 2 + [(200, 400)] * 8 + [(400, 600)] * 15
    cols = ["valve", "last_ok_hours", "found_failed_hours"]
    blank = [[f"V{i}", lo, hi] for i, (lo, hi) in enumerate(windows)] + [[f"S{i}", 1000, None] for i in range(15)]
    assert tags(blank, cols)["summary"] == "40 valves · 25 failed between inspections"
    coded = ([[f"V{i}", lo, hi, 2] for i, (lo, hi) in enumerate(windows)]
             + [[f"S{i}", 1000, 1000, 1] for i in range(15)])
    assert tags(coded, cols + ["censor_code"])["summary"] == "40 valves · 25 failed between inspections"
    words = ([[f"V{i}", lo, hi, "F"] for i, (lo, hi) in enumerate(windows)]
             + [[f"S{i}", 1000, 1000, "S"] for i in range(15)])
    assert tags(words, cols + ["status"])["summary"] == "40 valves · 25 failed between inspections"


def test_summary_weighs_rows_by_a_count_column():
    rows = [[m, "F", 5 + m] for m in range(1, 7)] + [[m, "S", 400 + m] for m in range(1, 7)]
    assert tags(rows, ["age_months", "status", "count"])["summary"] == "2,472 units · 51 failed"


def test_summary_reads_a_blank_failure_mode_as_still_running():
    rows = [[f"P-{i}", 100 + 10 * i, ["seal leak", "bearing wear", None][i % 3], "A" if i % 2 else "B"]
            for i in range(30)]
    assert tags(rows, ["pump", "hours", "failure_mode", "site"])["summary"] == "30 pumps · 20 failed"


def test_summary_does_not_say_all_failed_when_it_cannot_tell():
    # A status column it can't read: the units alone, not a guess.
    rows = [[100 + i, ["amber", "green", "review"][i % 3]] for i in range(12)]
    assert tags(rows, ["hours", "status"])["summary"] == "12 units"
    # Times with a group column and nothing that could be a status: every row failed.
    rows = [["A" if i % 2 else "B", 400 + 10 * i] for i in range(12)]
    assert tags(rows, ["design", "cycles"])["summary"] == "12 units · all failed"


def test_covariates_tag_follows_the_reading():
    """A split of a plant sheet: an id marked not used and a failure mode read
    as ``e`` are not covariates, so the saved reading (z empty) drops the tag
    the columns alone suggest; a reading that includes a covariate keeps it."""
    from backend.schema import Dataset
    from backend.services.datasets import dataset_tags

    rows = [[f"R{i:03d}", f"U1-BFP-{i:02d}", "Failed" if i % 3 else "Right-censored", 4000 + 517 * i,
             ["Seal leak", "Bearing wear"][i % 2] if i % 3 else ""] for i in range(14)]
    cols = ["ID", "Equipment Tag", "Status", "Age (h)", "Failure Mode"]
    csv = pd.DataFrame(rows, columns=cols).to_csv(index=False).encode()
    reading = {"x": "Age (h)", "c": "Status", "i": "Equipment Tag", "e": "Failure Mode", "z": [], "not_used": ["ID"]}
    ds = Dataset(id="split-1", name="Boiler feed pump", checksum="tags-reading-test", data=csv, reading=reading)
    out = dataset_tags(ds)
    assert out["tags"] == ["Non-repairable"]
    assert out["use_for"][0] == "Non-repairable model"

    with_z = ds.model_copy(update={"reading": {**reading, "z": ["Failure Mode"], "e": ""}})
    out = dataset_tags(with_z)
    assert out["tags"] == ["Non-repairable", "Covariates"]
    assert out["use_for"][0] == "Non-repairable model with covariates"
