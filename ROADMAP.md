# Reliafy roadmap

Reliafy's goal is to be the platform where failure data becomes maintenance
decisions — open source at the core, connected end to end, so that a meter
reading taken on a Tuesday can change a replacement interval by Wednesday.

This roadmap is organised by **horizon, not date**:

- **Now** — being built, or immediately next.
- **Next** — coming after that; shapes are known, order can change.
- **Later** — direction we're committed to, not yet scheduled.
- **Ideas** — plausible futures, unvalidated. Argue for them.

**How to influence it:** 👍 the [roadmap issues](https://github.com/Reliafy/reliafy/issues?q=is%3Aissue+is%3Aopen+label%3Aroadmap+sort%3Areactions-%2B1-desc)
you want, or open a new issue. Real usage beats this document: when users
tell us what hurts, items move. If you're evaluating Reliafy and something
here would decide it for you, say so in the issue — that's exactly the
signal that reorders the list.

---

## Now

**Automated data ingestion + alerts.** The flagship gap. A token-authed API
to push the data you already collect — fleet usage/meter readings,
degradation measurements, new lives/failures — followed by the loop it
unlocks: recompute on new data and email when something changes state
("Truck 12 → plan replacement", "expected failures next quarter rose
3.2 → 4.8"). Closing the loop from data source → prediction → inbox is
something desktop reliability tools structurally can't do.

- Personal API tokens
- Ingestion endpoints (fleet usage, measurements, lives) — JSON and CSV
- Health-transition and forecast-drift email alerts
- **Notebook → Reliafy model push**: fit with
  [SurPyval](https://github.com/derrynknife/SurPyval) anywhere (your AI
  assistant writes the notebook), then `reliafy.push(model)` to make it a
  shareable, trackable, citable artifact. The notebook is the lab; Reliafy
  is the plant.
- `curl`/Python examples in docs; a packaged CLI once the API settles

## Next

**Repairable systems.** Reliafy currently models non-repairable life. The
other half of the discipline: Crow-AMSAA / NHPP growth analysis, mean
cumulative function (MCF) for recurrent events, trend tests (is this fleet
degrading or improving?). This also makes MTBF honest for repairables.

**Public link for RBDs** — the one artifact type without a public read-only
view (needs a canvas renderer).

**Report view.** A print-friendly, single-link "report" composition of any
analysis (public links already carry the content; this adds layout — no
PDFs, the link *is* the report).

**Spares & maintenance economics deepening.** Stock-level recommendation on
top of fleet failure forecasts (service-level → how many spares to hold),
block replacement policies, inspection-interval optimisation for degrading
items.

**Onboarding & guidance.** Guided first-run walkthroughs per module, worked
sample narratives, empty states that teach.

## Later

### The model landscape

Reliafy's statistical core, [SurPyval](https://github.com/derrynknife/SurPyval),
organises survival models along orthogonal axes — **time scale**
(continuous durations vs discrete trials) × **recurrence** × **competing
events** × **covariates** × **estimation method**. Our destination for the
analysis engine is simple to state: **every cell of that table, surfaced in
the UI** with the same fit-plot-decide workflow the current models have.
The engine already implements more of the landscape than Reliafy exposes;
much of this horizon is UI, not statistics:

- **Covariates beyond PH** — AFT and proportional-odds families, CoxPH
- **Competing events** — cumulative incidence, Fine-Gray / cause-specific
  hazards regression
- **Recurrence** — Crow-AMSAA/NHPP and MCF (see *Next*), plus
  proportional-intensity regression and cause-specific MCF
- **Discrete time** — per-demand Bernoulli/Binomial models (protective
  devices, one-shot equipment), feeding failure-finding intervals
- **Estimation breadth** — Turnbull/Nelson-Aalen/Fleming-Harrington
  non-parametrics; probability-plotting, product-spacing, and
  method-of-moments estimation where MLE struggles
- **Distribution breadth** — the full catalogue (Exponentiated Weibull,
  Gumbel, Logistic, LogLogistic, Beta, Uniform) with 3-parameter offsets

### Beyond the table

**Accelerated life testing (ALT).** Arrhenius/Eyring/power-law stress
models — fit at test stress, extrapolate to use stress. Opens the
design/test-engineering audience.

**Richer degradation models.** Nonlinear paths (power, exponential,
logistic), random-effects/hierarchical fits across units, gamma-process
models; measurement-noise handling.

**Competing risks & mixtures.** Separate mixed failure modes statistically
(mixture Weibull), competing-risk fits when multiple modes race.

**FMEA/FMECA.** Structured failure-modes analysis that feeds the RCM module
(mode libraries, severity/occurrence/detection, criticality ranking) — with
the same live-evidence linking RCM has.

**System availability.** RBDs with repair distributions: steady-state and
time-dependent availability, spares-aware repair simulation.

**Bayesian fitting.** Priors from handbooks or expert judgement for
small-sample fleets; credible intervals throughout.

**CMMS integrations.** Import mappers/templates for the common exports
(SAP PM, Maximo, Fiix…) on top of the ingestion API. Webhooks outbound for
events (health transitions, contradicted decisions).

**Deeper collaboration.** Comments on artifacts, analysis version history,
RCM review workflows (sign-off, periodic-review reminders), org-level
workspaces. SSO when organisations ask.

**Assistant depth.** Explain-this-result, draft-the-report,
auto-map-my-CSV, "what changed since last month?" — the assistant as a
reliability engineer's analyst, not a chatbot.

## Ideas

**Deep survival models — learned RUL distributions from operating data.**
The moonshot. Once the ingestion API is streaming usage, duty, and
condition signals, train neural survival models that regress *full
survival distributions* on covariate histories — censoring-aware losses, a
distribution output head, so every prediction is a distribution of
remaining life with honest uncertainty, re-scored on a regular cadence as
data lands, feeding the same health badges and alerts as the statistical
models. The ingestion API is deliberately the first step of this: it
builds the training corpus. Where fleets are small, the classical models
remain the fallback — this augments the statistics, never replaces the
transparency.

- Warranty forecasting and returns analysis
- Stress–strength interference
- Common-cause failure and fault-tree views for RBDs
- Embeddable live charts (intranet dashboards)
- MCP server so users' AI agents can drive Reliafy
- Custom KPI dashboard across a whole workspace
- Condition-monitoring signal ingestion (vibration/oil trends as
  degradation measures)
- Dark mode
- Localisation

---

## Recently shipped

Evidence-linked RCM with live contradiction flagging · degradation tracking
with per-item RUL and credible intervals · fleet failure forecasting
(analytic + Monte Carlo renewals) · team workspaces and view-only sharing ·
public read-only share links (`/p/…`) · AI assistant with tool access to
every module · censored/truncated-data MLE fitting across Weibull,
Lognormal, Exponential, Gamma, Normal, and proportional-hazards models ·
reliability block diagrams with k-of-n, standby, importance measures, and
cut sets.

*(No dates on this document by design. It reorders as users teach us what
matters — that's a feature.)*
