"""Strategy, forecasts, system models and reports: the 12 Nov walkthrough
friction fixes that live in the backend.

- A saved analysis's list row rounds as its result does (2,000 h, not 1,999).
- A constant-rate (exponential) forecast is exact: Poisson, mean use / MTBF.
- Open as RBD names blocks for the part that works, not the failure.
- The Open-PSA download keeps the tree's name.
- The RBD script ranks importance at the Calculator's "Evaluate at t" and
  never waits on a plot window.
- A saved report can be read inside the app (Reports › View).
"""

import matplotlib

matplotlib.use("Agg")

import pytest  # noqa: E402
from scipy.stats import poisson  # noqa: E402

from backend.tests.test_fleet import A, _fleet_with, _make_model, session  # noqa: E402,F401 - session is a fixture
from backend.tests.test_reports import _fit_model, _report, client  # noqa: E402,F401 - client is a fixture


def test_saved_list_rounds_the_interval_as_the_result_does():
    from backend.services.strategy_store import _about

    assert _about(1999.4) == "2,000"
    assert _about(1764.9) == "1,760"
    assert _about(316.4) == "316"
    assert _about(0.000123) == "0.000123"


def test_constant_rate_forecast_is_exact(session):
    """20 items, MTBF from the fit, 730 h a month for 12 months: expected
    failures are use / MTBF exactly, flat by month, with Poisson ranges."""
    from backend.services import fleet as fs

    model = _make_model(session, A, distribution="exponential", kind="random")
    lam = next(p["value"] for p in model.results["params"] if p["name"] == "failure_rate")
    items = [{"name": f"s{k}", "current_use": 100.0 * k} for k in range(20)]
    fleet = _fleet_with(session, A, model, items, method="renewals", periods=12, rate=10.0)
    f = fs.compute(session, fleet, A)
    assert f["status"] == "ok"
    total = 20 * 12 * 10.0 * lam
    assert f["expected"] == pytest.approx(total, rel=1e-9)
    assert f["interval"] == [poisson.ppf(0.05, total), poisson.ppf(0.95, total)]
    assert f["per_period"] == pytest.approx([total / 12] * 12, rel=1e-9)
    assert f["interval_method"] == "exact"
    assert all(row["expected"] == pytest.approx(120.0 * lam, rel=1e-9) for row in f["per_item"])
    st = f["strategy"]
    assert st["total"]["failures"]["expected"] == pytest.approx(total, rel=1e-9)
    assert [p["failures"]["expected"] for p in st["per_period"]] == pytest.approx([total / 12] * 12, rel=1e-9)
    if st.get("yearly"):
        assert st["yearly"][0]["failures"]["expected"] == pytest.approx(total, rel=1e-6)


def test_wear_out_forecast_is_still_simulated(session):
    from backend.services import fleet as fs

    model = _make_model(session, A)  # Weibull, wearing out
    items = [{"name": "a", "current_use": 10.0}]
    f = fs.compute(session, _fleet_with(session, A, model, items, "renewals", periods=6, rate=5.0), A)
    assert f["status"] == "ok" and f.get("interval_method") != "exact"


@pytest.mark.parametrize("label, block", [
    ("Dosing pump fails", "Dosing pump"),
    ("UV reactor failure", "UV reactor"),
    ("Failure of the intake screen", "Intake screen"),
    ("Pump A has failed", "Pump A"),
    ("Power supply", "Power supply"),
    ("fails", "fails"),  # nothing would be left: kept
])
def test_block_names_drop_the_failure_words(label, block):
    from backend.services.fault_trees import block_name

    assert block_name(label) == block


def test_open_as_rbd_blocks_are_named_for_the_part():
    from backend.services import fault_trees as ft

    tree = {"top": "top", "unit": "hours", "nodes": [
        {"id": "top", "type": "gate", "gate": "or", "label": "Loss of treated water", "inputs": ["a", "b"]},
        {"id": "a", "type": "event", "label": "Dosing pump fails",
         "model": {"source": "params", "distribution_id": "exponential",
                   "params": [{"name": "failure_rate", "value": 1e-4}]}},
        {"id": "b", "type": "event", "label": "UV reactor failure",
         "model": {"source": "params", "distribution_id": "exponential",
                   "params": [{"name": "failure_rate", "value": 2e-4}]}},
    ]}
    graph, _notes = ft.to_rbd_graph(ft.normalize_tree(tree))
    labels = {(n.get("data") or {}).get("label") or n.get("label") for n in graph["nodes"]}
    assert {"Dosing pump", "UV reactor"} <= labels
    assert not any("fail" in str(x).lower() for x in labels)


def test_openpsa_download_keeps_the_trees_name():
    from backend.routers.fault_trees import xml_disposition

    header = xml_disposition("Loss of treated water – UV & dosing")
    assert 'filename="Loss of treated water UV dosing.xml"' in header
    assert "filename*=UTF-8''Loss%20of%20treated%20water%20%E2%80%93%20UV%20%26%20dosing.xml" in header
    assert 'filename="fault-tree.xml"' in xml_disposition("")
    assert "\n" not in xml_disposition('a"\r\nb')


def _diagram():
    m = lambda rate: {"source": "params", "distribution_id": "exponential",  # noqa: E731
                      "params": [{"name": "failure_rate", "value": rate}]}
    return {"unit": "hours", "nodes": [
        {"id": "input", "type": "input"}, {"id": "output", "type": "output"},
        {"id": "c1", "type": "component", "data": {"label": "Screen", "model": m(1e-4)}},
        {"id": "c2", "type": "component", "data": {"label": "Reactor", "model": m(3e-4)}},
    ], "edges": [{"source": "input", "target": "c1"}, {"source": "c1", "target": "c2"},
                 {"source": "c2", "target": "output"}]}


def test_rbd_script_ranks_at_the_calculators_time_and_never_blocks(tmp_path):
    from backend.services import rbd_export
    from backend.tests.python_scripts import run

    source = rbd_export.to_python(_diagram(), "Treatment train", evaluate_at=8760)
    assert "EVALUATE_AT = 8760" in source
    assert "plt.show()" in source and "sys.stdout.isatty()" in source
    out = run(source, tmp_path)
    assert "Importance at t = 8,760" in out["_stdout"]
    assert (tmp_path / "exported.png").exists()
    # Without a time, the default (where R falls to 90%) as before.
    assert "EVALUATE_AT = None" in rbd_export.to_python(_diagram(), "Treatment train")


def test_a_report_can_be_read_in_the_app(client):
    client.act_as(A)
    model_id = _fit_model(client)
    rep = _report(client, [{"collection": "models", "artifact_id": model_id, "note": "The main finding."}]).json()
    r = client.get(f"/api/reports/{rep['id']}/view")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Pump reliability review"
    assert body["sections"][0]["artifact"]["name"] == "Pump bearings"
    assert body["sections"][0]["note"] == "The main finding."
    client.act_as("user-b")
    assert client.get(f"/api/reports/{rep['id']}/view").status_code == 404


def test_rbd_downloads_both_work_with_and_without_a_time(client):
    """Download as Python takes the Calculator's time; the JSON download takes none."""
    client.act_as(A)
    saved = client.post("/api/rbds", json={"name": "Treatment train", "graph": _diagram()})
    assert saved.status_code == 200, saved.text
    rid = saved.json()["id"]
    py = client.get(f"/api/rbds/{rid}/export.py?t=500")
    assert py.status_code == 200, py.text
    assert "EVALUATE_AT = 500" in py.text
    assert client.get(f"/api/rbds/{rid}/export.json").status_code == 200
