"""The how-tos an AI agent reads about Reliafy's core tools, one topic at a
time (the ``guide`` tool), so the server's instructions stay a short
orientation and each tool's description stays about its actions. Reliafy
Maintenance has its own (backend/maintenance/mcp_guide.py)."""

TOPICS: dict[str, tuple[str, str]] = {
    "life_data": ("Censoring, fitting, saved models, bounds, requirements and comparing groups.", """\
Life data: failure and suspension times of non-repairable units.
- Censoring flags, per time: 0 = the unit FAILED then; 1 = still running (right-censored, a suspension); -1 = \
left-censored (found failed then, failed at some unknown earlier time); 2 = interval-censored (failed between \
two times: the lower bound in data / time_column, the upper in data_right / time_right_column; other rows repeat \
their time there). Spreadsheets often use 1 = failed: pass c_invert=true rather than rewriting the data. A fit \
saying nearly every row is censored almost always means the flags are inverted; `censoring` gives the failures \
and censored units a fit used: check them against what the user said.
- Units already in service when records began are left-truncated (delayed entry): their entry age goes in \
trunc_left (trunc_left_column), not a flag. trunc_right is the age past which a failure couldn't be seen.
- Fit and report: life_data_analysis fit (inline data, or dataset_id with time_column / censor_column). Keep it: \
models fit (same arguments plus name; inline data is saved as a dataset too). Fitted elsewhere (e.g. locally \
with SurPyval, the way when fitting isn't on the plan): models save with the distribution and params.
- distribution: weibull by default; 'best' fits every plain distribution and keeps the lowest AIC \
(include_mixtures lets two-mode mixtures compete, decided by BIC); discrete, bounded, spline, regression (with \
covariates and a dataset: weibull_ph, cox_ph, …; id_column for covariates that change over time), shared \
frailty (group_column), competing risks (causes / cause_column: each failure mode's share). method: MLE unless \
the user asks.
- A fit that didn't converge or has no finite maximum leads with fit_ok false: don't quote its numbers.
- Weibull beta < 1 = infant mortality, ≈ 1 = random failures, > 1 = wear-out.
- Read saved models: list kind models, get kind model (parameters with 95% CIs, goodness of fit, B-lives with \
one-sided 90% lower bounds; regression models: validation and the proportional-hazards checks).
- Evaluate: life_data_analysis reliability_at (R(t), F(t), hazard; conditional_age for a unit still working; \
confidence for bounds, quoted with the point values; covariates or a covariate_schedule for regression \
models). Bounds are null, with bounds_note saying why, where a model has none: never invent them.
- Requirements: life_data_analysis check_life_requirement ("B10 >= 50,000 at 90% confidence": meets only on \
the B-life's lower bound) and life_data_analysis plan_demonstration_test (units, test time and failures \
allowed; b_life, shape_model_id, producer_risk). Relay plan warnings. Other test plans: guide topic test_planning.
- One-shot items (a valve that must open): life_data_analysis fit_per_demand (batches of demands and \
failures; exact bounds); models fit with demand_batches saves one.
- "Is A better than B?": life_data_analysis compare_groups (split by a column or give a group per time; \
log-rank, RMST difference, Gray's test per mode, a verdict to relay). Nothing is fitted.
- Condition monitoring: remaining life from condition readings (a joint model, Pro): a reading taken again and again on each unit (vibration, wear, oil \
debris) and the units' lives, fitted together. Two datasets: lifetimes, one row per unit (unit_id_column, \
age_column = age since new at failure or when last seen running, censor_column, optional entry_age_column and \
numeric covariates; age_right_column for units found failed between two ages, flag 2), and readings, one row \
per reading (reading_unit_column, reading_age_column since new, reading_value_column). Ages are since new, in \
one time unit (say it). hazard_covariates change the failure rate at a given reading; path_covariates change \
how the reading drifts; one may be in both. path_model: linear unless the readings clearly curve. \
life_data_analysis fit_joint reports; models fit_joint saves. The fit runs on the calculation service (8-40 s): \
it may come back as a job (get kind job). Quote each hazard ratio with its 95% CI, as its text says.
- A running unit's risk: life_data_analysis predict_joint (unit_id, or age_now + readings + unit_covariates): \
survival over the horizons with bounds, and the median remaining life. Never quote a mean life for these \
units: a reading that levels off can leave a chance of never failing, so the mean can be infinite; "not \
reached" means the median is beyond any finite age."""),

    "units": ("Time units for data, models and diagrams.", """\
Units.
- A model's parameters and every time given to or returned by it are in the model's time unit; a diagram's in \
the diagram's unit (rbd create unit; rbd edit set unit relabels, never rescales). Always state the unit with a \
number, and ask the user when unsure: never assume hours.
- A saved model used on a diagram block must be in the diagram's unit; analyses warn when they differ.
- Rates: an exponential failure_rate is per unit time (1/MTBF). An MTBF or MTTR can be given as a block's mean \
(with its shape, e.g. weibull {beta}) instead of params.
- Imported diagram files that state no unit come back with unit_warning: ask, then pass time_unit (or rbd \
edit set unit).
- Calendar-based figures (discount rates, by-horizon costs in years, proof-test calendars) need a calendar \
unit (hours … years).
- Accelerated tests: thermal life-stress models need absolute temperature (kelvin)."""),

    "accelerated": ("Accelerated life tests: fit, extrapolate, bounds.", """\
Accelerated life tests (ALT).
- models fit_alt fits and saves failure times at several stress levels with a life-stress relationship \
(life_model: arrhenius, eyring, inverse_power, dual models…) and a distribution: inline data + stresses (one \
row per unit) or a dataset (time_column + stress_columns). Same censoring flags as life data, inspection data \
(flag 2 with data_right) and delayed entry (trunc_left) included. Thermal models need kelvin. Fitting is Pro.
- life_data_analysis alt_use_level extrapolates it to the use stress: characteristic and mean life, B-lives, \
mission reliability, the acceleration factor against a test stress, with bounds: wald (default), lr, or \
bootstrap (Pro, runs as a job: get kind job until done; not for interval or left-censored data). Quote the \
bounds with the values: an ALT answer is an extrapolation, and with few failures (a warning says so) no bound \
holds its stated confidence."""),

    "test_planning": ("Planning tests: demonstration, sequential, life, accelerated and before/after comparisons.", """\
Test planning: every plan is exact or numerical and saves nothing (life_data_analysis actions). Each answer \
leads with a plain summary: relay it, with the assumptions that matter.
- Show a target is met: plan_demonstration_test (fixed length; method attribute or mtbf; with a good design and \
producer_risk it keeps both risks). plan_sequential_test decides as failures come in, usually sooner: it needs \
the target and a good design (design_mtbf / design_reliability), and with failures_seen plus time_seen (or \
units_seen) says accept, reject or continue. Budget for its longest run (max_time / max_units).
- Estimate a life: plan_life_test from planning values (params, the shape matters most): the precision of a \
B-life or the mean for units on test (solve_for precision), the units for a precision (units, within_pct: 20 = \
±20%) or how long to run (length). test_end time (censor_time), failures (failure_fraction) or all.
- Accelerated tests: plan_accelerated_test from planning values of the non-repairable model (life_params; a similar \
part's models fit_alt gives them) and shape: stresses, units at each and expected failures up to high_stress \
(levels 2 = optimum, 3 = compromise, which can show the model is wrong), or the precision of your own stresses \
and units_at. Relay warnings: stresses with under 3 expected failures make the precision optimistic.
- Did the change work? plan_comparison. kind logrank: old and new units side by side (hazard_ratio new/old, \
event_probability = chance a unit fails during the study): sample_size or power. kind rate_ratio: one fleet \
before and after (failures_before in exposure_before): exposure after needed for a rate_ratio, the smallest \
detectable drop for exposure_after, or power. A null exposure_after means no exposure is enough: say so.
- Checking a plan by simulation is in the app (Pro), not here."""),

    "repairable": ("Recurrent-event (repairable-system) models.", """\
Repairable systems: many failures per system.
- models fit_recurrent fits (and saves, unless save=false) a recurrent-event model from event histories: \
inline times + systems (censored: 0 failure, 1 end of observation; or observed_to) or a dataset. Minimal \
repair: crow_amsaa (default), duane, hpp, cox_lewis; covariates on the repair rate: pi_nhpp; imperfect repair: \
grp_i / grp_ii, ara, ari, g1. windows give observation gaps; causes add each cause's growth. Fitting is Pro.
- get kind model on one: the growth verdict with β's 95% interval, ROCOF and MTBF with bounds, the \
demonstrated MTBF's lower bound, trend and goodness-of-fit tests, and (imperfect repair) the repair \
effectiveness and each system's next failure.
- repairable_analysis next_failure: at a system's age, the chance of a failure within given times and the \
time to the next one. repairable_analysis growth_projection: the MTBF a growth test reaches once its fixes \
are in (BD modes with fix-effectiveness factors).
- strategy optimal_overhaul: the overhaul interval for a deteriorating system (minimal-repair model, β > 1)."""),

    "rbds": ("Building and editing reliability block diagrams: the structure rules.", """\
Building RBDs (rbd create / clone / edit).
- Structure is everything: pure series only for items that must ALL work. Redundancy is modelled as \
redundancy: items named A/B, 1/2, duplex, dual, twin, standby, spare, backup, N+1 or "2 of 3" go in parallel \
(a standby node when the spare sits idle; a knode for k-of-n). Never wire "Pump A" -> "Pump B" in series. State \
your structural assumptions; if unclear, ask one question first. Check structure_summary, the diagram in one \
line, against what the user described.
- Never invent failure data: ask for MTBFs (or saved models) per class of block. If the user wants a starting \
point, give different values per class, set placeholder=true on every guessed model and tell the user.
- rbd create, graph form: nodes + edges, exactly one {id: input, type: input} and one {id: output, type: \
output}; two parallel blocks fan out from the node before and join at the node after; "2 of 3": three blocks \
into one knode (n=2). Stages form: stages in series, each with components in parallel (k_of_n voting).
- Block models: inline distribution_id + params, a mean (MTBF/MTTR) with its shape, a mixture, or a saved \
model (saved_model_id; same time unit).
- Repairable diagrams (repairable=true, analysed for availability): every block needs a repair model. Blocks \
may carry costs, preventive (age / block / condition replacement), inspection (hidden failures found by proof \
tests: offset staggers, coverage + full_test for partial tests), maintenance_group, crew_priority, \
repair_quality (Kijima: simulated figures); the diagram repair_crews, safety_function + target_sil (needs proof \
tests), costs (downtime_rate, horizon, discount_rate) and production (capacity demand). Common cause: \
common_cause_beta on a stage, or edit add_ccf (mgl for 3+ members).
- Non-repairable extras: phases (a phased mission), network (an undirected two-terminal network), \
covariate_schedules on a block with a saved regression model.
- Condition monitoring block (non-repairable diagrams only, one component block per unit): model = \
{saved_model_id: <joint model id>, joint_unit: {id: <running unit id>}} or joint_unit {age, readings: [[age, \
value], ...], covariates}. The block runs from its unit's age now: at mission time t its reliability is the \
unit's survival to age + t given its readings. Don't give it an age in current_state (it is already as of \
now). Repairable diagrams, exports to RePyability JSON and Download as Python refuse it (it lives in Reliafy).
- Edit, don't rebuild: rbd edit with one batch of ops (add_node / remove_node / update_node / add_edge / \
remove_edge / set / add_ccf / remove_ccf), all or nothing; dry_run checks first; if_updated_at refuses if the \
diagram changed. Samples are read-only: rbd clone first. get kind rbd reads a diagram's full graph.
- rbd upload_outage_log attaches a real outage log (asset, start, end; blank end = still down) to the user's \
diagram; rbd_analysis system_history reads it back."""),

    "rbd_analysis": ("Analysing RBDs: figures, simulation, jobs and the other analyses.", """\
Analysing RBDs (rbd_analysis).
- analyze, non-repairable: reliability curve (~21 points; `times` gives exact values in reliability_at), MTTF, \
B-lives, importance and cut sets; current_state ({node: {failed: true} | {age}}) gives the remaining life from \
now; target_reliability the design life; confidence intervals from fitted blocks (with b_lives, times).
- analyze, repairable, on every plan: exact (or numerical, never simulated) long-run availability, mean up / \
down time, failure frequency, and in `exact` A(t), the mission availability and the window's expected \
failures, outages, downtime and cost — from new, or from now with current_state ({node: {down: true, since} | \
{age}}) over t_max. Safety functions add PFDavg and SIL; priced diagrams costs (a present value with \
discount_rate); capacities the production availability. The Monte-Carlo simulation adds only the spread \
(percentiles, P(no outage), criticality; from current_state the time to the next failure) and is Pro; it runs \
only where a figure needs it unless simulate=true. A saved result is served when one matches. When a response \
says figures are simulation-only (e.g. one crew for wear-out lives), say so; offer export_python to run it \
locally. summary_only gives the headline figures.
- Jobs: a long simulation or calculation returns a job_id: call get kind job every few seconds until done. \
quote_simulation says how long one should take before anything runs; list kind rbd_runs / get kind rbd_run read \
past simulations.
- What to improve (repairable): sensitivity ranks every lever by what a 10% step gains (exact or numerical \
free; simulated Pro); costs_to_change with order benefit_per_cost ranks by benefit per cost; measure gives \
over_time, shares, joint, rate or uncertainty. Quote `top` with its basis.
- optimise_intervals chooses age-replacement or proof-test intervals together (lowest cost, or a target \
availability / PFDavg / SIL, or a cost cap), returns edit_rbd_ops to apply with rbd edit. cheapest_design: \
the redundancy with the lowest total cost (needs block acquisition prices, a horizon and a downtime_rate; \
trains copy whole chains). compare: design B against A (rbd clone A, edit, compare). allocate_targets: what \
each block needs for a system target. fault_tree: ranked cut sets with common causes. These answer only; apply a choice \
with rbd edit.
- system_history: observed availability from the diagram's outage log. export_python: a standalone script \
(SurPyval + RePyability) with the run command; export_json: RePyability's JSON (uploads import_rbd takes it \
back)."""),

    "strategy": ("Replacement (also over a shut calendar), proof-test and overhaul intervals; shape uncertainty.", """\
Maintenance strategy (strategy).
- strategy optimal_replacement: the cost-optimal age-replacement interval from a non-repairable model (model_id, or \
distribution_id + params) and the planned and unplanned costs. beneficial=false: run to failure is cheaper.
- strategy failure_finding_interval: the proof-test interval keeping a hidden protective function (relief valve, trip, \
standby unit) at a target availability.
- strategy optimal_overhaul: the overhaul interval of a repairable system from a minimal-repair recurrent model.
- strategy calendar_replacement: when replacing costs less at shuts (annual, quarterly, weekly stops) than between \
them, the long-run best rule: at each shut, replace the part if it is older than a threshold age (the threshold \
depends on when the next cheaper shut comes). Give the model in a time unit, the shuts (name, cost, every N \
days/weeks/months/years from a start date, or dates), failure_cost and anytime_cost (a planned replacement between \
shuts; omit when only shuts allow one). Today is time 0; months are 365.25/12 days. Back: cost_rate (per model \
unit) and cost_per_year, the rule in words, by_kind (replacements and cost a year per shut kind and failures), \
comparisons (run to failure, age replacement ignoring the shuts, every shut of a kind) and the next 12 months' \
shuts with each one's threshold and chance of a replacement. method dp (default) and integration (no anytime_cost) \
are exact and free; sampling (Pro) is for calendars whose cycle is very long, with cost_rate_se. Quote the unit.
- strategy next_replacement: the same calendar plus the age of the unit in service today: replace it now, at the \
next shut of each kind, between shuts, or run it to failure, each choice's cost, the best, and replace_from_age \
(from that age replacing now beats waiting).
- With a saved Weibull (or Crow-AMSAA) model fitted to data, shape_uncertainty gives the answer at each end of \
the shape's 95% interval: relay uncertainty_note when present — the recommendation is less firm than it reads \
(for a protective function, the shorter interval is the safe side).
- A whole diagram's intervals together: rbd_analysis optimise_intervals. A demonstration test or a B-life \
check: life_data_analysis plan_demonstration_test / check_life_requirement. Fleets: guide topic fleets."""),

    "fleets": ("Fleet failure forecasts and their email alerts (Pro).", """\
Fleets (Reliafy Pro).
- A fleet is in-service items run against one saved model; the app creates them and usage arrives through \
the ingest API. list kind fleets lists them (model_kind life, regression, alt or recurrent).
- strategy fleet_forecast: expected failures over the horizon with a P10–P90 range, per period and per item (the \
top 20 unless include_items; item_probabilities adds each item's chance by period). Recurrent fleets count every \
repeat failure.
- Spares: fleet_forecast with spares = {lead_time (in the fleet's periods), service_level (default 0.95), review, \
per_failure, stock, unit_cost} (or the fleet's saved spares settings) adds spares: hold (the stock for that chance \
of no stock-out over the lead time plus review), reorder_at, risk_at_stock, hold_cost, the same per period, and \
risk_curve ([stock, chance of running out]). repairable with turnaround: the pool covers the repair turnaround \
(one site). Read off the forecast's own distribution, not a normal approximation.
- Alerts: list kind fleet_alerts reads a fleet's rules with their current values; fleet create_alert adds one \
(above a threshold, a percent change, or x failures within y periods), checked whenever usage arrives, emailing \
the user once per crossing; at most 10 per fleet, own fleets only."""),

    "uploads": ("Sending files: the upload link, its fallbacks, inspecting and importing.", """\
Files (BlockSim / Open-PSA / Galileo / RePyability diagrams, Excel workbooks, CSVs of failure times or \
outages). Never read a file into your context to paste it while the upload link works.
1. uploads create (purpose: rbd_import, excel, dataset or outage_log; filename): a single-use URL (15 minutes) \
and a ready curl PUT. Run it from a shell that can read the file.
2. If the PUT can't connect or a proxy refuses the host (e.g. CONNECT 403), retry the same PUT once on \
url_fallback (curl_fallback): the same link on reliafy.com, slower for large files, still unused after a \
refused attempt.
3. If that fails too (no network), don't retry: a small text file (at most 200 KB) can be passed as text instead \
(datasets upload csv, rbd upload_outage_log csv, uploads import_rbd content for Open-PSA XML, Galileo or \
RePyability JSON); any other file of up to a few hundred KB (an .xlsx, a BlockSim project) goes through this \
connection with uploads send_part (base64 parts 0, 1, 2… into the same upload_id, last=true with sha256 on the \
final one; not counted against the Free allowance), then import as usual; an FMEA / RCM worksheet you can read \
can instead go in as JSON with rcm create. Anything larger: ask the user to upload it in the app (create's \
fallback says where).
4. get kind upload shows a workbook's sheets, columns and a guessed mapping, or a diagram file's diagrams.
5. Import with the upload_id: uploads import_rbd (diagrams; save=false previews with edges and cut sets; only \
picks diagrams by name; time_unit when the file states none), uploads import_excel (target dataset, rcm or \
rbd_template), datasets upload, or rbd upload_outage_log.
Relay the import notes: they say what was approximated. Blocks imported without a non-repairable model (needs_model) \
need one before analysis: ask the user, don't invent values."""),

    "rcm": ("RCM / FMEA studies as structured JSON.", """\
RCM studies (FMEA / RCM worksheets).
- list kind rcm_studies; get kind rcm_study reads one in the form rcm create takes, with every node's id and \
each decision's evidence check (supported / contradicted / inconclusive / unevidenced / stale; read-only). Over \
300 failure modes comes back as an outline: pass function_id for one function.
- rcm create saves one from JSON: functions › failures (functional failures) › modes, each mode with effects, \
consequence (safety, environmental, operational, non_operational, hidden), notes and a decision {outcome: \
on_condition | fixed_interval | rtf (with rtf_basis random or uneconomic) | failure_finding | redesign | \
accept, task, interval, interval_unit, notes, evidence}. Every node needs text. Use it when you can read a \
worksheet but can't upload it (map the columns and values yourself), or to record an analysis built with the \
user. A decision with an interval becomes a scheduled task in Reliafy Maintenance (warnings flag ones without).
- Evidence links a decision to a saved model, strategy analysis or degradation model (the user's own or a \
sample); Reliafy checks it on every read.
- rcm update: mode merge (default) adds nodes without an id and changes those with one (give a parent's id with \
no other change to add children under it); mode replace makes functions the whole worksheet (keep ids so \
Maintenance positions stay linked); or set name, system, description. Samples can't change.
- A worksheet file: uploads import_excel with target rcm (guide topic uploads)."""),

    "sharing": ("Share links and reports: read-only pages anyone with the URL can open.", """\
Sharing (only when the user asks; confirm before publishing anything).
- sharing create_link publishes a read-only page of one of the user's own items (model, dataset, rbd, \
degradation_model, strategy_analysis, rcm_study, fleet, recurrent_model) that anyone with the URL can open \
without an account. password=true: Reliafy generates a passphrase, returned once — tell the user to send the \
link and the passphrase to the recipient separately. expires_in_days for a link that ends; label says who it's \
for. Samples can't be shared (rbd clone one first).
- sharing create_report puts several items on one print-ready page with a title, an author line, an \
introduction and a note per item. Write the notes from the items' results, quoting their figures as the tools \
returned them.
- list kind share_links shows the live links; sharing revoke_link ends one at once."""),

    "workspace": ("Reading, tidying and deleting saved items; what changed.", """\
The workspace.
- Reads: list kind models / datasets / rbds / rcm_studies / fleets / share_links / rbd_runs, and get kind model \
/ dataset (a page of rows at a time) / rbd / rcm_study / rbd_run / job / upload. Shared samples are listed \
(is_sample) and readable, never changed.
- list kind workspace_changes: what changed over a period (since a date or the last visit, or days), computed \
from what Reliafy stores: new and changed items, refits that moved B10 or MTTF, moved forecasts, fired alerts, \
RCM evidence changes, moved simulations. Start from its sentence; report not_compared as unknown, never guess.
- Tidying: models update / datasets update rename or annotate (never the data or the fit).
- Deleting: models delete, datasets delete, rbd delete — permanent, own items only. Only on the user's \
explicit request: confirm by name first, and relay what the response lists as affected. A dataset a model was \
fitted to, or a model a fleet runs on, can't be deleted until those are dealt with.
- Every saved item has a url: give it to the user so they can open it in Reliafy.
- When a tool gets in your way (an error, a result that makes no sense, an action that's missing, a default \
that's wrong, a guide that's unclear), report_problem report it: kind, a one-line summary, the tool and \
action, what you were trying, what you expected and what happened. Tell the user you did. It never counts \
against a plan. report_problem status (with the report_id, or none for your latest) says later whether it was \
acknowledged or fixed, and in which release; when it's fixed, try again."""),

    "plans": ("Free, Pro and the limits; what to do when one stops a call.", """\
Plans and limits.
- Using Reliafy from AI agents is part of Reliafy Pro: every tool, no limit. Free gets a few tool calls a month \
to try it (every tool except fitting and fleets, within the Free storage limits; availability simulation and \
some design searches are Pro too). A retired Agent plan keeps a daily quota until it ends.
- get kind account: the plan, the calls used and left (and when they reset), storage against the limits, \
whether simulation is included. It, guide, upgrade_link and uploads send_part are never counted.
- When a tool says a limit or the plan stops it, tell the user plainly what it says — the limit, when it \
resets, how to upgrade — and don't retry. Calls refused that way aren't counted.
- Without Pro, fit locally with SurPyval (pip install surpyval; 0 = failed, 1 = still running) and save the \
parameters with models save; run a diagram's simulation locally with rbd_analysis export_python.
- upgrade_link gives the user a Stripe payment link to open themselves; nothing is charged until they complete \
it. Never say an upgrade has happened."""),
}
