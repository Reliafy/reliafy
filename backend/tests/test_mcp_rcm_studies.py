"""RCM studies over MCP as structured JSON: list_rcm_studies, get_rcm_study,
create_rcm_study and update_rcm_study. A study made here is the one the app's
editor or an Excel import makes — the same tree, validation, plan cap and
evidence-link check."""

import pytest

from backend.tests.test_mcp import _err, _ok
from backend.tests.test_mcp_uploads import A, B, FMEA, FREE, _call, _upload, env, free_env  # noqa: F401

pytestmark = pytest.mark.usefixtures("mcp_on")

PUMP = [{
    "text": "Pump water at 50 l/s", "standard": "At least 50 l/s at 3 bar",
    "failures": [
        {"text": "Fails to pump", "modes": [
            {"text": "Bearing seizes", "effects": "Pump stops", "consequence": "operational",
             "decision": {"outcome": "on_condition", "task": "Vibration check", "interval": 1,
                          "interval_unit": "months"}},
            {"text": "Impeller worn", "effects": "Low flow", "consequence": "operational",
             "decision": {"outcome": "fixed_interval", "task": "Replace impeller"}},
            {"text": "Coupling fails", "consequence": "non_operational",
             "decision": {"outcome": "rtf", "rtf_basis": "random"}},
        ]},
        {"text": "Leaks", "modes": [
            {"text": "Seal fails", "effects": "Water on floor", "consequence": "safety",
             "decision": {"outcome": "fixed_interval", "interval": 4000}},
        ]},
    ],
}]


def _create(env, uid=A, **extra) -> dict:
    return _ok(_call(env.token[uid], "create_rcm_study", {"name": "Cooling water pump", "system": "P-101",
                                                          "functions": PUMP, **extra}))


def _strip_ids(functions):
    return [{**fn, "id": None, "failures": [
        {**f, "id": None, "modes": [{**m, "id": None} for m in f["modes"]]} for f in fn["failures"]]}
        for fn in functions]


def test_create_saves_the_study_the_app_would(env):
    out = _create(env, description="From the 2024 review")
    assert out["name"] == "Cooling water pump" and out["system"] == "P-101"
    assert out["counts"] == {"functions": 1, "failures": 2, "modes": 4, "decisions": 4, "scheduled_tasks": 2}
    assert out["evidence"]["modes"] == 4 and out["evidence"]["unevidenced"] == 4
    assert out["url"].endswith(f"/rcm/studies/{out['study_id']}")
    # Decisions that won't become scheduled tasks as they stand are pointed out.
    assert any("no interval" in w and "Impeller worn" in w for w in out["warnings"])
    assert any("no interval_unit" in w and "Seal fails" in w for w in out["warnings"])

    doc = env.db.rcm_studies.find_one({"_id": out["study_id"]})
    assert doc["owner_id"] == A and doc["description"] == "From the 2024 review"
    assert doc["updated_by"] == {"uid": A, "name": A}
    from backend.services import rcm as rcm_service

    assert _strip_ids(doc["functions"]) == _strip_ids(rcm_service.clean_tree(PUMP))  # the editor's own cleaning
    # The app reads it like any other study.
    listed = _ok(_call(env.token[A], "list_rcm_studies"))["studies"]
    assert [(s["id"], s["modes"], s["decisions"]) for s in listed] == [(out["study_id"], 4, 4)]
    assert "data_notice" in _ok(_call(env.token[A], "list_rcm_studies"))


def test_the_same_worksheet_as_json_or_as_an_excel_import(env):
    """The FMEA workbook imported, and the same rows given as JSON, make the
    same worksheet."""
    link, _ = _upload(env, FMEA, "pump-fmea.xlsx", purpose="excel")
    imported = _ok(_call(env.token[A], "import_excel", {"upload_id": link["upload_id"], "target": "rcm"}))
    as_json = [{"text": "Pump water at 50 l/s", "failures": [
        {"text": "Fails to pump", "modes": [
            {"text": "Bearing seizes", "effects": "Pump stops", "consequence": "operational", "notes": "Severity 7"},
            {"text": "Impeller worn", "effects": "Low flow", "consequence": "operational", "notes": "Severity 5"}]},
        {"text": "Leaks", "modes": [
            {"text": "Seal fails", "effects": "Water on floor", "consequence": "safety", "notes": "Severity 8"}]},
    ]}]
    made = _ok(_call(env.token[A], "create_rcm_study", {"name": "Pump", "functions": as_json}))
    a = env.db.rcm_studies.find_one({"_id": imported["study_id"]})["functions"]
    b = env.db.rcm_studies.find_one({"_id": made["study_id"]})["functions"]
    assert _strip_ids(a) == _strip_ids(b)


