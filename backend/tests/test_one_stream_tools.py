"""One stream of events (``one_stream``) through the tool registry: the REST
route, the generated CLI flag and the client's upload, on a replacement log with
no item column."""

import os
import sys

import pytest

from backend.tests.test_api_tools import env  # noqa: F401  (the fixture)

pytestmark = pytest.mark.usefixtures("mcp_on")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "python"))

LOG = os.path.join(os.path.dirname(__file__), "..", "..", "..", "planning", "testing", "data",
                   "sup-j17-lift-pump-replacements.csv")
ROWS = ["replacement,fleet_hours,part"] + [f"{k},{k * 4000 + (k % 5) * 13},pump" for k in range(1, 49)]


def _csv() -> str:
    return "\n".join(ROWS) + "\n"


def test_dataset_upload_and_update_take_one_stream_over_rest(env):  # noqa: F811
    r = env.post("/api/v1/change/dataset_upload", {
        "name": "Pumps", "csv": _csv(), "x_col": "fleet_hours", "all_failed": True, "one_stream": True,
        "not_used": ["replacement", "part"], "unit": "hours"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["reading"]["one_stream"] is True and not out["reading"].get("i")
    from backend.services import datasets as ds_service
    ds = ds_service.get_dataset(env.db, out["id"], ["user-a"])
    assert "Repairable" in ds.tags and "Non-repairable" not in ds.tags
    # Without it the rows are separate units, as before.
    r = env.post("/api/v1/change/dataset_update", {"dataset_id": out["id"], "one_stream": False})
    assert r.status_code == 200, r.text
    assert "one_stream" not in r.json().get("reading", {})
    r = env.post("/api/v1/change/dataset_update", {"dataset_id": out["id"], "one_stream": True})
    assert r.json()["reading"]["one_stream"] is True


@pytest.mark.skipif(not os.path.exists(LOG), reason="the planning test data isn't checked out here")
def test_lift_pump_log_is_one_stream_of_48_events_and_fits(env):  # noqa: F811
    text = open(LOG).read()
    r = env.post("/api/v1/change/dataset_upload", {
        "name": "Lift pumps", "csv": text, "x_col": "fleet_hours", "all_failed": True, "one_stream": True,
        "record_end": 216000, "not_used": ["replacement", "date", "genset", "part", "reason"], "unit": "hours"})
    assert r.status_code == 200, r.text
    ds_id = r.json()["id"]
    res = env.client.post("/api/recurrent/fit", data={
        "dataset_id": ds_id, "i": "", "one_stream": "true", "x": "fleet_hours", "unit": "hours",
        "model": "crow_amsaa"},
        headers={"Authorization": f"Bearer {env.token['user-a']}"})
    assert res.status_code == 200, res.text
    out = res.json()["results"]
    assert out["n_systems"] == 1 and out["n_events"] == 48 and out["end_of_observation"] == 216000
    assert out["beta"] == pytest.approx(0.588, abs=0.001)


def test_cli_upload_has_the_one_stream_flag_and_passes_it(monkeypatch, tmp_path):
    from reliafy import cli

    seen = {}

    class Fake:
        def upload_dataset(self, path, name=None, sheet=None, **args):
            seen.update(args)
            return {}

    monkeypatch.setattr(cli, "render", lambda *a, **k: None)
    parser = cli.builtin_parser()
    assert parser is not None
    ns = parser.parse_args(["upload", "f.csv", "--x-col", "fleet_hours", "--one-stream", "--record-end", "216000"])
    assert cli.cmd_upload(Fake(), ns) == 0
    assert seen["record_end"] == 216000 and seen["one_stream"] is True and seen["x_col"] == "fleet_hours"
    ns = parser.parse_args(["upload", "f.csv"])
    seen.clear()
    cli.cmd_upload(Fake(), ns)
    assert "one_stream" not in seen
