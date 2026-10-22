"""A non-repairable model's data in words (#303): how many units failed and how many
were still running, so a saved model's panel says "5 failed, 7 running" as
a fresh fit does, not "12 observations".

The counts are read off the same fit inputs SurPyval is given (censor flag 0
= failed, 1 = still running, anything else another kind of censoring),
weighted by the count column. A fit records them as ``split``; a model saved
before that gets them from its dataset when it's opened (kept in memory).
Interval data (``xl``/``xr``) has no simple split, so none is given.
"""

from __future__ import annotations

from collections import OrderedDict

import numpy as np

#: The kinds whose panel shows the data (plain, non-parametric, flexible).
SPLIT_KINDS = ("distribution", "nonparametric", "flexible", "discrete")

_CACHE: OrderedDict = OrderedDict()
_CACHE_MAX = 2048


def split_of_inputs(kwargs: dict) -> dict | None:
    """{failed, running, other} from built fit inputs, or None when the data
    aren't plain times with a censor flag."""
    x = kwargs.get("x")
    if x is None or kwargs.get("xl") is not None or kwargs.get("xr") is not None:
        return None
    x = np.asarray(x, dtype=float)
    c = np.asarray(kwargs["c"], dtype=float) if kwargs.get("c") is not None else np.zeros_like(x)
    n = np.asarray(kwargs["n"], dtype=float) if kwargs.get("n") is not None else np.ones_like(x)
    keep = np.isfinite(x)
    if not (np.all(np.isfinite(c[keep])) and np.all(np.isfinite(n[keep]))):
        return None
    failed = float(n[keep & (c == 0)].sum())
    running = float(n[keep & (c == 1)].sum())
    other = float(n[keep].sum()) - failed - running
    return {"failed": int(round(failed)), "running": int(round(running)), "other": int(round(other))}


def data_split(df, mapping: dict) -> dict | None:
    """The split of a data frame under a (plain) column mapping, its censor
    column already read the right way round. Never raises."""
    from backend.fitting import build_fit_inputs  # local: fitting imports this module

    try:
        return split_of_inputs(build_fit_inputs(df, {k: v for k, v in (mapping or {}).items()
                                                     if k in ("x", "c", "n", "xl", "xr")}))
    except Exception:
        return None


def split_for_model(db, model) -> dict | None:
    """A saved model's split: the one its fit recorded, else counted from its
    dataset (with the censor column read as the fit read it)."""
    results = model.results or {}
    if results.get("split") is not None:
        return results["split"]
    if model.kind not in SPLIT_KINDS or not model.dataset_id:
        return None
    key = (model.id, str(model.updated_at))
    if key in _CACHE:
        return _CACHE[key]
    from backend import fitting
    from backend.services import datasets as datasets_service

    split = None
    try:
        spec = model.spec or {}
        mapping = spec.get("mapping") or {}
        dataset = datasets_service.get_dataset(db, model.dataset_id, owner_id=model.owner_id)
        if dataset is not None and not mapping.get("i"):
            df = datasets_service.load_dataframe(dataset)
            options = spec.get("options") or {}
            c_col = mapping.get("c")
            if c_col and options.get(fitting.CENSOR_MAP_KEY):
                df = fitting.map_censor_column(df, c_col, options[fitting.CENSOR_MAP_KEY])
            elif c_col and options.get(fitting.CENSOR_INVERT_KEY):
                df = fitting.invert_censor_column(df, c_col)
            split = data_split(df, mapping)
    except Exception:
        split = None
    _CACHE[key] = split
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return split
