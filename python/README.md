# reliafy — push SurPyval models to Reliafy

Fit a model anywhere with [SurPyval](https://github.com/derrynknife/SurPyval),
then make it a shareable, trackable, citable artifact in
[Reliafy](https://reliafy.com) with one call. The notebook is the lab;
Reliafy is the plant.

```bash
pip install reliafy
```

## Quick start

```python
import surpyval as sp
import reliafy

# Fit however you like — censored data, offsets, whatever.
model = sp.Weibull.fit(x=failures, c=censoring_flags)

reliafy.configure(token="rlf_...")            # from Reliafy → API access (Pro)
url = reliafy.push(model, name="Pump bearings — 2026 refit", unit="hours")
print(url)                                    # open it in Reliafy
```

`push()` uploads the model **and its fitted data** by default, so Reliafy
shows the full probability plot with confidence bounds — and the model stays
editable and refittable in the app, and can be cited as RCM evidence, used in
RBD blocks, or tracked against a fleet.

Offset / limited-failure-population / zero-inflated fits are detected
automatically from the model and reproduced.

## Options

```python
# Parameters only (no data upload): functions & life metrics, no plot.
reliafy.push(model, name="From a report", data=False)

# No SurPyval object — just numbers:
reliafy.push_params("weibull", [1200.0, 2.3], name="Handbook value", unit="hours")

# Self-hosted instance:
reliafy.configure(token="rlf_...", base_url="https://reliafy.mycompany.com")
```

Configuration also reads `RELIAFY_TOKEN` and `RELIAFY_BASE_URL` from the
environment.

## Notes

- The token is a personal API token, created on the **API access** page in
  Reliafy. On Reliafy Cloud this is a Pro feature; self-hosted instances have
  it unconditionally.
- Supported distributions: Weibull, Exponential, Normal, LogNormal, Gamma,
  LogLogistic, Exponentiated Weibull, Gumbel, Logistic.
- Pure standard library — no dependencies. You bring SurPyval to do the fit.
