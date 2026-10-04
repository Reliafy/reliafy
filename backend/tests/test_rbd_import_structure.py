"""The one-line structure and minimal cut sets an import preview shows (#187):
backend/services/rbd_import/structure.py."""

from backend.services import rbd_import
from backend.services.rbd_graph import normalize_graph
from backend.services.rbd_import import structure


def _describe_dft(text: str) -> dict:
    (d,) = rbd_import.import_file(text.encode(), "x.dft", time_unit="Hours")
    return structure.describe(normalize_graph(d.graph))


def test_voting_and_series():
    out = _describe_dft('toplevel "Sys"; "Sys" or "Ctrl" "Sensors"; "Sensors" 2of3 "S1" "S2" "S3";'
                        '"Ctrl" lambda=1e-4; "S1" lambda=1e-3; "S2" lambda=1e-3; "S3" lambda=1e-3;')
    assert out["structure"] == "Ctrl → 2-of-3(S1, S2, S3)"
    assert out["cut_sets"] == [["Ctrl"], ["S1", "S2"], ["S1", "S3"], ["S2", "S3"]]


def test_a_repeated_event_is_one_component_in_the_cut_sets():
    # Parallel groups in series are wired exit-to-entry as a full mesh.
    out = _describe_dft('toplevel "T"; "T" or "G1" "G2"; "G1" and "A" "B"; "G2" and "A" "C";'
                        '"A" lambda=1e-3; "B" lambda=1e-3; "C" lambda=1e-3;')
    assert out["structure"] == "(A ∥ B) → (A ↺ ∥ C)"
    assert out["cut_sets"] == [["A", "B"], ["A", "C"]] and out["n_cut_sets"] == 2


def test_a_bridge_has_no_one_line_structure():
    nodes = [{"id": "input", "type": "input"}, *[{"id": x, "type": "component", "label": x} for x in "ABCDE"],
             {"id": "output", "type": "output"}]
    wires = ["input A", "input B", "A C", "B D", "A E", "E D", "C output", "D output"]
    graph = normalize_graph({"nodes": nodes, "edges": [dict(zip(("source", "target"), w.split())) for w in wires]})
    assert structure.describe(graph) == {"structure": None, "cut_sets": None, "n_cut_sets": None}