def test_get_reads_it_back_with_ids_and_writes_back_unchanged(env):
    out = _create(env)
    got = _ok(_call(env.token[A], "get_rcm_study", {"study_id": out["study_id"]}))
    assert "data_notice" in got and got["system"] == "P-101" and got["counts"]["modes"] == 4
    mode = got["functions"][0]["failures"][0]["modes"][0]
    assert mode["id"] and mode["decision"]["interval_unit"] == "months"
    assert mode["decision"]["check"]["status"] == "unevidenced"
    assert mode["decision"]["check"]["expected_evidence"] == "degradation_model"
    before = env.db.rcm_studies.find_one({"_id": out["study_id"]})["functions"]

    # What get_rcm_study gives, written back whole, changes nothing (check is ignored).
    again = _ok(_call(env.token[A], "update_rcm_study", {"study_id": out["study_id"], "mode": "replace",
                                                         "functions": got["functions"]}))
    assert again["action"] == "replace" and again["counts"] == again["counts_before"]
    assert env.db.rcm_studies.find_one({"_id": out["study_id"]})["functions"] == before

    # One function in full; a big study as an outline.
    fid = got["functions"][0]["id"]
    one = _ok(_call(env.token[A], "get_rcm_study", {"study_id": out["study_id"], "function_id": fid}))
    assert [f["id"] for f in one["functions"]] == [fid]
    assert "no function" in _err(_call(env.token[A], "get_rcm_study", {"study_id": out["study_id"],
                                                                       "function_id": "nope"}))


def test_a_large_study_comes_back_as_an_outline(env, monkeypatch):
    from backend import mcp_server

    monkeypatch.setattr(mcp_server, "_RCM_FULL_MODES", 2)
    out = _create(env)
    got = _ok(_call(env.token[A], "get_rcm_study", {"study_id": out["study_id"]}))
    assert got["outline"] is True and "function_id" in got["note"]
    assert [f["n_modes"] for f in got["functions"][0]["failures"]] == [3, 1]


def test_merge_adds_and_changes_nodes_by_id(env):
    out = _create(env)
    got = _ok(_call(env.token[A], "get_rcm_study", {"study_id": out["study_id"]}))
    fn = got["functions"][0]
    fails, leaks = fn["failures"]
    impeller = fails["modes"][1]

    merged = _ok(_call(env.token[A], "update_rcm_study", {"study_id": out["study_id"], "functions": [
        {"id": fn["id"], "failures": [
            # A new mode under an existing failure, and a changed decision on an existing mode.
            {"id": fails["id"], "modes": [
                {"text": "Cavitation", "consequence": "operational"},
                {"id": impeller["id"], "decision": {"outcome": "fixed_interval", "task": "Replace impeller",
                                                    "interval": 2, "interval_unit": "years"}}]},
            # A new failure under the existing function.
            {"text": "Runs noisily", "modes": [{"text": "Loose baseplate"}]}]},
        # And a new function.
        {"text": "Contain the water", "failures": []}]}))
    assert merged["action"] == "merge"
    assert merged["counts"]["modes"] == 6 and merged["counts"]["functions"] == 2
    assert merged["counts_before"]["modes"] == 4
    assert not any("Impeller worn" in w for w in merged.get("warnings", []))

    doc = env.db.rcm_studies.find_one({"_id": out["study_id"]})["functions"]
    assert doc[0]["text"] == "Pump water at 50 l/s" and doc[0]["standard"] == "At least 50 l/s at 3 bar"
    modes = doc[0]["failures"][0]["modes"]
    assert [m["text"] for m in modes] == ["Bearing seizes", "Impeller worn", "Coupling fails", "Cavitation"]
    assert modes[1]["id"] == impeller["id"] and modes[1]["effects"] == "Low flow"  # kept
    assert modes[1]["decision"]["interval"] == 2.0 and modes[1]["decision"]["interval_unit"] == "years"
    assert doc[0]["failures"][1]["id"] == leaks["id"]

    # An id that isn't there is refused, not added.
    msg = _err(_call(env.token[A], "update_rcm_study", {"study_id": out["study_id"], "functions": [
        {"id": fn["id"], "failures": [{"id": "nope", "modes": []}]}]}))
    assert "no functional failure with id “nope”" in msg


