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
from backend.schema import Dataset, DegradationModelDoc, Model, Rbd, TrackedItem

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

# Long-format degradation histories: 6 brake pads measured every 550 hours.
# Near-linear wear toward the 8 mm replacement threshold.
_BRAKE_WEAR_CSV = (
    "item,hours,wear_mm\n"
    "pad-01,500,1.16\npad-01,1050,1.96\npad-01,1600,2.53\npad-01,2150,3.37\n"
    "pad-01,2700,4.28\npad-01,3250,5.04\npad-01,3800,5.85\npad-01,4350,6.58\n"
    "pad-02,500,1.16\npad-02,1050,1.88\npad-02,1600,2.46\npad-02,2150,3.00\n"
    "pad-02,2700,3.73\npad-02,3250,4.26\npad-02,3800,5.05\npad-02,4350,5.61\n"
    "pad-03,500,1.15\npad-03,1050,1.83\npad-03,1600,2.60\npad-03,2150,3.39\n"
    "pad-03,2700,4.25\npad-03,3250,5.02\npad-03,3800,5.81\npad-03,4350,6.60\n"
    "pad-04,500,1.26\npad-04,1050,2.01\npad-04,1600,2.91\npad-04,2150,3.73\n"
    "pad-04,2700,4.42\npad-04,3250,5.14\npad-04,3800,5.92\npad-04,4350,6.82\n"
    "pad-05,500,1.04\npad-05,1050,1.84\npad-05,1600,2.41\npad-05,2150,3.14\n"
    "pad-05,2700,3.80\npad-05,3250,4.47\npad-05,3800,5.19\npad-05,4350,5.80\n"
    "pad-06,500,0.75\npad-06,1050,1.35\npad-06,1600,1.75\npad-06,2150,2.41\n"
    "pad-06,2700,2.97\npad-06,3250,3.53\npad-06,3800,4.13\npad-06,4350,4.85\n"
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
    {
        "id": "sample-ds-brake-wear",
        "name": "Brake pad wear (sample)",
        "csv": _BRAKE_WEAR_CSV,
    },
]

SAMPLE_DEGRADATION_MODELS = [
    {
        "id": "sample-deg-brake-wear",
        "name": "Brake pad wear — linear degradation (sample)",
        "dataset_id": "sample-ds-brake-wear",
        "spec": {
            "mapping": {"i": "item", "x": "hours", "y": "wear_mm"},
            "threshold": 8.0,
            "path": "linear",
            "distribution_id": "weibull",
            "population_method": "moments",
            "unit": "hours",
            "measurement_unit": "mm",
        },
    },
]

