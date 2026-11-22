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
    assert tags(rows, ["unit", "hours", "failed"])["summary"] == "4 units · 1 failed · 1 failed between inspections · 1 found failed at the first inspection"


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
    assert tags(blank, cols)["summary"] == "40 valves · 23 failed between inspections · 2 found failed at the first inspection"
    coded = ([[f"V{i}", lo, hi, 2] for i, (lo, hi) in enumerate(windows)]
             + [[f"S{i}", 1000, 1000, 1] for i in range(15)])
    assert tags(coded, cols + ["censor_code"])["summary"] == "40 valves · 23 failed between inspections · 2 found failed at the first inspection"
    words = ([[f"V{i}", lo, hi, "F"] for i, (lo, hi) in enumerate(windows)]
             + [[f"S{i}", 1000, 1000, "S"] for i in range(15)])
    assert tags(words, cols + ["status"])["summary"] == "40 valves · 23 failed between inspections · 2 found failed at the first inspection"


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


# --- The saved reading decides how rows are counted (demo review, Nov 2026) ---

def _saved(rows, cols, reading, key):
    from backend.schema import Dataset
    from backend.services.datasets import dataset_tags

    csv = pd.DataFrame(rows, columns=cols).to_csv(index=False).encode()
    return dataset_tags(Dataset(id=key, name=key, checksum=key, data=csv, reading=reading))


_INSPECTION_COLS = ["av", "fitted_at_airframe_fh", "age_last_clean_fh", "age_found_fh", "status", "event"]
_INSPECTION_READING = {"xl": "age_last_clean_fh", "xr": "age_found_fh", "c": "status", "i": "av",
                       "unit": "flight hours", "not_used": ["fitted_at_airframe_fh", "event"]}


def test_no_findings_count_as_none_failed():
    """A column named "status" reads 1 = failed by its name alone, but the
    saved reading says 0 = failed (no c_invert): ten units still in service are
    no failures, as the fit reads them."""
    rows = [[f"AV-{i:02d}", 20.0 * i, 270.0 + i, 270.0 + i, 1, "still in service"] for i in range(1, 11)]
    out = _saved(rows, _INSPECTION_COLS, _INSPECTION_READING, "reading-no-findings")
    assert out["summary"] == "10 avs · 0 failed"
    assert out["tags"] == ["Non-repairable"]


def test_c_invert_and_c_map_are_read():
    rows = [[f"P-{i}", 100 + i, 1 if i < 3 else 0] for i in range(10)]
    cols = ["pump", "hours", "flag"]
    out = _saved(rows, cols, {"x": "hours", "c": "flag", "c_invert": True}, "reading-invert")
    assert out["summary"] == "10 pumps · 3 failed"
    out = _saved(rows, cols, {"x": "hours", "c": "flag"}, "reading-plain")
    assert out["summary"] == "10 pumps · 7 failed"
    words = [[f"P-{i}", 100 + i, "Broke" if i < 4 else "OK"] for i in range(10)]
    out = _saved(words, cols, {"x": "hours", "c": "flag", "c_map": {"Broke": 0, "OK": 1}}, "reading-map")
    assert out["summary"] == "10 pumps · 4 failed"


def test_inspection_lives_are_not_repairable():
    """Several inspection lives per air vehicle (a range each, 2 = found
    between inspections) are non-repairable lives, not a repairable system's
    events, whatever the airframe hours column does."""
    rows = [["AV-01", 193.8, 231.2, 256.2, 2, "found"], ["AV-01", 450, 114.9, 114.9, 1, "in service"],
            ["AV-02", 186.7, 138.3, 163.3, 2, "found"], ["AV-02", 350, 176.7, 176.7, 1, "in service"],
            ["AV-03", 157.9, 92.1, 117.1, 2, "found"], ["AV-03", 275, 125, 150, 2, "found"],
            ["AV-03", 425, 78.2, 78.2, 1, "in service"]]
    out = _saved(rows, _INSPECTION_COLS, _INSPECTION_READING, "reading-inspection-lives")
    assert out["tags"] == ["Non-repairable"]
    assert out["summary"] == "3 avs · 7 lives · 4 failed between inspections"


