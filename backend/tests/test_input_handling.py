"""Input handling: text parsed in time that grows with its length, stored files
kept to their folder, callbacks only to the configured address, and the
indenture level list found under its new id and the old one."""

import time

import pytest

from backend.services import maintainability, rbd_analysis, rbd_mixture

LONG = 50_000


def _fast(fn, *args, limit=1.0):
    t0 = time.perf_counter()
    out = fn(*args)
    assert time.perf_counter() - t0 < limit, f"{fn.__name__} took too long"
    return out


# ---- assembly paths ----------------------------------------------------------------------

@pytest.mark.parametrize("text, parts", [
    ("Propulsion › Motor 1", ["Propulsion", "Motor 1"]),
    ("Propulsion>Motor 1 / Bearing", ["Propulsion", "Motor 1", "Bearing"]),
    ("A \\ B » C", ["A", "B", "C"]),
    ("  A  ›  › B ", ["A", "B"]),
    ("Pump set", ["Pump set"]),
    ("", []),
    (None, []),
])
def test_assembly_path(text, parts):
    assert maintainability.assembly_path(text) == parts


def test_assembly_path_long_input_is_fast():
    assert _fast(maintainability.assembly_path, " " * LONG + "x") == ["x"]
    assert _fast(maintainability.assembly_path, "a" + " \t" * LONG + "b") == ["a b"]


# ---- mixture parameter names -------------------------------------------------------------

@pytest.mark.parametrize("name, split", [
    ("alpha1", ("alpha", "1")),
    ("weight12", ("weight", "12")),
    ("12", ("1", "2")),
    ("a0", ("a", "0")),
    ("beta1\n", ("beta", "1")),
    ("alpha", None),
    ("1", None),
    ("", None),
    ("al\npha1", None),
])
def test_mixture_parameter_names(name, split):
    assert rbd_mixture._numbered(name) == split


def test_mixture_parameter_name_long_input_is_fast():
    assert _fast(rbd_mixture._numbered, "a" + "00" * LONG + "x") is None
    assert _fast(rbd_mixture._numbered, "a" + "0" * LONG) == ("a", "0" * LONG)


# ---- block label stems -------------------------------------------------------------------

@pytest.mark.parametrize("label, stem", [
    ("Pump B (standby)", ("pump", "b")),
    ("Pump A", ("pump", "a")),
    ("Pump-2", ("pump", "2")),
    ("P2", ("p", "2")),
    ("Train ii", ("train", "ii")),
    ("Fan left", ("fan", "left")),
    ("Duty pump 12", ("pump", "12")),
    ("Compressor", ("compressor", None)),
    ("Valve (x", ("valve (x", None)),
    ("12", ("1", "2")),
    ("x-1z", ("x-1z", None)),
])
def test_label_stem(label, stem):
    assert rbd_analysis._label_stem(label) == stem


def test_label_stem_long_input_is_fast():
    _fast(rbd_analysis._label_stem, "(" * LONG)
    _fast(rbd_analysis._label_stem, "0" + "00" * LONG + "!")
    _fast(rbd_analysis._label_stem, "a " + "0 " * LONG)


# ---- simulation reasons ------------------------------------------------------------------

@pytest.mark.parametrize("text, plain", [
    ("Standby groups need simulation. Simulate the system with availability() or cost().",
     "Standby groups need simulation. Simulate the system."),
    ("by simulation, with availability(demand=...), which take any",
     "by simulation, which takes any"),
    ("Simulate it with  availability()", "Simulate it"),
    ("no space:with availability()", "no space:with availability()"),
    ("2 repair crew(s) for 5 components here", "2 repair crews for 5 repair jobs (each unit of a standby group "
                                                "is one) here"),
    ("1 repair crew(s) for 3 components", "1 repair crew for 3 repair jobs (each unit of a standby group is one)"),
    ("a repair crew(s) for 3 components", "a repair crew(s) for 3 components"),
])
def test_plain_reason(text, plain):
    assert rbd_analysis.plain_reason(text) == plain
    assert rbd_analysis.plain_reason(plain) == plain


