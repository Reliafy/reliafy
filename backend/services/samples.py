"""Shared sample (starter) datasets and models.

A fresh account shouldn't open to an empty workspace. We seed a small set of
realistic reliability datasets and fitted models **once**, stored under the
synthetic owner :data:`backend.config.SAMPLE_OWNER`, and surface them to every
user alongside their own data. Nothing is copied per user.

"Deleting" a sample is per-user: the sample's id is recorded in that user's
``hidden_samples`` set (on their ``users`` document) so it disappears from *their*
lists only — the shared copy other users see is untouched. Samples are
read-only: they can't be renamed or really deleted, only hidden.

Seeding is idempotent (fixed ids; insert only when absent), so it's safe to run
on every startup and against either real Atlas or the in-memory simulator.
"""

from __future__ import annotations

import logging

from backend import config, fitting, storage
from backend.db import from_doc, to_doc
from backend.schema import Dataset, Model, Rbd

logger = logging.getLogger(__name__)

SAMPLE_OWNER = config.SAMPLE_OWNER


# ---------------------------------------------------------------------------
# Sample content. CSVs are tiny, embedded inline; ids are fixed & stable.
# ---------------------------------------------------------------------------

# Complete (uncensored) bench-test failure times — the textbook Weibull case.
_BEARINGS_CSV = (
    "hours\n"
    "312\n420\n506\n588\n655\n719\n773\n824\n889\n946\n998\n1051\n"
    "1104\n1158\n1203\n1259\n1312\n1366\n1421\n1485\n1542\n1607\n"
    "1683\n1764\n1842\n1925\n2014\n2118\n2233\n2401\n"
).encode()

# Field returns with right-censoring: units still running carry censored=1.
_PUMP_CSV = (
    "months,censored\n"
    "4,0\n7,0\n9,0\n11,0\n13,0\n15,0\n16,0\n18,0\n19,0\n21,0\n"
    "23,0\n24,0\n26,0\n28,0\n31,0\n34,0\n38,0\n43,0\n"
    "36,1\n36,1\n36,1\n36,1\n36,1\n36,1\n36,1\n"
).encode()

SAMPLE_DATASETS = [
    {
        "id": "sample-ds-bearings",
        "name": "Bearing fatigue test (sample)",
        "csv": _BEARINGS_CSV,
    },
    {
        "id": "sample-ds-pumps",
        "name": "Pump field returns (sample)",
        "csv": _PUMP_CSV,
    },
]

SAMPLE_MODELS = [
    {
        "id": "sample-model-bearings-weibull",
        "name": "Bearing life — Weibull (sample)",
        "dataset_id": "sample-ds-bearings",
        "distribution": "weibull",
        "mapping": {"x": "hours"},
        "unit": "hours",
    },
    {
        "id": "sample-model-bearings-lognormal",
        "name": "Bearing life — Lognormal (sample)",
        "dataset_id": "sample-ds-bearings",
        "distribution": "lognormal",
        "mapping": {"x": "hours"},
        "unit": "hours",
    },
    {
        "id": "sample-model-pumps-weibull",
        "name": "Pump life — Weibull, right-censored (sample)",
        "dataset_id": "sample-ds-pumps",
        "distribution": "weibull",
        "mapping": {"x": "months", "c": "censored"},
        "unit": "months",
    },
]


# A small but representative diagram: a controller in series with two redundant
# pumps in parallel (input -> controller -> {Pump A | Pump B} -> output). Each
# component carries an inline Weibull life model so the RBD is self-contained
# (it doesn't depend on any saved model). Shape matches what the React Flow
# builder produces, so it opens, analyses, and edits like any user diagram.
def _weibull(alpha: float, beta: float) -> dict:
    return {
        "source": "params",
        "distribution": "Weibull",
        "distribution_id": "weibull",
        "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}],
    }


def _pump_station_graph() -> dict:
    return {
        "nodes": [
            {"id": "input", "type": "input", "position": {"x": 0, "y": 120},
             "data": {"label": "Input"}},
            {"id": "controller", "type": "component", "position": {"x": 210, "y": 120},
             "data": {"label": "PLC controller", "model": _weibull(1500.0, 1.8)}},
            {"id": "pumpA", "type": "component", "position": {"x": 430, "y": 30},
             "data": {"label": "Pump A", "model": _weibull(900.0, 1.4)}},
            {"id": "pumpB", "type": "component", "position": {"x": 430, "y": 210},
             "data": {"label": "Pump B", "model": _weibull(900.0, 1.4)}},
            {"id": "output", "type": "output", "position": {"x": 650, "y": 120},
             "data": {"label": "Output"}},
        ],
        "edges": [
            {"id": "e-in-ctl", "source": "input", "target": "controller"},
            {"id": "e-ctl-a", "source": "controller", "target": "pumpA"},
            {"id": "e-ctl-b", "source": "controller", "target": "pumpB"},
            {"id": "e-a-out", "source": "pumpA", "target": "output"},
            {"id": "e-b-out", "source": "pumpB", "target": "output"},
        ],
    }


