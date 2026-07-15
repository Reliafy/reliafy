"""reliafy — the programmatic client for Reliafy.

Grouped by area:

    import surpyval as sp
    import reliafy

    reliafy.configure(token="rlf_...")           # from Settings -> API access

    # models
    model = sp.Weibull.fit(x=my_data)
    url = reliafy.models.push(model, name="Pump bearings", unit="hours")
    reliafy.models.list()
    reliafy.models.reliability(model_id, t=1000)

    # data
    ds = reliafy.data.upload("Bearings", csv="hours,failed\\n120,1\\n340,0")
    reliafy.models.fit(ds["id"], "weibull", "Bearing life",
                       mapping={"x": "hours", "c": "failed"})

    # strategy / fleet
    reliafy.strategy.optimal_replacement("weibull", [1435, 2.5],
                                         planned_cost=200, unplanned_cost=1500)
    reliafy.fleet.forecast(fleet_id)

``configure`` / ``push`` / ``push_params`` are also available top-level for
backward compatibility. The token is a personal API token (Reliafy Cloud ->
API access; a Pro feature); self-hosted instances pass ``base_url``.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

__all__ = [
    "configure", "push", "push_params",
    "models", "data", "strategy", "fleet",
    "ReliafyError",
]

_DEFAULT_BASE = "https://reliafy.com"

# SurPyval distribution name -> Reliafy id (the server also resolves these,
# but mapping here gives a clear error before the network call).
_DIST_MAP = {
    "Weibull": "weibull",
    "Exponential": "exponential",
    "Normal": "normal",
    "LogNormal": "lognormal",
    "Gamma": "gamma",
    "LogLogistic": "loglogistic",
    "ExpoWeibull": "expo_weibull",
    "Gumbel": "gumbel",
    "Logistic": "logistic",
}

_config = {
    "token": os.environ.get("RELIAFY_TOKEN"),
    "base_url": os.environ.get("RELIAFY_BASE_URL", _DEFAULT_BASE),
}


class ReliafyError(RuntimeError):
    pass


def configure(token: str | None = None, base_url: str | None = None) -> None:
    """Set the API token and (optionally) the base URL for later calls.

    Both also read from ``RELIAFY_TOKEN`` / ``RELIAFY_BASE_URL`` in the
    environment.
    """
    if token is not None:
        _config["token"] = token
    if base_url is not None:
        _config["base_url"] = base_url.rstrip("/")


def _dist_name(model) -> str:
    dist = getattr(model, "dist", None)
    name = getattr(dist, "name", None) or type(dist).__name__.rstrip("_")
    if name not in _DIST_MAP:
        raise ReliafyError(
            f"Distribution {name!r} isn't supported by Reliafy import. "
            f"Supported: {', '.join(sorted(_DIST_MAP))}."
        )
    return _DIST_MAP[name]


def _extract(model, include_data: bool):
    """Pull distribution, params, data, and extras off a fitted SurPyval model."""
    body = {
        "distribution": _dist_name(model),
        "params": [{"value": float(v)} for v in list(model.params)],
    }
    extras = {}
    for attr, default in (("gamma", 0.0), ("p", 1.0), ("f0", 0.0)):
        val = getattr(model, attr, None)
        if val is not None and float(val) != default:
            extras[attr] = float(val)
    if extras:
        body["extras"] = extras
        # Also flag the equivalent options so a data-backed refit reproduces them.
        body["options"] = {
            "offset": "gamma" in extras, "lfp": "p" in extras, "zi": "f0" in extras,
        }

    data = getattr(model, "data", None)
    if include_data and data is not None and data.get("x") is not None:
        out = {"x": [float(v) for v in data["x"]]}
        c = data.get("c")
        if c is not None and any(int(v) != 0 for v in c):
            out["c"] = [int(v) for v in c]
        n = data.get("n")
        if n is not None and any(int(v) != 1 for v in n):
            out["n"] = [int(v) for v in n]
        body["data"] = out
    return body


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    """Call the Reliafy API with the configured token. Pure standard library."""
    token = _config.get("token")
    if not token:
        raise ReliafyError(
            "No API token. Call reliafy.configure(token='rlf_...') or set "
            "RELIAFY_TOKEN. Create a token on the API access page (Pro)."
        )
    url = _config["base_url"].rstrip("/") + path
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail", exc.reason)
        except Exception:
            detail = exc.reason
        raise ReliafyError(f"Reliafy returned {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise ReliafyError(f"Couldn't reach Reliafy at {url}: {exc.reason}") from None


def _post(payload: dict) -> dict:
    return _request("POST", "/api/import/models", payload)


def push(model, name: str, *, data: bool = True, unit: str | None = None) -> str:
    """Push a fitted SurPyval model to Reliafy; return the URL to open it.

    ``data=True`` (default) uploads the model's fitted observations too, so
    Reliafy shows the full probability plot and the model stays editable and
    refittable. ``data=False`` uploads parameters only.
    """
    if not name or not str(name).strip():
        raise ReliafyError("A name is required.")
    body = _extract(model, include_data=data)
    body["name"] = str(name).strip()
    if unit:
        body["unit"] = unit
    result = _post(body)
    return _config["base_url"].rstrip("/") + result["url"]


def push_params(distribution: str, params, name: str, *, unit: str | None = None,
                extras: dict | None = None) -> str:
    """Push a model by distribution + parameter values (no SurPyval object).

    ``params`` is a sequence of numbers in the distribution's natural order,
    or a list of ``{"name": ..., "value": ...}`` dicts. ``extras`` may hold
    ``gamma``/``p``/``f0`` for offset/LFP/zero-inflated models.
    """
    norm = []
    for p in params:
        if isinstance(p, dict):
            norm.append({"value": float(p["value"]), **({"name": p["name"]} if "name" in p else {})})
        else:
            norm.append({"value": float(p)})
    body = {"name": str(name).strip(), "distribution": distribution, "params": norm}
    if unit:
        body["unit"] = unit
    if extras:
        body["extras"] = {k: float(v) for k, v in extras.items()}
    result = _post(body)
    return _config["base_url"].rstrip("/") + result["url"]


# ---- read models & reliability --------------------------------------------

def list_models() -> list:
    """Your saved models: ``[{id, name, distribution, kind, n, unit, url}, …]``."""
    return _request("GET", "/api/v1/models").get("models", [])


def get_model(model_id: str) -> dict:
    """One model's fit: parameters (with CIs), life metrics, goodness-of-fit."""
    return _request("GET", f"/api/v1/models/{model_id}")


