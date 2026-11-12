"""Download as Python for a saved degradation model.

The script embeds the readings the model was fitted to (item, time, reading:
the rows the app kept, after reading the columns as numbers), makes the same
``DegradationAnalysis.fit`` call the app made (path shape, threshold, life
distribution, population method), then prints the page's numbers: the
path's population means, the life distribution's parameters, the mean life,
and B1/B5/B10/B50 with the 90% one-sided lower bound and the 90% two-sided
band, read off the reliability curve on the same 200-point grid the page
reads them from.
"""

from __future__ import annotations

import pandas as pd

from backend import degradation as degradation_fit
from backend.fitting import DISTRIBUTIONS, FitError
from backend.services import datasets as datasets_service
from backend.services import python_export as px
from backend.units import unit_in_text


def _dist_name(distribution_id: str) -> str:
    entry = DISTRIBUTIONS.get(distribution_id)
    if entry is None:
        raise FitError(f"This model's life distribution ('{distribution_id}') can't be exported.")
    name = getattr(entry["dist"], "name", None)
    import surpyval

    if not name or getattr(surpyval, name, None) is not entry["dist"]:
        raise FitError(f"This model's life distribution ({entry['name']}) can't be exported.")
    return name


def readings(db, doc) -> pd.DataFrame:
    """The rows the model was fitted to: ``item`` (text), ``time``, ``reading``."""
    dataset = datasets_service.get_dataset(db, doc.dataset_id, owner_id=doc.owner_id)
    if dataset is None:
        raise FitError("The data this model was fitted to has been deleted, so it can't be exported.")
    df = datasets_service.load_measurements(dataset)
    x, y, i = degradation_fit.build_inputs(df, (doc.spec or {}).get("mapping") or {})
    return pd.DataFrame({"item": i, "time": x, "reading": y})


def python_script(name: str, spec: dict, frame: pd.DataFrame) -> str:
    """The standalone script for a degradation model fitted with ``spec`` to ``frame``."""
    spec = spec or {}
    dist = _dist_name(spec.get("distribution_id", "weibull"))
    path = spec.get("path", "best") or "best"
    population = spec.get("population_method", "moments") or "moments"
    threshold = float(spec.get("threshold"))
    unit = unit_in_text(spec.get("unit") or "") or ""
    m_unit = (spec.get("measurement_unit") or "").strip()
    shown_unit = unit or "the model's time unit"
    head = px.header(
        name or "Degradation model",
        "a degradation model (readings that wear towards a failure threshold).",
        unit=shown_unit,
        notes=[
            "Each item's readings are fitted with the same path shape; where an item's "
            "path crosses the threshold is its failure time (a 'pseudo' failure time). A "
            f"{dist} life distribution is then fitted to those times, and the B-lives are "
            "read off its reliability curve.",
        ],
    )
    body = [
        "import io",
        "",
        "import numpy as np",
        "import pandas as pd",
        "import surpyval",
        "from surpyval.degradation import DegradationAnalysis",
        "",
        *px.PRINT_HELPERS,
        "",
        "",
        *px.comment("The readings the model was fitted to: one row per reading, with the item it "
                    f"belongs to, the time it was taken (in {shown_unit}) and the value read"
                    + (f" (in {m_unit})." if m_unit else ".")),
        *px.csv_block("READINGS", frame),
        "",
        'data = pd.read_csv(io.StringIO(READINGS), dtype={"item": str})',
        "",
        "# The same fit the app made.",
        "model = DegradationAnalysis.fit(",
        '    data["time"].to_numpy(dtype=float),',
        '    data["reading"].to_numpy(dtype=float),',
        '    data["item"].to_numpy(),',
        f"    threshold={px.num(threshold)},  # the reading at which an item has failed"
        + (f", in {m_unit}" if m_unit else ""),
        f"    path={path!r},  # the shape of each item's path" + ("; 'best' picks it by AICc" if path == "best" else ""),
        f"    distribution=surpyval.{dist},  # the life distribution fitted to the crossing times",
        f"    population_method={population!r},",
        ")",
        "",
        f'UNIT = {unit!r}',
        'print(f"Path shape: {model.path_model.name}")',
        "",
        "# The population's path: the mean of each path parameter over the items.",
        'names = list(getattr(model.path_model, "parameter_names", [])) or [f"p{k + 1}" for k in range('
        "len(model.path_param_mean))]",
        "for pname, value in zip(names, np.asarray(model.path_param_mean, dtype=float)):",
        '    print_value(f"Path {pname}", value)',
        'print_value("Measurement variance", model.measurement_var)',
        "",
        "# The life distribution fitted to the times each item reaches the threshold.",
        "life = model.life_model",
        "for pname, value in zip(life.dist.parameter_names, np.atleast_1d(life.params)):",
        '    print_value(f"Life {pname}", value)',
        'print_value("Mean life", life.mean(), UNIT)',
        "",
        "# The population's reliability on the page's grid (0 to the time 99% have failed),",
        "# with its 90% two-sided band and its 90% one-sided lower bound.",
        "grid = np.linspace(0.0, float(life.qf(0.99)), 200)",
        "sf = np.asarray(model.sf(grid), dtype=float)",
        'band = np.asarray(model.cb(grid, on="sf", alpha_ci=0.10, bound="two-sided"), dtype=float)',
        'one_sided = np.asarray(model.cb(grid, on="sf", alpha_ci=0.10, bound="lower"), dtype=float).ravel()',
        "",
        "",
        "def steady(bound, lower):",
        '    """A bound with its rounding noise near R = 1 taken out, never rising with time."""',
        "    b = np.asarray(bound, dtype=float).copy()",
        "    flat = np.isfinite(sf) & (1.0 - sf < 1e-9)",
        "    b[flat] = sf[flat]",
        "    return np.fmax.accumulate(b[::-1])[::-1] if lower else np.fmin.accumulate(b)",
        "",
        "",
        "def time_at(curve, target):",
        '    """When ``curve`` first falls to ``target``, by straight lines between grid points."""',
        "    for k in range(1, len(grid)):",
        "        a, b = curve[k - 1], curve[k]",
        "        if not (np.isfinite(a) and np.isfinite(b)):",
        "            continue",
        "        if a >= target >= b:",
        "            f = 0.0 if a == b else (a - target) / (a - b)",
        "            return grid[k - 1] + f * (grid[k] - grid[k - 1])",
        "    return None",
        "",
        "",
        "band_lower, band_upper = steady(band[:, 0], True), steady(band[:, 1], False)",
        "life_lower = steady(one_sided, True)",
        "# A B-life: the time by which that share has reached the threshold.",
        "# Its lower bound is the cautious figure to plan with (90% one-sided).",
        'for label, share in (("B1", 0.01), ("B5", 0.05), ("B10", 0.10), ("B50", 0.50)):',
        "    value = time_at(sf, 1 - share)",
        '    print_bound(label, value, time_at(life_lower, 1 - share), "lower", UNIT)',
        '    print_interval(f"{label} band", value, time_at(band_lower, 1 - share), time_at(band_upper, 1 - share),'
        " UNIT)",
    ]
    return px.assemble(head, body)


def export_python(db, model, owners) -> tuple[str, str]:
    """``(filename, source)`` for a saved degradation model. ``owners`` is
    kept for the shared export signature (the data is read in the model's
    own scope, as its refit does)."""
    frame = readings(db, model)
    return px.filename(model.name, "degradation_model"), python_script(model.name, model.spec or {}, frame)