def test_plain_reason_long_input_is_fast():
    _fast(rbd_analysis.plain_reason, "x" + " " * LONG + "y")
    _fast(rbd_analysis.plain_reason, "0" * LONG + " repair")
    _fast(rbd_analysis.plain_reason, ", " * LONG)


# ---- stored files ------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["../x", "a/b", "..", "", "a.b", "ab\x00", "é1", "a b"])
def test_document_ids_stay_in_their_folder(tmp_path, bad):
    from backend.maintenance.documents import FileDocumentStore

    store = FileDocumentStore(str(tmp_path / "docs"))
    with pytest.raises(KeyError):
        store._path(bad)
    assert store.get(bad) is None
    store.delete(bad)  # quietly nothing


def test_document_store_round_trip(tmp_path):
    from backend.maintenance.documents import FileDocumentStore

    store = FileDocumentStore(str(tmp_path / "docs"))
    store.put("abc123", b"%PDF-1.4")
    assert store.get("abc123") == b"%PDF-1.4"
    assert (tmp_path / "docs" / "abc123.pdf").exists()
    store.delete("abc123")
    assert store.get("abc123") is None


def test_a_link_out_of_the_folder_is_refused(tmp_path):
    from backend.maintenance.documents import FileDocumentStore

    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"secret")
    store = FileDocumentStore(str(tmp_path / "docs"))
    (tmp_path / "docs" / "abc.pdf").symlink_to(outside)
    assert store.get("abc") is None


@pytest.mark.parametrize("photo_id, size", [("../x", "full"), ("abc", "../../x"), ("abc", "huge"), ("a/b", "thumb")])
def test_photo_paths_stay_in_their_folder(tmp_path, photo_id, size):
    from backend.maintenance.photos import FilePhotoStore

    store = FilePhotoStore(str(tmp_path / "photos"))
    with pytest.raises(KeyError):
        store._path(photo_id, size)
    assert store.get(photo_id, size) is None


def test_photo_store_round_trip(tmp_path):
    from backend.maintenance.photos import FilePhotoStore

    store = FilePhotoStore(str(tmp_path / "photos"))
    store.put("p1", "thumb", b"jpeg")
    assert store.get("p1", "thumb") == b"jpeg"
    store.delete("p1")
    assert store.get("p1", "thumb") is None


# ---- compute callbacks -------------------------------------------------------------------

def test_the_configured_callback_always_wins(monkeypatch):
    from backend import compute_app, config

    monkeypatch.setattr(config, "COMPUTE_CALLBACK_URL", "https://web.example/internal/compute/callback")
    assert compute_app.callback_target("https://elsewhere.example/x") == config.COMPUTE_CALLBACK_URL
    assert compute_app.callback_target(None) == config.COMPUTE_CALLBACK_URL


@pytest.mark.parametrize("url, ok", [
    ("http://localhost:8000/internal/compute/callback", True),
    ("http://127.0.0.1:8000/internal/compute/callback", True),
    ("https://elsewhere.example/internal/compute/callback", False),
    ("http://localhost.example.com/x", False),
    ("http://169.254.169.254/computeMetadata/v1/", False),
    ("file:///etc/hosts", False),
    ("http://[::1", False),
    ("", False),
    (None, False),
    ({"url": "x"}, False),
])
def test_without_configuration_only_a_local_callback(monkeypatch, url, ok):
    from backend import compute_app, config

    monkeypatch.setattr(config, "COMPUTE_CALLBACK_URL", None)
    assert (compute_app.callback_target(url) is not None) is ok


