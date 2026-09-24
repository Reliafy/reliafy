"""Public share links for RBDs: the graph goes out sanitised, the analysis is
computed server-side in the grantor's scope, and the same ownership rules as
every other public link apply."""

import matplotlib

matplotlib.use("Agg")

from backend.tests.test_public_links import A, B, client  # noqa: F401 - fixture


def _component(node_id, label, alpha, beta, repair=None):
    node = {
        "id": node_id,
        "type": "component",
        "position": {"x": 0, "y": 0},
        "data": {
            "label": label,
            "model": {
                "source": "saved",
                "modelId": "model-" + node_id,
                "distribution_id": "weibull",
                "distribution": "Weibull",
                "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}],
            },
        },
    }
    if repair is not None:
        node["data"]["repair"] = {
            "source": "params", "distribution_id": "lognormal",
            "params": [{"name": "mu", "value": repair}, {"name": "sigma", "value": 0.4}],
        }
    return node


def _rbd_graph(repairable=False, extra_nodes=(), extra_edges=()):
    repair = 2.0 if repairable else None
    return {
        "unit": "hours",
        "repairable": repairable,
        "ccf_groups": [],
        "nodes": [
            {"id": "input", "type": "input", "data": {"label": "Input"}, "position": {"x": 0, "y": 0}},
            {"id": "output", "type": "output", "data": {"label": "Output"}, "position": {"x": 600, "y": 0}},
            _component("ctrl", "Controller", 2000, 1.6, repair),
            _component("pumpA", "Pump A", 900, 1.4, repair),
            _component("pumpB", "Pump B", 900, 1.4, repair),
            *extra_nodes,
        ],
        "edges": [
            {"id": "e1", "source": "input", "target": "ctrl"},
            {"id": "e2", "source": "ctrl", "target": "pumpA"},
            {"id": "e3", "source": "ctrl", "target": "pumpB"},
            {"id": "e4", "source": "pumpA", "target": "output"},
            {"id": "e5", "source": "pumpB", "target": "output"},
            *extra_edges,
        ],
    }


def _save_rbd(client, name="Cooling loop", graph=None):
    r = client.post("/api/rbds", json={"name": name, "graph": graph or _rbd_graph()})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _link_rbd(client, rbd_id):
    r = client.post("/api/public-links", json={"collection": "rbds", "artifact_id": rbd_id})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_rbd_link_public_read_carries_graph_and_analysis(client):
    client.act_as(A)
    rbd_id = _save_rbd(client)
    token = _link_rbd(client, rbd_id)
    # Idempotent, like every other collection.
    assert client.post(
        "/api/public-links", json={"collection": "rbds", "artifact_id": rbd_id}
    ).json()["token"] == token

    client.act_as(None)
    pub = client.get(f"/api/public/{token}")
    assert pub.status_code == 200
    data = pub.json()
    assert data["collection"] == "rbds"
    assert data["shared_by"] == "Alice"
    a = data["artifact"]
    assert a["name"] == "Cooling loop"
    assert a["graph"]["unit"] == "hours"
    assert {n["id"] for n in a["graph"]["nodes"]} == {"input", "output", "ctrl", "pumpA", "pumpB"}
    assert len(a["graph"]["edges"]) == 5
    # Positions survive so the public canvas matches the owner's layout.
    assert a["graph"]["nodes"][2]["position"] == {"x": 0, "y": 0}

    # The analysis is computed server-side: reliability curve, MTTF, B-lives.
    an = a["analysis"]
    assert a["analysis_error"] is None
    assert an.get("kind") != "repairable"
    assert an["unit"] == "hours"
    assert an["mttf"] > 0 and an["blife"]["b10"] > 0
    assert len(an["time"]) == len(an["system"]["sf"]) > 10
    assert an["structure"]["min_cut_sets"]


