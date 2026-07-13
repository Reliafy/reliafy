"""reliafy — push SurPyval models to Reliafy.

Build a model in a notebook with SurPyval, then make it a shareable,
trackable, citable artifact in Reliafy with one call:

    import surpyval as sp
    import reliafy

    model = sp.Weibull.fit(x=my_data)

    reliafy.configure(token="rlf_...")           # from the API access page
    url = reliafy.push(model, name="Pump bearings")
    print(url)                                    # open it in the app

The token is a personal API token (Reliafy Cloud → API access; a Pro
feature). Self-hosted instances pass ``base_url`` to point at your server.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

__all__ = ["configure", "push", "push_params", "ReliafyError"]

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


def _post(payload: dict) -> dict:
    token = _config.get("token")
    if not token:
        raise ReliafyError(
            "No API token. Call reliafy.configure(token='rlf_...') or set "
            "RELIAFY_TOKEN. Create a token on the API access page (Pro)."
        )
    url = _config["base_url"].rstrip("/") + "/api/import/models"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail", exc.reason)
        except Exception:
            detail = exc.reason
        raise ReliafyError(f"Reliafy returned {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise ReliafyError(f"Couldn't reach Reliafy at {url}: {exc.reason}") from None
    return result


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