def test_part_lives_per_vehicle_are_not_repairable():
    """Propeller removals: hours on each propeller (resetting at each fit) with
    the airframe hours beside them. The reading's x doesn't rise along a
    vehicle's rows, so these are part lives, not repairable events."""
    rows = [["AV-01", 0, 45.9, 0], ["AV-01", 45.9, 16, 0], ["AV-01", 61.9, 64.1, 0], ["AV-01", 126, 429.1, 1],
            ["AV-02", 0, 191.5, 0], ["AV-02", 191.5, 60.2, 0], ["AV-02", 251.7, 135.9, 1]]
    cols = ["av", "fitted_at_airframe_fh", "fh_on_part", "status"]
    out = _saved(rows, cols, {"x": "fh_on_part", "c": "status", "i": "av", "not_used": ["fitted_at_airframe_fh"]},
                 "reading-part-lives")
    assert out["tags"] == ["Non-repairable"]
    assert out["summary"] == "2 avs · 7 lives · 5 failed"


def test_an_events_table_with_no_readings_is_not_measurements():
    """An events table read as component ages, every row a failure, with
    repair hours not used: no measured value (m), so not Measurements."""
    rows = [["AV-01", 45.9, 45.9, 0.5], ["AV-01", 61.9, 16, 1.8], ["AV-02", 76, 76, 4],
            ["AV-02", 120, 44, 3], ["AV-03", 26.4, 26.4, 0.7]]
    cols = ["asset", "airframe_fh", "component_age_fh", "repair_h"]
    reading = {"x": "component_age_fh", "i": "asset", "all_failed": True, "not_used": ["airframe_fh", "repair_h"]}
    out = _saved(rows, cols, reading, "reading-events")
    assert "Measurements" not in out["tags"]
    assert out["tags"] == ["Non-repairable"]
    assert out["summary"] == "3 assets · 5 lives · 5 failed"


def test_recurrent_events_still_repairable_with_a_reading():
    rows = [[f"T{u}", 100 * k + u, 0 if k < 3 else 1] for u in range(3) for k in range(1, 5)]
    out = _saved(rows, ["truck", "engine_hours", "censored"], {"x": "engine_hours", "c": "censored", "i": "truck"},
                 "reading-recurrent")
    assert out["tags"] == ["Repairable"]
    assert out["summary"] == "3 trucks · 6 failures"


def test_one_numbered_system_history_is_repairable():
    """A fleet history in cumulative hours (system 1, every row a defect, up
    to an observed-to time) is a repairable system's events."""
    rows = [[1, t, 4429.2, "Belt"] for t in (278.2, 365.5, 422.5, 427.9, 900.0)]
    reading = {"x": "time", "tr": "observed_to", "i": "system", "e": "cause", "all_failed": True}
    out = _saved(rows, ["system", "time", "observed_to", "cause"], reading, "reading-one-system")
    assert out["tags"] == ["Repairable"]
    assert out["summary"] == "1 system · 5 failures"


def test_summary_and_fit_step_count_first_inspection_failures_alike():
    # A window that opens at zero was found failed at the first look: the
    # dataset's summary words it as the fit step does (REL-02 counted 25 here, 23 + 2 there).
    from backend import fitting
    windows = [(0, 200)] * 2 + [(200, 400)] * 8 + [(400, 600)] * 15
    rows = [[f"V{i}", lo, hi] for i, (lo, hi) in enumerate(windows)] + [[f"S{i}", 1000, None] for i in range(15)]
    cols = ["valve", "last_ok_hours", "found_failed_hours"]
    assert tags(rows, cols)["summary"].endswith("23 failed between inspections · 2 found failed at the first inspection")
    import pandas as pd
    df = pd.DataFrame(rows, columns=cols)
    fit = fitting.data_reading(df, {"xl": "last_ok_hours", "xr": "found_failed_hours"})
    assert (fit["interval"], fit["left"], fit["running"]) == (23, 2, 15)


