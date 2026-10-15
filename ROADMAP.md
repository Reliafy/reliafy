# Reliafy roadmap

Reliafy's goal is to be the place where failure data becomes maintenance
decisions: open source at the core (SurPyval, RePyability), connected end to
end, so that a reading taken on a Tuesday can change a replacement interval by
Wednesday.

The roadmap is organised by **horizon, not date**:

- **Now**: being built this week or next.
- **Next**: after that, **in order**. The order can change.
- **Later**: a direction we're committed to, not yet scheduled.
- **Ideas**: plausible, unvalidated. Argue for them.

**How to influence it:** 👍 the [roadmap issues](https://github.com/Reliafy/reliafy/issues?q=is%3Aissue+is%3Aopen+label%3Aroadmap+sort%3Areactions-%2B1-desc)
you want, or open a new issue. Real usage beats this document. If something
here would decide whether you use Reliafy, say so in the issue: that is the
signal that reorders the list.

_Last updated 15 October 2026._

---

## What Reliafy does today

- **Life data:** fit 20+ distributions to failures and suspensions (right,
  left and interval censoring, truncation), mixtures, accelerated life tests,
  regression with covariates, degradation paths with per-item remaining life,
  and repairable systems (Crow-AMSAA, MCF, trend tests, optimal overhaul).
- **Reliability block diagrams:** reliability, MTTF, B-lives and importance;
  availability by simulation with repair crews and standby; k-of-n and
  standby groups; safety functions (PFDavg, SIL); import from BlockSim,
  Open-PSA, Galileo and Excel; download any diagram as a Python script.
- **Strategy:** optimal replacement, failure-finding intervals, fleet failure
  forecasts with email alerts, and evidence-linked RCM studies.
- **Maintenance (early access):** a register of positions, locations and
  items; plans, work orders, measurement points and spares; life data from the
  history, class models, and interval proposals you accept or reject.
- **Agents:** the Reliafy connector (MCP) lets Claude and other agents fit,
  analyse and run maintenance on your data; an ingestion API feeds usage,
  readings and new lives in.
- **Sharing:** public links to any analysis, team workspaces.

## Now

**Release safety.** Browser smoke tests on every release, so a page that
fails to load never goes live.
([#123](https://github.com/Reliafy/reliafy/issues/123))

**Writing.** The November What's new, tutorials and technical posts on the
[content calendar](https://github.com/Reliafy/reliafy/issues/343).

## Next (in order)

1. **Recommendations from combinations of context.** An outdoor pump on
   seawater needs checks that neither "pump" nor "outdoor" implies alone.
   Rules match the register and propose failure modes, tasks and parts; the
   data then tests whether a combination really changes life.
   ([#421](https://github.com/Reliafy/reliafy/issues/421))
2. **Failure forecasts from the register.** Expected failures per position
   class, the positions most at risk, then the spares and budget to hold
   against them.
   ([#407](https://github.com/Reliafy/reliafy/issues/407),
   [#31](https://github.com/Reliafy/reliafy/issues/31))
3. **A leaner connector.** Smaller tool definitions, so agents spend less of
   their context on Reliafy's tools.
   ([#410](https://github.com/Reliafy/reliafy/issues/410))
4. **A Claude plugin** and a listing in the connector directory.
   ([#415](https://github.com/Reliafy/reliafy/issues/415))
5. **Intervals for rotables and alerts.** Task intervals that follow an
   item's life since overhaul; alerts when health, RCM evidence or maintenance
   state changes, with preferences.
   ([#409](https://github.com/Reliafy/reliafy/issues/409),
   [#26](https://github.com/Reliafy/reliafy/issues/26))
6. **Connecting other systems and money.** CMMS import mappings and outbound
   webhooks; optimal replacement in business terms; guided fleet set-up.
   ([#39](https://github.com/Reliafy/reliafy/issues/39),
   [#296](https://github.com/Reliafy/reliafy/issues/296),
   [#297](https://github.com/Reliafy/reliafy/issues/297))

## Later

Each theme has a tracking issue listing everything in it.

**Maintenance and RCM** ([#283](https://github.com/Reliafy/reliafy/issues/283)):
FMEA / FMECA scoring and failure-mode libraries (#36); event-driven checks
after over-temperature, storms or hard landings (#422); condition-based risk
from joint models of readings and failures (#388); meter reading quality
(#413); position class templates (#412); an offline work-order app (#419);
Maintenance for every account (#418).

**Forecasts, spares and strategy** ([#416](https://github.com/Reliafy/reliafy/issues/416)):
calendar-allowed replacement intervals (#320), a capital renewal plan from
life models (#408), group comparisons saved as strategy analyses (#201).

**Modelling** ([#279](https://github.com/Reliafy/reliafy/issues/279)):
Gamma and Wiener degradation processes (#178), Bayesian fitting with priors
(#38), accelerated degradation tests (#69), copulas and survival forests
(#180).

**Reliability data library** ([#115](https://github.com/Reliafy/reliafy/issues/115)):
cited, licence-clean failure-rate records with pages, an API and agent search
(#116, #117); publishing models, diagrams and datasets to share (#120, #121).

**Connector and integrations** ([#143](https://github.com/Reliafy/reliafy/issues/143)):
redundancy design within a budget (#141), degradation tools (#137), a
versioned RBD spec with a validator (#108), fleets and team workspaces over
the connector (#138, #140), a command-line client (#42).

**Platform** ([#285](https://github.com/Reliafy/reliafy/issues/285)):
comments, version history and RCM sign-off reminders (#40).

## Ideas

- Agents querying their own maintenance graph directly, as a paid add-on
  ([#423](https://github.com/Reliafy/reliafy/issues/423))
- Upload pages an agent creates, so you can send it a file
  ([#420](https://github.com/Reliafy/reliafy/issues/420))
- Deep survival models: learned remaining-life distributions from operating
  data ([#49](https://github.com/Reliafy/reliafy/issues/49))
- Bring-your-own models ([#56](https://github.com/Reliafy/reliafy/issues/56))