def test_rbd_public_payload_has_no_identities_or_saved_ids(client):
    client.act_as(A)
    rbd_id = _save_rbd(client)
    token = _link_rbd(client, rbd_id)
    client.act_as(None)
    r = client.get(f"/api/public/{token}")
    body = r.text
    assert "owner_id" not in body and "updated_by" not in body and "read_only" not in body
    assert A not in body and "a@x.com" not in body
    # Saved-model references are the owner's artifact ids — not shared.
    assert "modelId" not in body and "model-ctrl" not in body
    # ...but the model summary the canvas renders is still there.
    model = r.json()["artifact"]["graph"]["nodes"][2]["data"]["model"]
    assert model["distribution"] == "Weibull" and len(model["params"]) == 2


def test_rbd_repairable_public_read_reports_availability(client):
    client.act_as(A)
    rbd_id = _save_rbd(client, name="Repairable loop", graph=_rbd_graph(repairable=True))
    token = _link_rbd(client, rbd_id)
    client.act_as(None)
    a = client.get(f"/api/public/{token}").json()["artifact"]
    assert a["graph"]["repairable"] is True
    an = a["analysis"]
    assert an["kind"] == "repairable"
    assert 0 < an["steady_state_availability"] <= 1
    assert an["mean_up_time"] > 0 and an["mean_down_time"] > 0


def test_rbd_subsystem_resolves_in_grantor_scope_and_hides_its_id(client):
    client.act_as(A)
    sub_id = _save_rbd(client, name="Pump pair")
    top = _rbd_graph(extra_nodes=[{
        "id": "ss1", "type": "subsystem", "position": {"x": 300, "y": 200},
        "data": {"label": "Sub-system", "kind": "subsystem", "rbd": {"id": sub_id, "name": "Pump pair"}},
    }], extra_edges=[
        {"id": "e6", "source": "ctrl", "target": "ss1"},
        {"id": "e7", "source": "ss1", "target": "output"},
    ])
    top_id = _save_rbd(client, name="Plant", graph=top)
    token = _link_rbd(client, top_id)

    client.act_as(None)
    r = client.get(f"/api/public/{token}")
    assert r.status_code == 200
    a = r.json()["artifact"]
    assert a["analysis"] is not None and a["analysis_error"] is None
    ss = next(n for n in a["graph"]["nodes"] if n["id"] == "ss1")
    assert ss["data"]["rbd"] == {"name": "Pump pair"}
    assert sub_id not in r.text


def test_rbd_unanalysable_diagram_still_renders(client):
    client.act_as(A)
    graph = _rbd_graph()
    graph["nodes"][2]["data"]["model"] = None  # controller has no life model
    rbd_id = _save_rbd(client, name="Draft", graph=graph)
    token = _link_rbd(client, rbd_id)
    client.act_as(None)
    r = client.get(f"/api/public/{token}")
    assert r.status_code == 200
    a = r.json()["artifact"]
    assert a["analysis"] is None
    assert "life model" in a["analysis_error"]
    assert len(a["graph"]["nodes"]) == 5


def test_rbd_only_owner_can_link_and_revoked_link_is_gone(client):
    client.act_as(A)
    rbd_id = _save_rbd(client)
    token = _link_rbd(client, rbd_id)

    client.act_as(B)
    r = client.post("/api/public-links", json={"collection": "rbds", "artifact_id": rbd_id})
    assert r.status_code == 404
    assert client.delete(f"/api/public-links/{token}").status_code == 404
    client.act_as(None)
    assert client.get(f"/api/public/{token}").status_code == 200

    client.act_as(A)
    assert client.delete(f"/api/public-links/{token}").status_code == 200
    client.act_as(None)
    assert client.get(f"/api/public/{token}").status_code == 404


def test_rbd_link_dies_with_diagram(client):
    client.act_as(A)
    rbd_id = _save_rbd(client)
    token = _link_rbd(client, rbd_id)
    assert client.delete(f"/api/rbds/{rbd_id}").status_code == 200
    client.act_as(None)
    assert client.get(f"/api/public/{token}").status_code == 404