def test_a_failure_mode_columns_blanks_count_as_running_on_the_card_as_in_the_fit():
    """A dataset read with a failure-mode column and no status column: a
    blank mode is a unit still running. The Data card's count follows the
    fit by failure mode (and the fit step's "50 failed, 22 running"), never
    "every row failed"."""
    import io

    import numpy as np

    from backend import competing_risks
    from backend.services import samples
    from backend.services.datasets import count_reading_of

    csv = samples._PUMP_MODES_CSV
    df = pd.read_csv(io.StringIO(csv.decode() if isinstance(csv, bytes) else csv))
    mapping = {"x": "hours", "e": "failure_mode", "g": "site"}
    prep = competing_risks.prepare(df, mapping)
    failed, running = int(np.sum(prep["c"] == 0)), int(np.sum(prep["c"] == 1))
    assert (failed, running) == (50, 22)
    blanks = int(df["failure_mode"].isna().sum())
    assert blanks == running  # the hand check: one running pump per blank mode
    # The newest model's mapping (no saved reading) and a saved reading alike.
    card = detect_tags(df, None, count_reading_of({"mapping": mapping}))["summary"]
    assert card == f"72 pumps · {failed} failed"
    saved = detect_tags(df, {"x": "hours", "e": "failure_mode", "i": "pump", "unit": "Hours"})["summary"]
    assert saved == f"72 pumps · {failed} failed"
    # A status column, where there is one, still decides.
    df2 = df.assign(status=0)
    assert detect_tags(df2, {"x": "hours", "c": "status", "e": "failure_mode", "i": "pump"})["summary"] \
        == "72 pumps · 72 failed"


def test_a_failure_logged_twice_at_one_time_is_still_repairable():
    """A repair history (trucks, the hours of each failure, an end of record)
    where one failure is logged twice at the same hours: the time never goes
    back along a truck's rows, so it is still repeat failures, not one life
    per row ("150 lives · 150 failed")."""
    rows = []
    for u in range(4):
        for k in range(1, 6):
            rows.append([f"T{u:02d}", "West" if u % 2 else "East", 500 * k + 10 * u, "hose", 3000])
    rows.insert(3, list(rows[2]))  # T00's third failure entered twice
    reading = {"x": "hours", "tr": "record_end_hours", "i": "truck", "e": "cause", "unit": "hours", "z": ["depot"]}
    cols = ["truck", "depot", "hours", "cause", "record_end_hours"]
    out = _saved(rows, cols, reading, "reading-repairable-tie")
    assert out["tags"][0] == "Repairable"
    assert out["summary"] == "4 trucks · 21 failures"
    # Guessed from the columns alone, the same.
    assert tags(rows, cols)["tags"][0] == "Repairable"


def test_start_stop_rows_with_late_entry_and_an_item_are_not_repairable():
    """Start and stop rows read as x = stop, tl = start, i = motor (each row
    starts where the motor's last one stopped): stretches of one life with
    the load over time, not repeat failures."""
    rows = [["M-01", 0, 2217, 0, 65], ["M-01", 2217, 4377, 0, 90], ["M-01", 4377, 11275, 1, 65],
            ["M-02", 0, 20957, 0, 65],
            ["M-03", 0, 1882, 0, 90], ["M-03", 1882, 8482, 1, 65]]
    cols = ["motor", "start_h", "stop_h", "failed", "load_pct"]
    late = {"x": "stop_h", "tl": "start_h", "i": "motor", "c": "failed", "c_invert": True, "z": ["load_pct"]}
    out = _saved(rows, cols, late, "reading-tvc-late-entry")
    assert out["tags"] == ["Non-repairable", "Time-varying covariates"]
    assert out["use_for"][0] == "Non-repairable model with time-varying covariates"
    assert out["summary"] == "3 motors · 2 failed"
    # The same rows read as a range (xl = start, xr = stop), as the upload guesses them.
    ranged = {"xl": "start_h", "xr": "stop_h", "i": "motor", "c": "failed", "c_invert": True, "z": ["load_pct"]}
    out = _saved(rows, cols, ranged, "reading-tvc-range")
    assert out["tags"] == ["Non-repairable", "Time-varying covariates"]
    assert out["summary"] == "3 motors · 2 failed"