# Two monitored assets on the sample degradation model, so the fleet table has
# life the moment a user opens it. Measurements are literal (idempotent seed).
SAMPLE_TRACKED_ITEMS = [
    {
        "id": "sample-item-truck-07",
        "model_id": "sample-deg-brake-wear",
        "name": "Truck 07 — front left",
        "measurements": [
            {"t": 500.0, "y": 0.9},
            {"t": 1500.0, "y": 2.4},
            {"t": 2500.0, "y": 4.1},
        ],
    },
    {
        "id": "sample-item-truck-12",
        "model_id": "sample-deg-brake-wear",
        "name": "Truck 12 — front right",
        "measurements": [
            {"t": 800.0, "y": 1.1},
            {"t": 2000.0, "y": 2.6},
        ],
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
            existing = db.models.find_one({"_id": spec["id"]})
            if existing is not None:
                # Upgrade older seeds whose cached results predate newer payload
                # fields (parameter CIs / the randomness verdict).
                old_params = (existing.get("results") or {}).get("params") or []
                if old_params and "ci" in old_params[0]:
                    continue
            ds_doc = db.datasets.find_one({"_id": spec["dataset_id"]})
            if ds_doc is None:
                continue
            dataset = from_doc(Dataset, ds_doc)
            df = fitting.read_dataframe(bytes(dataset.data))
            result = fitting.fit(
                spec["distribution"], df, spec["mapping"], None, None, spec.get("unit")
            )
            if existing is not None:
                db.models.update_one(
                    {"_id": spec["id"]}, {"$set": {"results": result}}
                )
                logger.info("Upgraded sample model %r (param CIs).", spec["id"])
                continue
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

    _seed_strategy_analyses(db)
    _seed_rcm_study(db)
    _seed_fleet(db)

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

    for spec in SAMPLE_DEGRADATION_MODELS:
        try:
            from backend import degradation as degradation_fit  # local: heavy import

            model_exists = db.degradation_models.find_one({"_id": spec["id"]}) is not None

            def _needs_seed(it):
                doc = db.tracked_items.find_one({"_id": it["id"]})
                if doc is None:
                    return True
                # Upgrade older seeds whose cached prediction predates newer
                # payload fields (e.g. the credible band on the projection).
                proj = (doc.get("prediction") or {}).get("projection") or {}
                return bool(proj) and "lo" not in proj

            missing_items = [
                it for it in SAMPLE_TRACKED_ITEMS
                if it["model_id"] == spec["id"] and _needs_seed(it)
            ]
            if model_exists and not missing_items:
                continue

            ds_doc = db.datasets.find_one({"_id": spec["dataset_id"]})
            if ds_doc is None:
                continue
            dataset = from_doc(Dataset, ds_doc)
            df = fitting.read_dataframe(bytes(dataset.data))
            s = spec["spec"]
            payload, cache_id = degradation_fit.fit(
                df, s["mapping"], s["threshold"], s["path"],
                s["distribution_id"], s["population_method"],
                s["unit"], s["measurement_unit"],
            )
            if not model_exists:
                import surpyval

                doc = DegradationModelDoc(
                    id=spec["id"], name=spec["name"], owner_id=SAMPLE_OWNER,
                    dataset_id=spec["dataset_id"], spec=s, results=payload,
                    surpyval_version=getattr(surpyval, "__version__", None),
                    status="ready",
                )
                db.degradation_models.insert_one(to_doc(doc))
                logger.info("Seeded sample degradation model %r.", spec["id"])

            live = degradation_fit.get_live(cache_id)
            for it in missing_items:
                pred = degradation_fit.predict_item(
                    live, [m["t"] for m in it["measurements"]], [m["y"] for m in it["measurements"]]
                )
                item = TrackedItem(
                    id=it["id"], model_id=it["model_id"], name=it["name"],
                    owner_id=SAMPLE_OWNER, measurements=it["measurements"],
                    prediction=pred,
                )
                db.tracked_items.replace_one({"_id": it["id"]}, to_doc(item), upsert=True)
                logger.info("Seeded sample tracked item %r.", it["id"])
        except Exception as exc:  # pragma: no cover - defensive; never block boot
            logger.warning("Failed to seed sample degradation %r: %s", spec["id"], exc)


def _seed_rcm_study(db) -> None:
    """Sample RCM study wiring every sample artifact together as evidence.

    One decision — the legacy run-to-failure plan on the wheel bearings — is
    deliberately linked to a model that CONTRADICTS it (the bearing Weibull
    fits wear-out, β ≈ 2.5): the study opens with a red badge that demos the
    live evidence validation.
    """
    from backend.schema import RcmStudy

    if db.rcm_studies.find_one({"_id": "sample-rcm-truck"}) is not None:
        return
    try:
        functions = [
            {
                "id": "sample-rcm-f1",
                "text": "Stop the vehicle within the rated distance",
                "failures": [
                    {
                        "id": "sample-rcm-f1-ff1",
                        "text": "Insufficient braking force",
                        "modes": [
                            {
                                "id": "sample-rcm-m1",
                                "text": "Brake pad wear beyond the 8 mm limit",
                                "effects": "Extended stopping distance; risk of collision.",
                                "consequence": "safety",
                                "decision": {
                                    "outcome": "on_condition",
                                    "task": "Measure pad wear at each service; replace before the 8 mm threshold.",
                                    "evidence": {"type": "degradation_model", "id": "sample-deg-brake-wear"},
                                },
                            },
                            {
                                "id": "sample-rcm-m2",
                                "text": "Secondary hydraulic circuit failed (hidden until demanded)",
                                "effects": "No redundancy on primary circuit failure.",
                                "consequence": "hidden",
                                "decision": {
                                    "outcome": "failure_finding",
                                    "task": "Function-test the secondary circuit.",
                                    "evidence": {"type": "strategy_analysis", "id": "sample-strategy-ffi-brake-circuit"},
                                },
                            },
                        ],
                    },
                ],
            },
            {
                "id": "sample-rcm-f2",
                "text": "Transmit drive to the wheels",
                "failures": [
                    {
                        "id": "sample-rcm-f2-ff1",
                        "text": "Wheel does not rotate freely",
                        "modes": [
                            {
                                "id": "sample-rcm-m3",
                                "text": "Wheel-bearing fatigue",
                                "effects": "Vehicle immobilised; tow required.",
                                "consequence": "operational",
                                "decision": {
                                    "outcome": "fixed_interval",
                                    "task": "Replace wheel bearings preventively.",
                                    "interval": 580,
                                    "interval_unit": "hours",
                                    "evidence": {"type": "strategy_analysis", "id": "sample-strategy-bearing-replacement"},
                                },
                            },
                            {
                                "id": "sample-rcm-m4",
                                "text": "Wheel-bearing failure — legacy run-to-failure plan",
                                "effects": "As above; inherited from the old maintenance plan.",
                                "consequence": "operational",
                                "decision": {
                                    "outcome": "rtf",
                                    "rtf_basis": "random",
                                    "notes": "Legacy decision — kept to demonstrate live evidence validation.",
                                    "evidence": {"type": "model", "id": "sample-model-bearings-weibull"},
                                },
                            },
                            {
                                "id": "sample-rcm-m5",
                                "text": "Chassis cracking at the spring hanger",
                                "effects": "Structural risk under load.",
                                "consequence": "safety",
                                "decision": {
                                    "outcome": "redesign",
                                    "notes": "No task can manage the risk — reinforcement redesign raised with engineering.",
                                },
                            },
                        ],
                    },
                ],
            },
        ]
        from backend.services import rcm as rcm_service

        study = RcmStudy(
            id="sample-rcm-truck",
            name="Delivery truck — RCM demo (sample)",
            system="Delivery truck (brakes + drivetrain)",
            description=(
                "A worked RCM study with every decision linked to its evidence. "
                "Note the legacy run-to-failure decision flagged as CONTRADICTED — "
                "its own life model shows wear-out, not random failure."
            ),
            owner_id=SAMPLE_OWNER,
            functions=rcm_service.clean_tree(functions),
        )
        db.rcm_studies.insert_one(to_doc(study))
        logger.info("Seeded sample RCM study 'sample-rcm-truck'.")
    except Exception as exc:  # pragma: no cover - defensive; never block boot
        logger.warning("Failed to seed sample RCM study: %s", exc)


def _seed_strategy_analyses(db) -> None:
    """Sample saved strategy analyses (evidence for the sample RCM study).

    The bearing replacement analysis reads the just-seeded bearing model's
    fitted parameters, so this runs after the SAMPLE_MODELS loop.
    """
    from backend.schema import StrategyAnalysis
    from backend.services import strategy_store

    specs = []
    bearing = db.models.find_one({"_id": "sample-model-bearings-weibull"})
    if bearing is not None:
        params = [
            {"name": p["name"], "value": p["value"]}
            for p in (bearing.get("results") or {}).get("params", [])
        ]
        if params:
            specs.append({
                "id": "sample-strategy-bearing-replacement",
                "name": "Bearing preventive replacement (sample)",
                "kind": "optimal_replacement",
                "inputs": {
                    "distribution_id": "weibull",
                    "params": params,
                    "planned_cost": 200.0,
                    "unplanned_cost": 1500.0,
                    "unit": "hours",
                },
            })
    specs.append({
        "id": "sample-strategy-ffi-brake-circuit",
        "name": "Secondary brake circuit — failure finding (sample)",
        "kind": "failure_finding",
        "inputs": {
            "distribution_id": "exponential",
            "params": [{"name": "failure_rate", "value": 1.0 / 8760.0}],
            "target_availability": 0.99,
            "unit": "hours",
        },
    })

    for spec in specs:
        try:
            if db.strategy_analyses.find_one({"_id": spec["id"]}) is not None:
                continue
            results = strategy_store.compute(spec["kind"], spec["inputs"])
            doc = StrategyAnalysis(
                id=spec["id"], name=spec["name"], owner_id=SAMPLE_OWNER,
                kind=spec["kind"], inputs=spec["inputs"], results=results,
            )
            db.strategy_analyses.insert_one(to_doc(doc))
            logger.info("Seeded sample strategy analysis %r.", spec["id"])
        except Exception as exc:  # pragma: no cover - defensive; never block boot
            logger.warning("Failed to seed sample analysis %r: %s", spec["id"], exc)


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


def _seed_fleet(db) -> None:
    """Sample fleet forecast: eight trucks' wheel bearings against the sample
    bearing Weibull, staggered ages, 12 months at 500 operating hours/month.
    Demos the "how many failures next year?" question out of the box.
    """
    from backend.schema import Fleet

    if db.fleets.find_one({"_id": "sample-fleet-trucks"}) is not None:
        return
    try:
        if db.models.find_one({"_id": "sample-model-bearings-weibull"}) is None:
            return
        ages = [5200, 4100, 3600, 2900, 2400, 1800, 900, 350]
        fleet = Fleet(
            id="sample-fleet-trucks",
            name="Delivery trucks — bearing forecast (sample)",
            owner_id=SAMPLE_OWNER,
            model_id="sample-model-bearings-weibull",
            settings={"periods": 12, "period_label": "months",
                      "default_rate": 500.0, "method": "renewals"},
            items=[
                {"id": f"sample-fleet-truck-{i+1:02d}", "name": f"Truck {i+1:02d} — wheel bearing",
                 "current_use": float(a), "rate": None}
                for i, a in enumerate(ages)
            ],
        )
        db.fleets.insert_one(to_doc(fleet))
        logger.info("Seeded sample fleet 'sample-fleet-trucks'.")
    except Exception:  # pragma: no cover - seeding must never block boot
        logger.exception("Failed to seed the sample fleet")