SAMPLE_RBDS = [
    {
        "id": "sample-rbd-pump-station",
        "name": "Pump station — 1 controller, 2 pumps (sample)",
        "graph": _pump_station_graph(),
    },
]


def is_sample(owner_id: str | None) -> bool:
    """True if a record belongs to the shared sample owner (read-only)."""
    return owner_id == SAMPLE_OWNER


# ---------------------------------------------------------------------------
# Seeding (idempotent)
# ---------------------------------------------------------------------------

def seed_samples(db) -> None:
    """Ensure the shared sample datasets and models exist. Safe to re-run.

    Never raises: a sample that fails to fit is logged and skipped so it can
    never block application startup.
    """
    if not config.SEED_SAMPLES:
        return

    for spec in SAMPLE_DATASETS:
        try:
            if db.datasets.find_one({"_id": spec["id"]}) is not None:
                continue
            df = fitting.read_dataframe(spec["csv"])
            columns = [{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns]
            dataset = Dataset(
                id=spec["id"],
                name=spec["name"],
                owner_id=SAMPLE_OWNER,
                checksum=storage.checksum(spec["csv"]),
                n_rows=int(df.shape[0]),
                columns=columns,
                data=spec["csv"],
            )
            db.datasets.insert_one(to_doc(dataset))
            logger.info("Seeded sample dataset %r.", spec["id"])
        except Exception as exc:  # pragma: no cover - defensive; never block boot
            logger.warning("Failed to seed sample dataset %r: %s", spec["id"], exc)

    import surpyval

    for spec in SAMPLE_MODELS:
        try:
            if db.models.find_one({"_id": spec["id"]}) is not None:
                continue
            ds_doc = db.datasets.find_one({"_id": spec["dataset_id"]})
            if ds_doc is None:
                continue
            dataset = from_doc(Dataset, ds_doc)
            df = fitting.read_dataframe(bytes(dataset.data))
            result = fitting.fit(
                spec["distribution"], df, spec["mapping"], None, None, spec.get("unit")
            )
            model = Model(
                id=spec["id"],
                name=spec["name"],
                owner_id=SAMPLE_OWNER,
                dataset_id=dataset.id,
                kind=result.get("kind", "distribution"),
                distribution_id=spec["distribution"],
                spec={
                    "distribution_id": spec["distribution"],
                    "mapping": {k: v for k, v in spec["mapping"].items() if v},
                    "covariates": [],
                    "formula": None,
                    "unit": spec.get("unit", ""),
                },
                results=result,
                surpyval_version=getattr(surpyval, "__version__", None),
                status="ready",
            )
            db.models.insert_one(to_doc(model))
            logger.info("Seeded sample model %r.", spec["id"])
        except Exception as exc:  # pragma: no cover - defensive; never block boot
            logger.warning("Failed to seed sample model %r: %s", spec["id"], exc)

    for spec in SAMPLE_RBDS:
        try:
            if db.rbds.find_one({"_id": spec["id"]}) is not None:
                continue
            rbd = Rbd(id=spec["id"], name=spec["name"], owner_id=SAMPLE_OWNER,
                      graph=spec["graph"])
            db.rbds.insert_one(to_doc(rbd))
            logger.info("Seeded sample RBD %r.", spec["id"])
        except Exception as exc:  # pragma: no cover - defensive; never block boot
            logger.warning("Failed to seed sample RBD %r: %s", spec["id"], exc)


# ---------------------------------------------------------------------------
# Per-user hiding ("delete" a sample for me only)
# ---------------------------------------------------------------------------

def hidden_sample_ids(db, uid: str) -> set[str]:
    """The sample ids this user has dismissed (empty set if none)."""
    doc = db.users.find_one({"_id": uid}) or {}
    return set(doc.get("hidden_samples") or [])


def hide_sample(db, uid: str, sample_id: str) -> None:
    """Hide a shared sample for one user without touching the shared copy."""
    db.users.update_one(
        {"_id": uid},
        {"$addToSet": {"hidden_samples": sample_id}},
        upsert=True,
    )
