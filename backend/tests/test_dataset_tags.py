"""Dataset tags (planning #261): what a dataset holds, detected from its columns."""

import pandas as pd

from backend.services.datasets import detect_tags


def tags(rows, cols):
    return detect_tags(pd.DataFrame(rows, columns=cols))


def test_life_data_with_and_without_covariates():
    plain = tags([[f"P-{i}", 100 + i, i % 2] for i in range(10)], ["pump", "hours", "censored"])
    assert plain["tags"] == ["Non-repairable"]
    assert plain["use_for"][0] == "Life model"
    cov = tags([[f"P-{i}", 100 + i, i % 2, 60 + i % 3, "North"] for i in range(10)],
               ["pump", "hours", "censored", "load_pct", "site"])
    assert cov["tags"] == ["Non-repairable", "Covariates"]
    assert cov["use_for"][0] == "Life model with covariates"


def test_recurrent_events():
    rows = [[f"HT-{u}", 1000 * k + 37 * u, 0 if k < 3 else 1, 180 + 40 * (u % 2)] for u in range(4) for k in range(1, 4)]
    out = tags(rows, ["truck", "engine_hours", "censored", "payload_t"])
    assert out["tags"] == ["Repairable", "Covariates"]
    assert out["use_for"] == ["Repairable model with covariates"]


def test_readings_are_measurements():
    rows = [[f"B-{u}", 1000 * k, 2.0 + 0.1 * k + u] for u in range(4) for k in range(4)]
    out = tags(rows, ["bearing", "hours", "vibration_mm_s"])
    assert out["tags"] == ["Non-repairable", "Measurements"]
    assert "Condition monitoring (the readings)" in out["use_for"]


def test_start_stop_rows_with_changing_load():
    rows = [[f"TX-{u}", 2000 * k, 2000 * (k + 1), 1 if k < 2 else 0, [55, 70, 85][(u + k) % 3]]
            for u in range(4) for k in range(3)]
    out = tags(rows, ["transformer", "start_hours", "stop_hours", "censored", "load_pct"])
    assert out["tags"] == ["Non-repairable", "Time-varying covariates"]
    assert out["use_for"] == ["Life model with time-varying covariates"]


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


def test_lifetimes_and_readings_pair_by_their_unit_ids():
    from types import SimpleNamespace

    from backend.services import datasets as svc

    def ds(id_, name, csv):
        return SimpleNamespace(id=id_, name=name, checksum=id_, data=csv.encode())

    life = ds("L", "Bearing lifetimes", "bearing,hours,censored\n" + "\n".join(f"B-{i},{100+i},{i % 2}" for i in range(6)))
    reads = ds("R", "Bearing readings", "bearing,hours,vibration\n" + "\n".join(
        f"B-{i},{h},{2 + h / 1000}" for i in range(6) for h in (0, 1000, 2000)))
    other = ds("O", "Pump lifetimes", "pump,hours,censored\n" + "\n".join(f"P-{i},{100+i},0" for i in range(6)))
    pairs = svc.condition_pairs([life, reads, other])
    assert pairs == {"L": [{"id": "R", "name": "Bearing readings"}], "R": [{"id": "L", "name": "Bearing lifetimes"}]}
    assert "_ids" not in svc.dataset_tags(life)