def reliability(model_id: str, t=None, covariates: dict | None = None) -> dict:
    """Evaluate a model's reliability functions.

    With ``t`` you get R/F/hazard/etc. at that time (under ``"at"``); without
    it, the whole function grid (under ``"curves"``). ``covariates`` targets a
    proportional-hazards model at a given combination.
    """
    body = {}
    if t is not None:
        body["t"] = t
    if covariates:
        body["covariates"] = covariates
    return _request("POST", f"/api/v1/models/{model_id}/reliability", body)


# ---- datasets & fitting ----------------------------------------------------

def upload_dataset(name: str, *, csv: str | None = None, data: dict | None = None) -> dict:
    """Create a dataset from CSV text (``csv=``) or column arrays (``data=``)."""
    body = {"name": name}
    if csv is not None:
        body["csv"] = csv
    elif data is not None:
        body["data"] = data
    else:
        raise ReliafyError("Provide csv= text or data= arrays.")
    return _request("POST", "/api/v1/datasets", body)


def fit(dataset_id: str, distribution: str, name: str, *, mapping: dict | None = None,
        unit: str | None = None, covariates=None, formula: str | None = None) -> dict:
    """Fit and save a model from one of your datasets. Returns the model.

    ``mapping`` maps roles to columns, e.g. ``{"x": "hours", "c": "failed"}``.
    """
    body = {"name": name, "dataset_id": dataset_id, "distribution": distribution,
            "mapping": mapping or {}}
    if unit:
        body["unit"] = unit
    if covariates:
        body["covariates"] = covariates
    if formula:
        body["formula"] = formula
    return _request("POST", "/api/v1/fit", body)


# ---- fleet & strategy ------------------------------------------------------

def fleet_forecast(fleet_id: str) -> dict:
    """The live failure forecast for one of your fleets."""
    return _request("GET", f"/api/v1/fleets/{fleet_id}/forecast")


def optimal_replacement(distribution: str, params, planned_cost: float,
                        unplanned_cost: float, *, unit: str | None = None) -> dict:
    """Cost-optimal preventive-replacement interval from a distribution + params."""
    return _request("POST", "/api/v1/strategy/optimal-replacement", {
        "distribution_id": distribution, "params": list(params),
        "planned_cost": planned_cost, "unplanned_cost": unplanned_cost, "unit": unit,
    })


def failure_finding(distribution: str, params, target_availability: float,
                    *, unit: str | None = None) -> dict:
    """Failure-finding inspection interval for a hidden (protective) function."""
    return _request("POST", "/api/v1/strategy/failure-finding", {
        "distribution_id": distribution, "params": list(params),
        "target_availability": target_availability, "unit": unit,
    })


# ---- namespaces ------------------------------------------------------------
# Grouped access: reliafy.models.* / reliafy.data.* / reliafy.strategy.* /
# reliafy.fleet.*. (configure / push / push_params also stay top-level.)

class _Namespace:
    def __init__(self, name, **members):
        self._name = name
        self.__dict__.update(members)

    def __repr__(self):
        fns = ", ".join(k for k in self.__dict__ if not k.startswith("_"))
        return f"<reliafy.{self._name}: {fns}>"


models = _Namespace(
    "models",
    push=push,
    push_params=push_params,
    list=list_models,
    get=get_model,
    reliability=reliability,
    fit=fit,
)
data = _Namespace("data", upload=upload_dataset)
strategy = _Namespace(
    "strategy",
    optimal_replacement=optimal_replacement,
    failure_finding=failure_finding,
)
fleet = _Namespace("fleet", forecast=fleet_forecast)
