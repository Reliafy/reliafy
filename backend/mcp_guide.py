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
- Params are lists of {name, value} with SurPyval's names: weibull [alpha (scale), beta (shape)], exponential \
[failure_rate], normal / lognormal [mu, sigma], gamma [alpha, beta]; in the model's time unit.
- Fit and report: analyse fit (inline data, or dataset_id with time_column / censor_column). Keep it: \
change model_fit (same arguments plus name; inline data is saved as a dataset too). Fitted elsewhere (e.g. locally \
with SurPyval, the way when fitting isn't on the plan): change model_save with the distribution and params.
- distribution: weibull by default; 'best' fits every plain distribution and keeps the lowest AIC \
(criterion: aic_c, bic or neg_ll to rank by another score; selection gives each candidate's parameters, score \
and delta to the best, under 2 is a tie, what it skipped and why, and guidance in words: relay it; \
include_mixtures lets two-mode mixtures compete, decided by BIC); discrete, bounded, spline, regression (with \
covariates and a dataset: weibull_ph, weibull_aft, loglogistic_aft, weibull_po, weibull_ah, cox_ph, …; \
id_column for covariates that change over time; the read is a hazard ratio for _ph, a time ratio for _aft, an \
odds ratio for _po and an added failure rate for _ah; diagnostics.model_checks says whether the model's own \
assumption holds, with what to try if not), shared frailty (group_column; frailty_family lognormal for a \
heavier-tailed frailty), competing risks (causes / cause_column: each failure mode's share). method: MLE unless \
the user asks.
- A fit that didn't converge or has no finite maximum leads with fit_ok false: don't quote its numbers.
- One or two failures and a credible baseline (a class's or fleet's model, a vendor's or handbook's numbers, a \
B10 the user believes): analyse bayes_update (Pro) updates the baseline with the data: baseline {model_id} or \
{distribution, params, unit} or {b10: {value, low, high}, shape: {low, high}, unit}; trust close / guide / start \
(each number within about 10 / 30 / 60%; a fitted baseline counts as all, half or a fifth of its evidence); x and c \
in the baseline's unit. E.g. baseline {model_id: <the class's Weibull>}, trust guide, x [1400, 1900, 2500], c \
[0, 0, 1]. It returns posterior medians with 90% credible intervals (the B10 and mean life with a 90% one-sided \
lower bound: "90% sure the B10 is at least ..."), never confidence bounds, and says what moved the baseline. It's a Bayesian update of a baseline: use it for \
sparse data with a baseline the user trusts, say the baseline and the trust when quoting it; with plenty of \
failures fit instead. No data: the baseline stands as given. With Reliafy Maintenance, baseline \
{class_power_prior: true, position_id} uses that position's class's other positions' history as a power prior \
(SurPyval's prior.from_data, weighed by trust). A data library rate as a prior: maintenance models.link with fit, \
method bayes and prior {kind: library, record_id} (e.g. a motor-operated valve's rate, record from list kind \
library): on an exponential its gamma is the prior exactly (conjugate). On a maintenance position, maintenance models.link \
with fit and baseline saves one and attaches it.
- Weibull beta < 1 = infant mortality, ≈ 1 = random failures, > 1 = wear-out.
- Every bound is at 90%: life quantities (B-lives, mean life, life left) one-sided lower, a chance of \
failing one-sided upper, everything else (parameters, ratios, bands, forecast ranges) two-sided. Say the level \
with each bound; a result's ci_level or confidence field gives it (95% on some fits saved before Nov 2026).
- Read saved models: list kind models, get kind model (parameters with 90% CIs, goodness of fit, B-lives with \
one-sided 90% lower bounds; regression models: validation and the proportional-hazards checks).
- Evaluate: analyse reliability_at (R(t), F(t), hazard; conditional_age for a unit still working; \
confidence for bounds, quoted with the point values; covariates or a covariate_schedule for regression \
models). Bounds are null, with bounds_note saying why, where a model has none: never invent them.
- Requirements: analyse check_life_requirement ("B10 >= 50,000 at 90% confidence": meets only on \
the B-life's lower bound) and analyse plan_demonstration_test (units, test time and failures \
allowed; b_life, shape_model_id, producer_risk). Relay plan warnings. Other test plans: guide topic test_planning.
- One-shot items (a valve that must open): analyse fit_per_demand (batches of demands and \
failures; exact bounds); change model_fit with demand_batches saves one.
- "Is A better than B?": analyse compare_groups (split by a column or give a group per time; \
log-rank, RMST difference, Gray's test per mode, a verdict to relay). Nothing is fitted.
- Condition and life: remaining life from condition readings (a joint model, Pro): a reading taken again and again on each unit (vibration, wear, oil \
debris) and the units' lives, fitted together. One dataset (dataset_id) holding both: its life data, one row \
per unit (unit_id_column, age_column = age since new at failure or when last seen running, censor_column, \
optional entry_age_column and numeric covariates; age_right_column for units found failed between two ages, \
flag 2), and its measurements, one row per reading (reading_unit_column, reading_age_column since new, \
reading_value_column; change dataset_add_measurements puts them on the dataset: csv, an upload_id, or \
from_dataset_id to copy another dataset's table in). A dataset whose one table holds both (the flag filled in \
once per unit, a reading on every row) works as it is, or change dataset_split makes the two parts. Ages are since \
new, in one time unit (say it). hazard_covariates change the failure rate at a given reading; path_covariates \
change how the reading drifts; one may be in both. path_model: linear unless the readings clearly curve. \
analyse fit_joint reports; change model_fit_joint saves. The fit runs on the calculation service (8-40 s): \
it may come back as a job (get kind job). Quote each hazard ratio with its 90% CI, as its text says.
- A running unit's risk: analyse predict_joint (unit_id, or age_now + readings + unit_covariates): \
survival over the horizons with bounds, and the median remaining life. Never quote a mean life for these \
units: a reading that levels off can leave a chance of never failing, so the mean can be infinite; "not \
reached" means the median is beyond any finite age."""),

    "units": ("Time units for data, models and diagrams.", """\
Units.
- A model's parameters and every time given to or returned by it are in the model's time unit; a diagram's in \
the diagram's unit (change rbd_create unit; change rbd_edit set unit relabels, never rescales). Always state the unit with a \
number, and ask the user when unsure: never assume hours.
- A saved model used on a diagram block must be in the diagram's unit; analyses warn when they differ.
- Rates: an exponential failure_rate is per unit time (1/MTBF). An MTBF or MTTR can be given as a block's mean \
(with its shape, e.g. weibull {beta}) instead of params.
- Imported diagram files that state no unit come back with unit_warning: ask, then pass time_unit (or change \
rbd_edit set unit).
- Calendar-based figures (discount rates, by-horizon costs in years, proof-test calendars) need a calendar \
unit (hours … years).
- Accelerated tests: thermal life-stress models need absolute temperature (kelvin)."""),

    "accelerated": ("Accelerated life tests: fit, extrapolate, bounds.", """\
Accelerated life tests (ALT).
- change model_fit_alt fits and saves failure times at several stress levels with a life-stress relationship \
(life_model: arrhenius, eyring, inverse_power, dual models…) and a distribution: inline data + stresses (one \
row per unit) or a dataset (time_column + stress_columns). Same censoring flags as life data, inspection data \
(flag 2 with data_right) and delayed entry (trunc_left) included. Thermal models need kelvin. Fitting is Pro.
- analyse alt_use_level extrapolates it to the use stress: characteristic and mean life, B-lives, \
mission reliability, the acceleration factor against a test stress, with bounds: wald (default), lr, or \
bootstrap (Pro, runs as a job: get kind job until done; not for interval or left-censored data). Quote the \
bounds with the values: an ALT answer is an extrapolation, and with few failures (a warning says so) no bound \
holds its stated confidence."""),

    "test_planning": ("Planning tests: demonstration, sequential, life, accelerated and before/after comparisons.", """\
Test planning: every plan is exact or numerical and saves nothing (analyse actions). Each answer \
leads with a plain summary: relay it, with the assumptions that matter.
- Show a target is met: plan_demonstration_test (fixed length; method attribute or mtbf; with a good design and \
producer_risk it keeps both risks). plan_sequential_test decides as failures come in, usually sooner: it needs \
the target and a good design (design_mtbf / design_reliability), and with failures_seen plus time_seen (or \
units_seen) says accept, reject or continue. Budget for its longest run (max_time / max_units).
- Estimate a life: plan_life_test from planning values (params, the shape matters most): the precision of a \
B-life or the mean for units on test (solve_for precision), the units for a precision (units, within_pct: 20 = \
±20%) or how long to run (length). test_end time (censor_time), failures (failure_fraction) or all.
- Accelerated tests: plan_accelerated_test from planning values of the non-repairable model (life_params; a similar \
part's change model_fit_alt gives them) and shape: stresses, units at each and expected failures up to high_stress \
(levels 2 = optimum, 3 = compromise, which can show the model is wrong), or the precision of your own stresses \
and units_at. Relay warnings: stresses with under 3 expected failures make the precision optimistic.
- Did the change work? plan_comparison. kind logrank: old and new units side by side (hazard_ratio new/old, \
event_probability = chance a unit fails during the study): sample_size or power. kind rate_ratio: one fleet \
before and after (failures_before in exposure_before): exposure after needed for a rate_ratio, the smallest \
detectable drop for exposure_after, or power. A null exposure_after means no exposure is enough: say so.
- Checking a plan by simulation is in the app (Pro), not here."""),

    "repairable": ("Recurrent-event (repairable-system) models.", """\
Repairable systems: many failures per system.
- change model_fit_recurrent fits (and saves, unless save=false) a recurrent-event model from event histories: \
inline times + systems (censored: 0 failure, 1 end of observation; or observed_to) or a dataset. Minimal \
repair: crow_amsaa (default), duane, hpp, cox_lewis; covariates on the repair rate: pi_nhpp; imperfect repair: \
grp_i / grp_ii, ara, ari, g1. windows give observation gaps; causes add each cause's growth. Fitting is Pro.
- get kind model on one: the growth verdict with β's 90% interval, ROCOF and MTBF with bounds, the \
demonstrated MTBF's lower bound, trend and goodness-of-fit tests, and (imperfect repair) the repair \
effectiveness and each system's next failure.
- analyse next_failure: at a system's age, the chance of a failure within given times and the \
time to the next one. analyse growth_projection: the MTBF a growth test reaches once its fixes \
are in (BD modes with fix-effectiveness factors).
- analyse optimal_overhaul: the overhaul interval for a deteriorating system (minimal-repair model, β > 1)."""),

    "rbds": ("Building and editing reliability block diagrams: the structure rules.", """\
Building RBDs (change rbd_create / clone / edit).
- Structure is everything: pure series only for items that must ALL work. Redundancy is modelled as \
redundancy: items named A/B, 1/2, duplex, dual, twin, standby, spare, backup, N+1 or "2 of 3" go in parallel \
(a standby node when the spare sits idle; a knode for k-of-n). Never wire "Pump A" -> "Pump B" in series. State \
your structural assumptions; if unclear, ask one question first. Check structure_summary, the diagram in one \
line, against what the user described.
- Never invent failure data: ask for MTBFs (or saved models) per class of block. If the user wants a starting \
point, give different values per class, set placeholder=true on every guessed model and tell the user.
- change rbd_create, graph form: nodes + edges, exactly one {id: input, type: input} and one {id: output, type: \
output}; two parallel blocks fan out from the node before and join at the node after; "2 of 3": three blocks \
into one knode (n=2). Stages form: stages in series, each with components in parallel (k_of_n voting).
- Block models: inline distribution_id + params, a mean (MTBF/MTTR) with its shape, a mixture, or a saved \
model (saved_model_id; same time unit).
- Repairable diagrams (repairable=true, analysed for availability): every block needs a repair model. Blocks \
may carry costs, preventive (age / block / condition replacement), inspection (hidden failures found by proof \
tests: offset staggers, coverage + full_test for partial tests), maintenance_group, crew_priority, \
repair_quality (Kijima: simulated figures), duty (0-1, the share of the time it runs: its model is then a life \
in operating time; intervals stay on the clock); the diagram repair_crews, safety_function + target_sil (needs proof \
tests), costs (downtime_rate, horizon, discount_rate) and production (capacity demand). Common cause: \
common_cause_beta on a stage, or edit add_ccf (mgl for 3+ members).
- Non-repairable extras: phases (a phased mission), network (an undirected two-terminal network), \
covariate_schedules on a block with a saved regression model.
- Missions: change rbd_mission adds named phased missions to a diagram (several over the same blocks, e.g. \
"Corridor inspection", "Survey grid"); each phase has a duration, not_needed blocks, votes (k-of-n per \
phase) and values {covariate name: value} for the Use / Environment covariates its bound blocks left open \
(block_values {block id: {key: value}} for one block). Blocks age across the whole mission. analyse \
rbd_mission lists those covariates with the blocks each feeds, then gives the chance of completing it, per \
phase, and each phase's weakest block; a phase missing a value waits (needs).
- Condition and life block (non-repairable diagrams only, one component block per unit): model = \
{saved_model_id: <joint model id>, joint_unit: {id: <running unit id>}} or joint_unit {age, readings: [[age, \
value], ...], covariates}. The block runs from its unit's age now: at mission time t its reliability is the \
unit's survival to age + t given its readings. Don't give it an age in current_state (it is already as of \
now). Repairable diagrams, exports to RePyability JSON and Download as Python refuse it (it lives in Reliafy).
- Edit, don't rebuild: change rbd_edit with one batch of ops (add_node / remove_node / update_node / add_edge / \
remove_edge / set / add_ccf / remove_ccf), all or nothing; dry_run checks first; if_updated_at refuses if the \
diagram changed. Samples are read-only: change rbd_clone first. get kind rbd reads a diagram's full graph.
- change rbd_upload_outage_log attaches a real outage log (asset, start, end; blank end = still down) to the user's \
diagram; analyse rbd_system_history reads it back."""),

    "library": ("Published failure data: units, citing it, using it in a block.", """\
The reliability data library (list kind library, get kind library_record, list kind library_sources): published generic failure data. Each record is \
one component and failure mode from one source, with its citation and licence.
- list kind library finds records by words (component, failure mode, system: "motor-driven pump fails to start"), \
filtered by source, equipment_type and record_kind (rate, per_demand, life); 25 a page, best first, with counts. \
get kind library_record gives a record in full, with block_model: the model a block would use.
- Read the units. A rate is per hour: per hour of running (fails to run) or per calendar hour (leaks, spurious \
operation, running or not). per_demand is a probability on each demand (a start, an opening), not a rate.
- Quote the mean with its 5th to 95th percentile range (the source's spread: gamma for a rate, beta for a \
demand), and the evidence (failures, demands or hours).
- In an RBD block: a rate is an exponential (failure_rate = the mean, x 24 per day, x 8,760 per year). A \
per-demand probability p is a cold-standby spare's startProb (1 - p), or a proof-tested item's failure on test. \
Converting a calendar rate to hours of running needs the hours a year it runs: ask the user, never guess.
- Every input a record needs is a covariate (get kind library_record lists covariates: key, unit, role, default, \
limits): a pipe's length_ft; clock (calendar or operating) and running_hours_per_year to change a rate's clock; \
demands_per_year to make a per-demand probability a rate; a handbook part's environment and quality. Pass \
covariates to evaluate; one with no default is listed as missing: ask the user, never guess.
- Components (list kind library with components true; NRC/INL): an equipment type in one pooling group (motor-driven \
pump, normally standby) with its failure modes. get kind library_record with its id and covariates {demands, \
running_hours, calendar_hours} gives P(fails over the period): the modes as competing risks, 1 − Π(1 − q)^demands × \
exp(−Σ λ × hours), plus the plain rare-event sum and a constant rate per calendar hour.
- Handbook records (basis prediction_model, MIL-HDBK-217F: electronic parts) are a base failure rate per part \
type, not counted failures, and never mixed with field data. The rate depends on where the part works: get kind \
library_record with environment (GB ground, benign; GF ground, fixed; GM ground, mobile; NS naval, sheltered; AIC \
airborne, inhabited, cargo; and so on: the record's environments list each with its rate) gives the block model, \
base rate x the environment factor. Ask the user which environment; never guess. Say plainly that the handbook's \
other factors (temperature, stress, quality: prediction.not_applied) aren't applied and can move the rate a lot.
- NSWC-11 (source nswc-11, kind covariate_model: the U.S. Navy's mechanical handbook) is a library of covariate \
models for mechanical parts (bearings, seals, springs, pumps, gears, valves, motors...): a base rate scaled by \
factors for the conditions. get kind library_record lists covariate.inputs (unit, default and where it comes from, \
limits with the handbook's page); give conditions to evaluate: the rate per mode and in total (per million hours, \
or cycles or operations), or the problems (an input missing or past a limit). Ask the user for the conditions; \
never guess. Outside a warn limit it still computes: relay the warning. It's never a block model on its own; \
use it in a prediction, or fix its covariates at a position. Always say that CDNSWC and the Navy did not take part in or approve Reliafy, and that \
the handbook is a research result, not an official DoD document.
- These are generic estimates (NRC/INL: U.S. nuclear power plants; MIL-HDBK-217F: a 1995 prediction handbook), \
never the user's own data: say so, cite the record (licence.attribution), put the source in the block's label \
and suggest replacing it with their own data.
- Library lookups are never counted against the Free plan's tool calls.
- Build the user's own library: change library_create (name, description, notes or licence text shown with every \
record), then change library_add_model (library_id, model_id, failure_mode, equipment_type) for each saved Weibull, \
exponential, lognormal, normal or gamma model. A model is in no library until it's added; adding keeps a snapshot \
(distribution, parameters with their bounds, unit, sample sizes, how it was fitted) with model_id as a link, so a \
later refit doesn't change the record. list kind libraries and get kind library read them; their records appear in \
list kind library and get kind library_record like published ones (source: the library's id; kind life), usable as \
a model or a prior (the prior is in the record's family: each parameter about its value, between its bounds). One \
library is one saved item toward the Free storage limit, whatever it holds. Only on the user's request: \
library_remove_record and library_delete (the models stay).
"""),
    "prediction": ("Reliability prediction: a parts count from handbook base rates, before there's failure data.", """\
A reliability prediction (analyse prediction; change prediction_save / prediction_update / prediction_delete; get kind \
prediction; list kind predictions) estimates a design's failure rate from its parts \
list and the library's handbook base rates (MIL-HDBK-217F), for a design that has no failure data yet.
- The method is a parts count. Each line is a part type, how many there are and the handbook record for it: its \
rate is λb × πE × πQ × quantity (λb the record's base failure rate per million hours, πE the record's factor for \
the environment, πQ a quality factor per line, 1 unless given). The system is the sum, every part in series: \
MTBF = 1/λ and R(t) = exp(−λt) at mission_time (hours). The result gives the rate per million hours and per hour, per line, per \
assembly (a line's assembly is a name or a path such as "Power › BMS board") and in total, and a Pareto by line and by \
part category.
- Assign part types with list kind library (source mil-hdbk-217f-n2): "capacitor ceramic", "resistor film", \
"connector rectangular", "mosfet", "microprocessor MOS", "memory DRAM", "motor", "quartz crystal", "circuit \
board". Only handbook records (basis prediction_model) count; a field-data record (NRC / INL) is refused. \
Microcircuits, motors, synchros, circuit boards, crystals, lamps and laser diodes are parts-count records \
(generic_rates: a rate per environment, environment included; πQ defaults to the lowest grade, e.g. 10 for a \
commercial microcircuit, unless quality_factor is given). A mechanical part takes an NSWC-11 record (source \
nswc-11: "bearing", "seal", "pump", "spring", "gear") with conditions (its covariate inputs, guide topic library) \
and, for a rate per cycle or operation, cycles_per_hour; no quality factor or environment. A line missing a \
condition is listed (needs_conditions) and left out of the total until it has it. The result's method and \
handbooks say which lines used which handbook; quote its disclaimer with any NSWC-11 result. Neither handbook has \
batteries: a battery takes rate_per_million_hours only if the user gives one (shown as user-given); a part neither \
covers (airframe) takes excluded true (left out, and the result names it). A line with neither and no \
record_id is listed and left out of the total. Never invent a part type or a rate.
- The environment is one symbol for the whole prediction (GB, GF, GM, NS, NU, AIC, AIF, AUC, AUF, ARW, SF, MF, ML, \
CL): ask the user where the equipment works; never guess. A record's prediction.quality_factor_range is the \
handbook's range for πQ; a line outside it warns.
- Say what's applied and what isn't: λb, πE and πQ are; the handbook's other factors (temperature, electrical \
stress, construction, power and so on: factors.not_applied) aren't, and real rates depend on them. The handbook \
dates from 1995 and is for comparing designs early, not a measure of how equipment will fail: say so when quoting \
a result, and prefer the user's own failure data when they have any.
- Reliafy Maintenance users can start from a product: product_id reads its part's bill of materials as lines \
(each lowest-level part under its assemblies) with no part types yet; assign them and call again with lines (and \
product_id, which keeps the product as the prediction's source).
- Saving is free, exact and keeps the results as computed; an update computes them again.
"""),
    "rbd_analysis": ("Analysing RBDs: figures, simulation, jobs and the other analyses.", """\
Analysing RBDs (analyse rbd and the other rbd_ actions).
- rbd, non-repairable: reliability curve (~21 points; `times` gives exact values in reliability_at), MTTF, \
B-lives, importance and cut sets; current_state ({node: {failed: true} | {age}}) gives the remaining life from \
now; target_reliability the design life; confidence intervals from fitted blocks (with b_lives, times).
- rbd, repairable, on every plan: exact (or numerical, never simulated) long-run availability, mean up / \
down time, failure frequency, and in `exact` A(t), the mission availability and the window's expected \
failures, outages, downtime and cost — from new, or from now with current_state ({node: {down: true, since} | \
{age}}) over t_max. Safety functions add PFDavg and SIL; priced diagrams costs (a present value with \
discount_rate); capacities the production availability. The Monte-Carlo simulation adds only the spread \
(percentiles, P(no outage), criticality; from current_state the time to the next failure) and is Pro; it runs \
only where a figure needs it unless simulate=true. A saved result is served when one matches. When a response \
says figures are simulation-only (e.g. one crew for wear-out lives), say so; offer rbd_export_python to run it \
locally. summary_only gives the headline figures.
- Jobs: a long simulation or calculation returns a job_id: call get kind job every few seconds until done. \
rbd_quote_simulation says how long one should take before anything runs; list kind rbd_runs / get kind rbd_run read \
past simulations.
- What to improve (repairable): rbd_sensitivity ranks every lever by what a 10% step gains (exact or numerical \
free; simulated Pro); costs_to_change with order benefit_per_cost ranks by benefit per cost; measure gives \
over_time, shares, joint, rate or uncertainty. Quote `top` with its basis.
- rbd_optimise_intervals chooses age-replacement or proof-test intervals together (lowest cost, or a target \
availability / PFDavg / SIL, or a cost cap), returns edit_rbd_ops to apply with change rbd_edit. rbd_cheapest_design: \
the redundancy with the lowest total cost (needs block acquisition prices, a horizon and a downtime_rate; \
trains copy whole chains). rbd_compare: design B against A (change rbd_clone A, edit, compare). rbd_allocate_targets: \
what each block needs for a system target. rbd_fault_tree: ranked cut sets with common causes. These answer only; apply a choice \
with change rbd_edit.
- rbd_system_history: observed availability from the diagram's outage log. rbd_export_python: a standalone script \
(SurPyval + RePyability) with the run command; rbd_export_json: RePyability's JSON (change import_rbd takes it \
back)."""),

    "fault_trees": ("Fault trees built by hand: gates, basic events, analysis, RBD and Open-PSA.", """\
Fault trees: a top event, gates and basic events, saved as their own items (list kind fault_trees).
- Gates: or (occurs when any input occurs), and (when all do), vote with k (when at least k of its inputs do). \
NOT, XOR, INHIBIT and dynamic gates (priority-AND, spare, functional dependency, sequence) are refused: say \
so, and suggest an RBD (standby there) for spares.
- change fault_tree_save: name, top (the top event's gate id) and nodes. A gate: {id, type: gate, label, gate, \
k (vote), inputs: [ids]}. A basic event: {id, type: event, label} plus model (as an RBD block's: \
saved_model_id, or distribution_id + params, or mean) OR probability (a fixed unavailability q, 0 to 1). A \
basic event may sit under several gates (a repeated event, counted once); a gate under one. unit: the models' \
time unit. Up to 500 gates and events.
- Never invent failure data: ask, or mark a guess placeholder=true and say so. A tree may be saved unfinished \
(no_data lists the events still without data); analyse fault_tree says what it needs.
- fault_tree_save with fault_tree_id replaces the tree's nodes (get kind fault_tree first, change, send back); \
samples can't be changed: save a copy without fault_tree_id.
- analyse fault_tree: the top event probability at t (default where it's about 10%; no t when every event is \
a fixed probability), minimal cut sets (share_alone overlaps: shares don't add to 1) and each event's \
importance (criticality = its share of the top event; Birnbaum; Fussell-Vesely; RAW; RRW). Exact and free. \
export_openpsa=true adds the tree as Open-PSA XML.
- make_rbd=true on fault_tree_save also saves the equivalent RBD (OR = series, AND = parallel, k of n failed \
= n-k+1 of n working); a fixed-probability event becomes a block with no model, to be set before analysing it.
- change import_rbd with as_fault_tree=true saves an Open-PSA or Galileo file's top events as fault trees.
- change fault_tree_delete: own trees only, on the user's explicit request, confirmed by name."""),

    "strategy": ("Replacement (also over a shut calendar), proof-test and overhaul intervals; shape uncertainty.", """\
Maintenance strategy (analyse actions).
- analyse optimal_replacement: the cost-optimal age-replacement interval from a non-repairable model (model_id, or \
distribution_id + params) and the planned and unplanned costs. beneficial=false: run to failure is cheaper.
- analyse failure_finding_interval: the proof-test interval keeping a hidden protective function (relief valve, trip, \
standby unit) at a target availability.
- analyse optimal_overhaul: the overhaul interval of a repairable system from a minimal-repair recurrent model.
- analyse calendar_replacement: when replacing costs less at shuts (annual, quarterly, weekly stops) than between \
them, the long-run best rule: at each shut, replace the part if it is older than a threshold age (the threshold \
depends on when the next cheaper shut comes). Give the model in a time unit, the shuts (name, cost, every N \
days/weeks/months/years from a start date, or dates), failure_cost and anytime_cost (a planned replacement between \
shuts; omit when only shuts allow one). Today is time 0; months are 365.25/12 days. Back: cost_rate (per model \
unit) and cost_per_year, the rule in words, by_kind (replacements and cost a year per shut kind and failures), \
comparisons (run to failure, age replacement ignoring the shuts, every shut of a kind) and the next 12 months' \
shuts with each one's threshold and chance of a replacement. method dp (default) and integration (no anytime_cost) \
are exact and free; sampling (Pro) is for calendars whose cycle is very long, with cost_rate_se. Quote the unit.
- analyse next_replacement: the same calendar plus the age of the unit in service today: replace it now, at the \
next shut of each kind, between shuts, or run it to failure, each choice's cost, the best, and replace_from_age \
(from that age replacing now beats waiting).
- With a saved Weibull (or Crow-AMSAA) model fitted to data, shape_uncertainty gives the answer at each end of \
the shape's 90% interval: relay uncertainty_note when present — the recommendation is less firm than it reads \
(for a protective function, the shorter interval is the safe side).
- A whole diagram's intervals together: analyse rbd_optimise_intervals. A demonstration test or a B-life \
check: analyse plan_demonstration_test / check_life_requirement. Fleets: guide topic fleets."""),

    "fleets": ("Fleet failure forecasts and their email alerts (Pro).", """\
Fleets (Reliafy Pro).
- A fleet is in-service items run against one saved model; the app creates them and usage arrives through \
the ingest API. list kind fleets lists them (model_kind life, regression, alt or recurrent).
- analyse fleet_forecast: expected failures over the horizon with a 90% range (P5–P95), per period and per item (the \
top 20 unless include_items; item_probabilities adds each item's chance by period). Recurrent fleets count every \
repeat failure: an item named as a system in the model's data uses its own history (rate_factor; imperfect repair \
simulated from its state), and the range carries the fit's uncertainty; covariate recurrent models aren't taken.
- Spares: fleet_forecast with spares = {lead_time (in the fleet's periods), service_level (default 0.95), review, \
per_failure, stock, unit_cost} (or the fleet's saved spares settings) adds spares: hold (the stock for that chance \
of no stock-out over the lead time plus review), reorder_at, risk_at_stock, hold_cost, the same per period, and \
risk_curve ([stock, chance of running out]). repairable with turnaround: the pool covers the repair turnaround \
(one site). Read off the forecast's own distribution, not a normal approximation.
- Alerts: list kind fleet_alerts reads a fleet's rules with their current values; change fleet_create_alert adds one \
(above a threshold, a percent change, or x failures within y periods), checked whenever usage arrives, emailing \
the user once per crossing; at most 10 per fleet, own fleets only."""),

    "uploads": ("Sending files: the upload link, its fallbacks, inspecting and importing.", """\
Files (BlockSim / Open-PSA / Galileo / RePyability diagrams, Excel workbooks, CSVs of failure times or \
outages). Never read a file into your context to paste it while the upload link works.
1. change upload_create (purpose: rbd_import, excel, dataset, outage_log, or document for a PDF to keep; filename): a single-use URL (15 minutes) \
and a ready curl PUT. Run it from a shell that can read the file.
2. If the PUT can't connect or a proxy refuses the host (e.g. CONNECT 403), retry the same PUT once on \
url_fallback (curl_fallback): the same link on reliafy.com, slower for large files, still unused after a \
refused attempt.
3. If that fails too (no network), don't retry: a small text file (at most 200 KB) can be passed as text instead \
(change dataset_upload csv, change rbd_upload_outage_log csv, change import_rbd content for Open-PSA XML, Galileo or \
RePyability JSON); any other file of up to a few hundred KB (an .xlsx, a BlockSim project) goes through this \
connection with change upload_send_part (base64 parts 0, 1, 2… into the same upload_id, last=true with sha256 on the \
final one; not counted against the Free allowance), then import as usual (an FMEA / RCM worksheet goes onto a \
position's RCM with change import_excel target rcm and position_id). Anything larger: ask the user to upload it in the app (create's \
fallback says where).
4. get kind upload shows a workbook's sheets, columns and a guessed mapping, or a diagram file's diagrams.
5. Import with the upload_id: change import_rbd (diagrams; save=false previews with edges and cut sets; only \
picks diagrams by name; time_unit when the file states none), change import_excel (target dataset, rcm with a position_id, or \
rbd_template), change dataset_upload, or change rbd_upload_outage_log.
Relay the import notes: they say what was approximated. Blocks imported without a non-repairable model (needs_model) \
need one before analysis: ask the user, don't invent values."""),

    "sharing": ("Share links and reports: read-only pages anyone with the URL can open.", """\
Sharing (only when the user asks; confirm before publishing anything).
- change share_link publishes a read-only page of one of the user's own items (model, dataset, rbd, \
degradation_model, strategy_analysis, fleet, recurrent_model) that anyone with the URL can open \
without an account. password=true: Reliafy generates a passphrase, returned once — tell the user to send the \
link and the passphrase to the recipient separately. expires_in_days for a link that ends; label says who it's \
for. Samples can't be shared (change rbd_clone one first).
- change share_report puts several items on one print-ready page with a title, an author line, an \
introduction and a note per item. Write the notes from the items' results, quoting their figures as the tools \
returned them.
- list kind share_links shows the live links; change share_revoke ends one at once."""),

    "workspace": ("Reading, tidying and deleting saved items; what changed.", """\
The workspace.
- Reads: list kind models / datasets / rbds / fleets / share_links / rbd_runs, and get kind model \
/ dataset (a page of rows at a time; part=measurements for a dataset's readings) / rbd / rbd_run / job / \
upload. Shared samples are listed (is_sample) and readable, never changed.
- A dataset is one document: its life data (its table) and, when added, its measurements (readings on the \
same units at ages since new; change dataset_add_measurements / dataset_remove_measurements). The list shows a \
measurements entry where there is one. Datasets never point at each other: readings for a dataset's units \
go on that dataset.
- list kind workspace_changes: what changed over a period (since a date or the last visit, or days), computed \
from what Reliafy stores: new and changed items, refits that moved B10 or MTTF, moved forecasts, fired alerts, \
RCM evidence changes, moved simulations. Start from its sentence; report not_compared as unknown, never guess.
- Tidying: change model_update / change dataset_update rename or annotate (never the data or the fit).
- Deleting: change model_delete, change dataset_delete, change rbd_delete — permanent, own items only. Only on the user's \
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
whether simulation is included. It, guide, get kind upgrade_link, change upload_send_part and library lookups are never counted.
- When a tool says a limit or the plan stops it, tell the user plainly what it says — the limit, when it \
resets, how to upgrade — and don't retry. Calls refused that way aren't counted.
- Without Pro, fit locally with SurPyval (pip install surpyval; 0 = failed, 1 = still running) and save the \
parameters with change model_save; run a diagram's simulation locally with analyse rbd_export_python.
- get kind upgrade_link gives the user a Stripe payment link to open themselves; nothing is charged until they complete \
it. Never say an upgrade has happened."""),

    "maintainability": ("Maintainability prediction: Mct, M_max and availability from a parts list's repair times.", """\
Maintainability prediction (free on every plan).
- What it answers: how long corrective maintenance takes on a system, from its parts list. For each line give \
its repair time by element, in minutes or hours (unit): isolation (finding the fault), access (getting to it), \
replace (remove and replace), restore (reassembling) and checkout (proving it works); or just mttr when it \
isn't split. quantity is how many of that line are in one system.
- Weights: each line counts by how often it's the one repaired, its failure_rate × quantity. Give failure_rate \
on every line (failure_rate_unit: per_million_hours by default, or per_hour), or product_id with a saved \
reliability prediction for that product (its rates are taken where a line's ref or name matches). With any line \
still without a rate, every line counts the same; the result's weights.source and weights.note say which was \
used — relay them.
- Results: mct, the mean corrective maintenance time Σ(λ·q·MTTR)/Σ(λ·q); elements, where the time goes; \
pareto, each line's share of the maintenance time (λ·q·MTTR/Σ), largest first with cumulative; assemblies, the \
roll-up for lines whose assembly is given ('Propulsion › Motor 1' counts under Propulsion and under Motor 1); \
availability, the inherent availability MTBF/(MTBF+Mct) when the rates give a system MTBF (1/Σλ·q) or mtbf \
(hours) is given; m_max, the time by which the percentile's share of repairs (0.95 by default) is done.
- M_max needs a spread on the lines: sigma (the lognormal sigma of ln t; repair times are usually 0.3 to 1.0), \
or maximum, the time that share of the line's repairs is done by (e.g. twice its MTTR). Each line's repair time \
is taken as lognormal with its MTTR as the mean and that spread; the system's repair time is the mix of the \
lines' weighted by λ·q, and m_max is that mix's percentile. A line with no spread counts as always taking its \
MTTR; with no spread anywhere m_max is null and m_max_note says why. Say which lines lack one.
- Always quote the unit (results are in the lines' unit; mct_hours and mtbf_hours are in hours). Never invent \
repair times or failure rates: ask, or use the product's saved reliability prediction.
- analyse maintainability saves nothing; change maintainability_save keeps it (name, the same arguments), \
change maintainability_update renames it or gives it new lines, change maintainability_delete removes it; get \
kind maintainability_prediction and list kind maintainability_predictions read them (samples included)."""),
}