def test_a_task_without_a_usable_callback_is_refused(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import compute_app, config

    monkeypatch.setattr(config, "COMPUTE_CALLBACK_URL", None)
    monkeypatch.setattr(compute_app, "_post", lambda *a, **k: pytest.fail("posted a callback"))
    r = TestClient(compute_app.app).post("/compute/run", json={
        "job_id": "j1", "kind": "availability", "request": {}, "callback_url": "https://elsewhere.example/cb"})
    assert r.status_code == 500


# ---- indenture level list ----------------------------------------------------------------

def test_part_levels_are_found_under_the_old_id_and_saved_there():
    from backend.maintenance.service import PROJECTORS, part_levels_id, part_levels_node
    from backend.maintenance.store import GraphStore

    s = GraphStore(":memory:", PROJECTORS)
    org = "org-1"
    s.put_node(org, "part-levels-0123456789abcdef", "PartLevels", {"levels": ["System", "LRU"]})
    assert part_levels_node(s, org)["levels"] == ["System", "LRU"]
    PROJECTORS["part_levels.set"](s, org, {"levels": ["System", "SRU"]})
    assert [n["levels"] for n in s.nodes(org, "PartLevels")] == [["System", "SRU"]]
    assert s.node(org, part_levels_id(org)) is None  # kept where it was until a rebuild


def test_part_levels_new_graph_uses_the_new_id():
    from backend.maintenance.service import PROJECTORS, part_levels_id, part_levels_node
    from backend.maintenance.store import GraphStore

    s = GraphStore(":memory:", PROJECTORS)
    PROJECTORS["part_levels.set"](s, "org-2", {"levels": ["A"]})
    assert part_levels_node(s, "org-2")["id"] == part_levels_id("org-2")
    assert len(part_levels_id("org-2")) == len("part-levels-") + 16


def test_set_plan_needs_a_plain_user_id():
    import mongomock

    from backend.services import billing

    db = mongomock.MongoClient()["plans"]
    with pytest.raises(ValueError):
        billing.set_plan(db, {"$ne": None}, "pro")
    assert db.users.count_documents({}) == 0


def test_set_plan_matches_the_user_by_value():
    import mongomock

    from backend.services import billing

    db = mongomock.MongoClient()["plans"]
    db.users.insert_one({"_id": "u1", "plan": "free"})
    assert billing.set_plan(db, "u1", "pro") == "free"
    assert db.users.find_one({"_id": "u1"})["plan"] == "pro"


def test_get_model_matches_ids_by_value():
    import mongomock

    from backend.services import models

    db = mongomock.MongoClient()["models"]
    db.models.insert_one({"_id": "m1", "id": "m1", "owner_id": "u1", "name": "Pump"})
    for bad in ({"$ne": None}, {"$gt": ""}, ["m1"], None, 1, ""):
        assert models.get_model(db, bad) is None
        assert models.get_model(db, bad, "u1") is None
    assert models.get_model(db, "$ne") is None  # a string is only ever a value
    found = models.get_model(db, "m1", "u1")
    assert found is not None and found.id == "m1"
    assert models.get_model(db, "m1", "someone-else") is None


def test_plan_change_looks_up_plan_walls_by_value(monkeypatch):
    import mongomock

    from backend.services import usage

    db = mongomock.MongoClient()["usage"]
    monkeypatch.setattr(usage, "enabled", lambda: True)
    recorded = []
    monkeypatch.setattr(usage, "record", lambda _db, **kw: recorded.append(kw["feature"]))
    db.usage_events.insert_one({"uid": "u1", "channel": "mcp", "outcome": next(iter(usage.WALL_OUTCOMES))})
    usage.on_plan_change(db, "u1", "free", "pro")
    assert recorded == [usage.PRO_UPGRADE, usage.UPGRADE_AFTER_LOCK]
    recorded.clear()
    usage.on_plan_change(db, {"$ne": None}, "free", "pro")  # not a user id: nothing looked up or recorded
    assert recorded == []


def test_contained_path_root_and_links(tmp_path):
    from backend import main

    root = tmp_path / "dist"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("x")
    (root / "link.txt").symlink_to(tmp_path / "secret.txt")
    (tmp_path / "dist-other").mkdir()
    assert main.contained_path(root, root) == root.resolve()
    assert main.contained_path(root / "link.txt", root) is None
    assert main.contained_path(root / ".." / "dist-other", root) is None  # a shared prefix isn't inside
    assert main.contained_path(root / "a\x00b", root) is None