def test_replace_and_details(env):
    out = _create(env)
    done = _ok(_call(env.token[A], "update_rcm_study", {
        "study_id": out["study_id"], "mode": "replace", "name": "P-101 RCM", "system": "Pump P-101",
        "functions": [{"text": "Pump water", "failures": [{"text": "No flow", "modes": [{"text": "Seized"}]}]}]}))
    assert done["counts"]["modes"] == 1 and done["name"] == "P-101 RCM" and done["system"] == "Pump P-101"
    details = _ok(_call(env.token[A], "update_rcm_study", {"study_id": out["study_id"], "description": "v2"}))
    assert details["action"] == "details" and details["counts"]["modes"] == 1
    assert env.db.rcm_studies.find_one({"_id": out["study_id"]})["description"] == "v2"
    assert "Nothing to change" in _err(_call(env.token[A], "update_rcm_study", {"study_id": out["study_id"]}))
    assert "needs functions" in _err(_call(env.token[A], "update_rcm_study", {"study_id": out["study_id"],
                                                                              "mode": "replace"}))
    assert "needs a name" in _err(_call(env.token[A], "update_rcm_study", {"study_id": out["study_id"],
                                                                           "name": "  "}))


@pytest.mark.parametrize("functions, expected", [
    ([{"text": "F", "failures": [{"text": "FF", "modes": [{"effects": "no text"}]}]}],
     "Function 1 › failure 1 › mode 1: every failure mode needs text"),
    ([{"text": "F", "failures": [{"text": "FF", "modes": [{"text": "M", "decision": {"outcome": "rtf"}}]}]}],
     "needs rtf_basis"),
    ([{"text": "F", "failures": [{"text": "FF", "modes": [
        {"text": "M", "decision": {"outcome": "accept", "rtf_basis": "random"}}]}]}],
     "rtf_basis applies to outcome rtf only"),
    ([{"text": "F", "failures": [{"text": "FF", "modes": [
        {"text": "M", "decision": {"outcome": "fixed_interval", "interval_unit": "days"}}]}]}],
     "interval_unit was given without an interval"),
    ([{"id": "x", "text": "F", "failures": [{"id": "x", "text": "FF"}]}], "used twice"),
    ([{"text": "F", "failures": [{"text": "FF", "modes": [{"text": "M", "effect": "typo"}]}]}], "effect"),
    ([{"text": "F", "failures": [{"text": "FF", "modes": [{"text": "M", "consequence": "costly"}]}]}],
     "consequence"),
    ([{"text": "F", "failures": [{"text": "FF", "modes": [
        {"text": "M", "decision": {"outcome": "fixed_interval", "interval": -1}}]}]}], "interval"),
])
def test_invalid_worksheets_are_refused_saying_where(env, functions, expected):
    msg = _err(_call(env.token[A], "create_rcm_study", {"name": "Bad", "functions": functions}))
    assert expected in msg
    assert env.db.rcm_studies.count_documents({}) == 0


def test_size_limit(env, monkeypatch):
    from backend import mcp_server

    monkeypatch.setattr(mcp_server, "_RCM_MAX_NODES", 3)
    msg = _err(_call(env.token[A], "create_rcm_study", {"name": "Big", "functions": PUMP}))
    assert "would have 4 failure modes; a study holds at most 3" in msg
    assert env.db.rcm_studies.count_documents({}) == 0


def test_evidence_must_be_the_users_own_or_a_sample(env):
    model_id = "b-model"
    env.db.models.insert_one({"_id": model_id, "name": "B's fit", "owner_id": B})
    functions = [{"text": "F", "failures": [{"text": "FF", "modes": [
        {"text": "M", "decision": {"outcome": "rtf", "rtf_basis": "random",
                                   "evidence": {"type": "model", "id": model_id}}}]}]}]
    assert "can't open" in _err(_call(env.token[A], "create_rcm_study", {"name": "S", "functions": functions}))
    assert env.db.rcm_studies.count_documents({}) == 0


def test_only_the_users_own_studies_change(env):
    from backend import config
    from backend.services import rcm as rcm_service

    out = _create(env)
    assert "not found" in _err(_call(env.token[B], "get_rcm_study", {"study_id": out["study_id"]}))
    assert "not found" in _err(_call(env.token[B], "update_rcm_study", {"study_id": out["study_id"],
                                                                        "name": "Mine now"}))
    sample = rcm_service.create_study(env.db, "Sample pump", "", "", config.SAMPLE_OWNER)
    got = _ok(_call(env.token[A], "get_rcm_study", {"study_id": sample.id}))
    assert got["is_sample"] is True
    assert "shared sample" in _err(_call(env.token[A], "update_rcm_study", {"study_id": sample.id,
                                                                            "name": "Mine"}))


def test_the_free_plan_cap_applies(free_env, monkeypatch):
    from backend import config

    env = free_env
    monkeypatch.setattr(config, "FREE_MAX_RCM_STUDIES", 1)
    _create(env, uid=FREE)
    msg = _err(_call(env.token[FREE], "create_rcm_study", {"name": "Second", "functions": PUMP}))
    assert "limit of 1 saved RCM studies" in msg
    assert env.db.rcm_studies.count_documents({"owner_id": FREE}) == 1
