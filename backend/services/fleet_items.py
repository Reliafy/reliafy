"""A fleet's items from its model's own data: the units still running.

A life model's data holds the units that failed and the ones still running
(right-censored, ``c = 1``): those are the fleet in service, each at the age it
had reached. A repairable model's data holds every system's history: each
system is in service at the end of its record. ``running_units`` reads them as
forecast items, so a fleet doesn't have to be typed in again.

Ages are in the model's own unit, as the forecast takes them. A regression
model's units carry their covariate values from the same rows.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from backend.schema import Fleet
from backend.services import datasets as datasets_service
from backend.services import models as models_service
from backend.services import recurrent as recurrent_service

MAX_ITEMS = 500  # a fleet's limit (fleet._clean_items)

# A column that names each unit: "Unit", "Serial no", "Pump ID", "Asset tag".
_NAME_COLUMN = re.compile(
    r"^(id|ids|unit|units|unit[ _]?id|serial|serial[ _]?(no|num|number)|s/?n|name|asset|asset[ _]?(id|tag|no)|"
    r"item|item[ _]?id|tag|tag[ _]?no|equipment|equipment[ _]?id|pump|truck|machine|system|position)\b",
    re.I)


class NoModelData(ValueError):
    """The model has no data to read units from; the message says why."""


def _name_column(df: pd.DataFrame, used: set) -> str | None:
    """A column naming each unit, or None: one whose header says so and whose
    values are mostly distinct."""
    for col in df.columns:
        if col in used or not _NAME_COLUMN.match(str(col).strip()):
            continue
        values = df[col].dropna().astype(str).str.strip()
        if len(values) and values.nunique() >= 0.9 * len(values):
            return col
    return None


def _life_units(db, model, owners) -> dict:
    from backend import fitting, unit_column

    spec = model.spec or {}
    if spec.get("params_only") or not model.dataset_id:
        raise NoModelData("This model was built from parameters, so it has no units of its own to list.")
    options = {**(spec.get("options") or {}), **((model.results or {}).get("options") or {})}
    dataset = datasets_service.get_dataset(db, model.dataset_id, owner_id=model.owner_id)
    if dataset is None:
        raise NoModelData("This model's dataset is gone, so there are no units to list.")
    df = datasets_service.load_dataframe(dataset)
    mapping = {k: v for k, v in (spec.get("mapping") or {}).items() if v}
    time_col = mapping.get("x") or mapping.get("xl")
    if not time_col or time_col not in df.columns:
        raise NoModelData("This model's data has no time column to read ages from.")
    if mapping.get("i"):
        raise NoModelData("This model's covariates change over time, so its rows aren't one unit each.")
    if options.get(unit_column.UNIT_COLUMN_KEY):
        try:
            df, _ = unit_column.convert(df, mapping, str(options[unit_column.UNIT_COLUMN_KEY]), spec.get("unit"))
        except ValueError as exc:
            raise NoModelData(str(exc)) from None
    c_col = mapping.get("c")
    if not c_col or c_col not in df.columns:
        return {"items": [], "running": 0, "skipped": [],
                "reason": "This model's data has no censoring column: every unit in it failed, so none is "
                          "still running."}
    if options.get(fitting.CENSOR_MAP_KEY):
        df = fitting.map_censor_column(df, c_col, options[fitting.CENSOR_MAP_KEY])
    elif options.get(fitting.CENSOR_INVERT_KEY):
        df = fitting.invert_censor_column(df, c_col)
    c = pd.to_numeric(df[c_col], errors="coerce")
    x = pd.to_numeric(df[time_col], errors="coerce")
    n = pd.to_numeric(df[mapping["n"]], errors="coerce").fillna(1) if mapping.get("n") in df.columns else None
    running = (c == 1)
    name_col = _name_column(df, set(mapping.values()))
    covariate_cols = []
    if (model.results or {}).get("kind") == "regression":
        try:
            entry = models_service.get_live_model(db, model.id, owners) or {}
        except Exception:  # noqa: BLE001 - dataset gone or refit failed: no covariates
            entry = {}
        covariate_cols = [f["name"] for f in entry.get("fields") or [] if f.get("name") in df.columns]
    items, skipped = [], []
    for row in np.flatnonzero(running.to_numpy()):
        label = f"Row {row + 2}"  # the spreadsheet's row: the header is row 1
        age = x.iloc[row]
        if not np.isfinite(age) or age < 0:
            skipped.append(f"{label}: the time isn't a number of at least 0.")
            continue
        count = int(n.iloc[row]) if n is not None and np.isfinite(n.iloc[row]) and n.iloc[row] >= 1 else 1
        base = str(df[name_col].iloc[row]).strip() if name_col else ""
        base = base or f"Unit {row + 2}"
        covariates = {}
        for col in covariate_cols:
            value = df[col].iloc[row]
            if pd.isna(value):
                continue
            covariates[col] = float(value) if isinstance(value, (int, float, np.number)) else str(value)
        for k in range(count):
            item = {"name": base if count == 1 else f"{base} ({k + 1} of {count})", "current_use": float(age)}
            if covariates:
                item["covariates"] = covariates
            items.append(item)
    return {"items": items, "running": len(items), "skipped": skipped,
            "name_column": name_col, "time_column": time_col}


def _recurrent_units(db, doc) -> dict:
    from backend import recurrent as recurrent_fit
    from backend.fitting import FitError

    spec = doc.spec or {}
    if spec.get("params_only") or not doc.dataset_id:
        raise NoModelData("This model was built from parameters, so it has no systems of its own to list.")
    dataset = datasets_service.get_dataset(db, doc.dataset_id, owner_id=doc.owner_id)
    if dataset is None:
        raise NoModelData("This model's dataset is gone, so there are no systems to list.")
    df = datasets_service.load_dataframe(dataset)
    try:
        inputs = recurrent_fit.build_inputs(df, spec.get("mapping") or {})
    except FitError as exc:
        raise NoModelData(str(exc)) from None
    ends = np.asarray(inputs["x"], dtype=float)
    if inputs.get("tr") is not None:
        ends = np.maximum(ends, np.asarray(inputs["tr"], dtype=float))
    last: dict[str, float] = {}
    for system, end in zip(inputs["i"], ends):
        key = str(system)
        last[key] = max(last.get(key, 0.0), float(end))
    items = [{"name": name, "current_use": age} for name, age in last.items()]
    return {"items": items, "running": len(items), "skipped": [], "time_column": (spec.get("mapping") or {}).get("x")}


def running_units(db, fleet: Fleet, owners) -> dict:
    """The units still running in the fleet's model's data, as forecast items:
    ``{items, running, skipped, unit, kind, truncated?, reason?}``. Raises
    :class:`NoModelData` when the model has no data to read."""
    kind = fleet.model_kind
    if kind == "alt":
        raise NoModelData("An ALT model's units ran at test stresses, not in service: add the fleet's items "
                          "with the stress each runs at.")
    if kind == "recurrent":
        doc = recurrent_service.get_model(db, fleet.model_id, owners)
        if doc is None:
            raise NoModelData("The linked repairable model no longer exists.")
        out = _recurrent_units(db, doc)
        unit = (doc.results or {}).get("unit", "")
        what = "systems"
    else:
        model = models_service.get_model(db, fleet.model_id, owners)
        if model is None:
            raise NoModelData("The linked non-repairable model no longer exists.")
        out = _life_units(db, model, owners)
        unit = (model.results or {}).get("unit", "")
        what = "running units"
    if len(out["items"]) > MAX_ITEMS:
        out["truncated"] = len(out["items"])
        out["items"] = out["items"][:MAX_ITEMS]
    return {**out, "unit": unit, "kind": "systems" if what == "systems" else "running"}
