"""Export the model catalogue for the public reference pages.

Everything the reference can derive from code — ids, display names, parameter
names, bounds, support, which modifiers apply — is generated here rather than
written by hand, so adding a distribution can't silently leave the reference
stale. The human half (what it models, when to use it, the functional form)
lives in ``frontend/src/content/reference/*.md``, keyed by the same ids.

    python -m backend.scripts.export_reference          # write the JSON
    python -m backend.scripts.export_reference --check   # CI: fail if stale

``test_reference.py`` runs --check and also asserts every id has prose.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

OUT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "content" / "reference" / "catalogue.json"
)


def _num(v):
    """JSON-safe bound: infinities become null."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isinf(f) or math.isnan(f) else f


def _params(dist) -> list:
    names = list(getattr(dist, "param_names", []) or [])
    bounds = list(getattr(dist, "bounds", []) or [])
    out = []
    for i, name in enumerate(names):
        lo, hi = (bounds[i] if i < len(bounds) else (None, None))
        out.append({"name": name, "min": _num(lo), "max": _num(hi)})
    return out


def _support(dist) -> dict | None:
    s = getattr(dist, "support", None)
    if not s:
        return None
    return {"min": _num(s[0]), "max": _num(s[1])}


def build() -> dict:
    from backend import alt, fitting, recurrent

    families = []

    families.append({
        "id": "distributions",
        "title": "Life distributions",
        "blurb": "Continuous distributions for time to a single failure.",
        "entries": [
            {
                "id": eid,
                "name": e["name"],
                "params": _params(e["dist"]),
                "support": _support(e["dist"]),
                "offsetable": bool(e.get("offsetable")),
                "probability_plot": True,
            }
            for eid, e in fitting.DISTRIBUTIONS.items()
        ],
    })

    families.append({
        "id": "discrete",
        "title": "Discrete distributions",
        "blurb": "For life measured in whole counts — cycles, shocks, or demands.",
        "entries": [
            {
                "id": eid,
                "name": e["name"],
                "params": _params(e["dist"]),
                "support": _support(e["dist"]),
                "offsetable": False,
                # No probability paper: discrete distributions have no mpp transforms.
                "probability_plot": False,
            }
            for eid, e in fitting.DISCRETE.items()
        ],
    })

    families.append({
        "id": "nonparametric",
        "title": "Non-parametric estimators",
        "blurb": "Empirical survival estimates that assume no distribution.",
        "entries": [
            {"id": eid, "name": e["name"], "params": [], "support": None,
             "offsetable": False, "probability_plot": False}
            for eid, e in fitting.NONPARAMETRIC.items()
        ],
    })

    families.append({
        "id": "regression",
        "title": "Regression models",
        "blurb": "Life as a function of covariates — how conditions change reliability.",
        "entries": [
            {
                "id": eid,
                "name": e["name"],
                "effect": e.get("effect"),
                "ratio_label": fitting._RATIO_LABELS.get(e.get("effect")),
                "params": [],
                "support": None,
                "requires_covariates": True,
            }
            for eid, e in fitting.REGRESSION_MODELS.items()
        ],
    })

    families.append({
        "id": "accelerated-life",
        "title": "Life-stress relationships",
        "blurb": "How characteristic life responds to stress, for accelerated tests.",
        "entries": [
            {
                "id": eid,
                "name": e["name"],
                "n_stress": e["n_stress"],
                "log_life_axis": bool(e["log_y"]),
                "summary": e["desc"],
                "coefficients": sorted(
                    (getattr(e["model"], "phi_param_map", {}) or {}),
                    key=lambda k: (getattr(e["model"], "phi_param_map", {}) or {})[k],
                ),
            }
            for eid, e in alt.LIFE_MODELS.items()
        ],
    })

    families.append({
        "id": "recurrent",
        "title": "Recurrent-event models",
        "blurb": "Repairable systems — how often a fleet fails, and whether it's improving.",
        "entries": [
            {"id": eid, "name": e["name"]} for eid, e in recurrent.MODELS.items()
        ],
    })

    # Fit modifiers apply across the parametric families.
    modifiers = [
        {"id": "offset", "name": "Offset (3-parameter)",
         "applies_to": "Distributions marked offsetable"},
        {"id": "lfp", "name": "Limited failure population",
         "applies_to": "Plain distributions"},
        {"id": "zi", "name": "Zero-inflation",
         "applies_to": "Plain distributions"},
        {"id": "fixed", "name": "Fixed parameters",
         "applies_to": "Any parametric fit"},
    ]

    total = sum(len(f["entries"]) for f in families)
    return {"families": families, "modifiers": modifiers, "total": total}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the committed JSON is stale")
    args = ap.parse_args()

    data = build()
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    if args.check:
        if not OUT.exists():
            print(f"{OUT} is missing — run: python -m backend.scripts.export_reference")
            return 1
        if OUT.read_text() != text:
            print(f"{OUT} is out of date — run: python -m backend.scripts.export_reference")
            return 1
        print(f"reference catalogue is current ({data['total']} entries)")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(f"wrote {OUT} ({data['total']} entries across {len(data['families'])} families)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
