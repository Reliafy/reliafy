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
