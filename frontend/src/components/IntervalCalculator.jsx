import { useEffect, useRef, useState } from "react";
import Modal from "./Modal.jsx";
import "./IntervalCalculator.css";
import Field from "./ui/Field.jsx";
import InputGroup from "./ui/InputGroup.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import { saveErrorText } from "../confirm.js";
import {
  getFailureModeIntervalInputs, getModel, listModels, optimalReplacement, rcmFailureFindingInterval, rcmOnConditionInterval,
} from "../api.js";
import { savedModelRef } from "../modelNext.js";
import { modeAnswers } from "../decisionCheck.js";
import { formatCost } from "../money.js";
import { tabPlace } from "../explorerTabs.js";
import {
  ANALYSIS_KIND, TASK_COST_FIELD, TIME_UNITS, analysisName, taskCostWords, answerUnitWords, calculatorFor, isUseUnit, money, num, pct, pfUnits, rationale, roundDown, taskUnit, withUnit,
} from "../rcmIntervals.js";

// "Calculate…" on an RCM task card (RcmModeTasks): how often to do the task, worked out
// by the calculator its kind calls for (Derryn, 9 Nov 2026: "the RCM calculation functions
// in the RePyability package"):
//
//   on condition     the P-F calculator (RePyability's optimal_on_condition_interval)
//   failure finding  the test interval (optimal_failure_finding_interval, failure_finding)
//   fixed interval   the Strategy replacement calculator (optimal age replacement)
//
// One or two plain sentences say what it works out before any number; the inputs start
// from the failure mode's evidence and its position's failures where there are some (each
// says where it came from; "assumed" where the dialog chose it) and can all be changed.
// "Use N unit" hands the rounded interval, the rationale paragraph and the analysis to save
// to `onUse` ({value, unit, line, analysis: {kind, name, inputs}}), which writes them.
//
//   r      the failure mode's row        task   the task (its interval and unit now)
//   kind   the task's outcome            onUse  async; a refusal shows here

const blank = (v) => v === "" || v == null;
const n = (v) => (blank(v) ? null : Number(v));

export default function IntervalCalculator({ r, task, kind, onClose, onUse }) {
  const calc = calculatorFor(kind);
  const [form, setForm] = useState(() => startForm(calc.key, task));
  const [from, setFrom] = useState({}); // where a prefilled value came from, by field
  const [models, setModels] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  // On a safety or environmental failure the task must make the risk tolerable whatever it
  // costs: the cost inputs wait behind "Show costs" (Derryn, 9 Nov 2026).
  const safety = ["safety", "environmental"].includes(modeAnswers(r.ref).consequence);
  const [showCosts, setShowCosts] = useState(!safety);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  const set = (k) => (e) => { const v = e.target.value; setForm((f) => ({ ...f, [k]: v })); setResult(null); };

  useEffect(() => {
    let on = true;
    getFailureModeIntervalInputs(r.ref.id, task?.id).then((got) => { if (on) prefill(got); }, () => {});
    if (calc.key !== "pf") {
      listModels().then((out) => {
        if (on) setModels((out.models || []).filter((m) => m.kind === "distribution"));
      }, () => { if (on) setModels([]); });
    }
    return () => { on = false; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function prefill(got) {
    const said = {};
    setForm((f) => {
      const next = { ...f };
      // The task's own cost each time comes first (its Maintenance tab's figure): never asked again.
      const costField = TASK_COST_FIELD[calc.key];
      if (task?.id && costField) {
        if (got.task_cost?.amount != null && blank(f[costField])) next[costField] = String(got.task_cost.amount);
        said[costField] = taskCostWords(got.task_cost, (v) => formatCost(v, undefined, { sig: 4 }));
      }
      const rate = got.onset_rate;
      if (rate?.rate && blank(f.onset_rate)) {
        next.onset_rate = String(Number(rate.rate.toPrecision(3)));
        said.onset_rate = `From ${rate.text}.`;
      }
      if (calc.key === "ff") {
        if (got.device?.distribution_id) {
          next.device = "model";
          next.model = got.device;
          said.device = `From ${got.device.name ? `“${got.device.name}”` : "the linked model"}.`;
        } else if (rate?.rate && blank(f.failure_rate)) {
          next.failure_rate = String(Number(rate.rate.toPrecision(3)));
          said.failure_rate = `From ${rate.text}.`;
        }
      }
      if (calc.key === "fixed" && got.life_model?.distribution_id) {
        next.model = got.life_model;
        said.model = got.life_model.source === "position"
          ? `From the position's model, “${got.life_model.name}” (${tabPlace("models")}).`
          : `From the decision's evidence, “${got.life_model.name}”.`;
        if (got.costs?.planned_cost != null && blank(f.planned_cost)) next.planned_cost = String(got.costs.planned_cost);
        if (got.costs?.unplanned_cost != null && blank(f.unplanned_cost)) next.unplanned_cost = String(got.costs.unplanned_cost);
      }
      if (calc.key === "pf" && got.pf) said.pf_interval = got.pf.text;
      const prev = got.previous?.inputs;
      if (prev && got.previous.kind === ANALYSIS_KIND[calc.key]) {
        for (const [k, v] of Object.entries(prev)) if (k in next && blank(next[k]) && !blank(v)) next[k] = String(v);
      }
      return next;
    });
    setFrom(said);
  }

  // A saved model chosen from the list: read in full (its parameters), then `then(model)`.
  const pick = (id, then) => {
    if (!id || id === "__given") return;
    setResult(null);
    getModel(id).then((m) => { if (alive.current) then(modelOf(savedModelRef({ ...m, id }))); },
      (e) => { if (alive.current) setFailed(saveErrorText(e, { offline: navigator.onLine === false })); });
  };

  // What the calculator is sent, from the form (null for a blank).
  const body = () => {
    if (calc.key === "pf") {
      return {
        pf_interval: n(form.pf_interval), pf_unit: form.pf_unit, act_time: n(form.act_time),
        ...(priced() && !isUseUnit(form.pf_unit) ? {
          onset_rate: n(form.onset_rate), inspection_cost: n(form.inspection_cost), found_cost: n(form.found_cost),
          failure_cost: n(form.failure_cost),
        } : {}),
        detection_probability: blank(form.detection_probability) ? 1 : n(form.detection_probability) / 100,
        ...(task?.interval && (TIME_UNITS.includes(taskUnit(task.unit)) || taskUnit(task.unit) === taskUnit(form.pf_unit))
          ? { current_interval: task.interval, current_unit: taskUnit(task.unit) } : {}),
      };
    }
    if (calc.key === "ff") {
      const device = form.device === "model" && form.model
        ? { distribution_id: form.model.distribution_id, params: form.model.params, model_unit: form.model.unit || null, extras: form.model.extras || null }
        : { failure_rate: n(form.failure_rate) };
      return {
        ...device, target_unavailability: blank(form.target) ? null : n(form.target) / 100,
        ...(showCosts ? {
          test_cost: n(form.test_cost) ?? 0, repair_cost: n(form.repair_cost) ?? 0, demand_rate: n(form.demand_rate),
          consequence_cost: n(form.consequence_cost) ?? 0,
        } : {}),
        ...(task?.interval && TIME_UNITS.includes(taskUnit(task.unit)) ? { current_interval: task.interval, current_unit: taskUnit(task.unit) } : {}),
      };
    }
    return { model: form.model, planned_cost: n(form.planned_cost), unplanned_cost: n(form.unplanned_cost) };
  };

  // Costs given (shown and any typed): they add the cost-optimal interval, never change the P-F one.
  const priced = () => showCosts && [form.inspection_cost, form.found_cost, form.failure_cost].some((v) => !blank(v));
  const missing = () => {
    if (calc.key === "pf") {
      if (blank(form.pf_interval)) return "Enter the P-F interval: how long from the first sign to the failure.";
      if (priced() && (blank(form.inspection_cost) || blank(form.found_cost) || blank(form.failure_cost))) {
        return "Enter all three costs for the cost-optimal interval, or none for the interval from the P-F alone.";
      }
      if (priced() && blank(form.onset_rate)) return "The cost-optimal interval needs how many failures a year to expect if nothing is done.";
      return null;
    }
    if (calc.key === "ff") {
      if (form.device !== "model" && blank(form.failure_rate)) return "Enter the device's failure rate, a year.";
      if (blank(form.target) && (!showCosts || blank(form.test_cost) || blank(form.demand_rate) || blank(form.consequence_cost))) {
        return "Give a target unavailability, or the test cost, the demand rate and the cost of a demand on a failed device.";
      }
      return null;
    }
    if (!form.model) return "Choose the non-repairable model of the part's life.";
    if (blank(form.planned_cost) || blank(form.unplanned_cost)) return "Enter the planned and unplanned costs.";
    return null;
  };

  const work = async () => {
    const why = missing();
    if (why) { setFailed(why); return; }
    setBusy(true);
    setFailed(null);
    try {
      const b = body();
      let out;
      if (calc.key === "pf") out = await rcmOnConditionInterval(b);
      else if (calc.key === "ff") out = await rcmFailureFindingInterval(b);
      else {
        const m = b.model;
        out = await optimalReplacement(m.distribution_id, m.params, b.planned_cost, b.unplanned_cost, m.unit, m.extras);
      }
      if (alive.current) setResult({ out, sent: b });
    } catch (e) {
      if (alive.current) setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  const use = useOf(calc.key, result);
  const cheapest = result?.out?.cost_optimal?.recommended && !sameUse(result.out.cost_optimal.recommended, use)
    ? { ...result.out.cost_optimal.recommended, cheapest: true } : null;
  const apply = async (chosen = use) => {
    if (!chosen || busy) return;
    const use = chosen;
    setBusy(true);
    setFailed(null);
    const sent = result.sent;
    const inputs = calc.key === "fixed"
      ? { distribution_id: sent.model.distribution_id, params: sent.model.params, planned_cost: sent.planned_cost,
          unplanned_cost: sent.unplanned_cost, unit: sent.model.unit || null, extras: sent.model.extras || null }
      : { ...Object.fromEntries(Object.entries(sent).filter(([, v]) => v !== null)), unit: use.unit };
    const line = rationale(calc.key, { ...sent, target_assumed: form.targetAssumed && Number(form.target) === 1,
      model_name: sent.model?.name }, result.out, use);
    try {
      await onUse({ ...use, line, analysis: { kind: ANALYSIS_KIND[calc.key], name: analysisName(r.ref.text, calc.key), inputs } });
    } catch (e) {
      if (alive.current) { setBusy(false); setFailed(saveErrorText(e, { offline: navigator.onLine === false })); }
    }
  };

  return (
    <Modal title={calc.title} onClose={onClose} locked={busy} trapFocus className="ivc-dialog"
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
               {cheapest && (
                 <button type="button" className="secondary" onClick={() => apply(cheapest)} disabled={busy}>
                   Use the cheapest, {withUnit(cheapest.value, cheapest.unit)}
                 </button>
               )}
               <button type="button" onClick={() => apply()} disabled={!use || busy} aria-busy={busy || undefined}>
                 {use ? `Use ${withUnit(use.value, use.unit)}` : "Use"}
               </button>
             </>
           )}>
      <p className="ivc-what">{WHAT[calc.key]}</p>
      <form className="ivc-form" onSubmit={(e) => { e.preventDefault(); work(); }}>
        {calc.key === "pf" && (
          <>
            <Field label="P-F interval" help={from.pf_interval || "From the first sign you can detect (a noise, a rise in temperature) to the failure."} as="fieldset">
              <InputGroup label="P-F interval">
                <TextInput type="number" inputMode="decimal" min="0" step="any" value={form.pf_interval} onChange={set("pf_interval")} aria-label="P-F interval" placeholder="e.g. 10" />
                <Select value={form.pf_unit} onChange={set("pf_unit")} aria-label="P-F interval unit">
                  {pfUnits(task).map((u) => <option key={u} value={u}>{u}{isUseUnit(u) ? " (use)" : ""}</option>)}
                </Select>
              </InputGroup>
            </Field>
            <Field label="Time needed to act" optional as="fieldset"
                   help="From finding the warning to the fix being done (ordering the part, planning the shutdown), in the P-F interval's unit. When the P-F interval less this is shorter than half of it, that's the limit.">
              <TextInput type="number" inputMode="decimal" min="0" step="any" value={form.act_time} onChange={set("act_time")} aria-label="Time needed to act" placeholder="0" />
            </Field>
            {!isUseUnit(form.pf_unit) && (
              <CostsToggle safety={safety} show={showCosts} onShow={() => { setShowCosts(true); setResult(null); }}
                           words="Costs only matter for whether the check pays for itself, not for the P-F interval; add them to see the cost-optimal interval." />
            )}
            {showCosts && !isUseUnit(form.pf_unit) && (
              <>
                <Field label="Failures a year, if nothing is done" optional help={from.onset_rate || "How often the warning (and so the failure) starts, e.g. 0.5 for once in two years. Needed with the costs."}>
                  <TextInput type="number" inputMode="decimal" min="0" step="any" value={form.onset_rate} onChange={set("onset_rate")} placeholder="e.g. 0.5" />
                </Field>
                <div className="ivc-row">
                  <Field label="Cost of a check ($)" optional help={from.inspection_cost || null}><TextInput type="number" inputMode="decimal" min="0" step="any" value={form.inspection_cost} onChange={set("inspection_cost")} placeholder="e.g. 20" /></Field>
                  <Field label="Cost when found ($)" optional help="The planned fix."><TextInput type="number" inputMode="decimal" min="0" step="any" value={form.found_cost} onChange={set("found_cost")} placeholder="e.g. 200" /></Field>
                  <Field label="Cost of a failure ($)" optional help="Unplanned, all in."><TextInput type="number" inputMode="decimal" min="0" step="any" value={form.failure_cost} onChange={set("failure_cost")} placeholder="e.g. 2000" /></Field>
                </div>
              </>
            )}
            <Field label="Chance a check finds the warning (%)" help={Number(form.detection_probability) === 100 ? "Assumed: every check finds a warning that's there. Lower it for a check that can miss." : null}>
              <TextInput type="number" inputMode="decimal" min="1" max="100" step="any" value={form.detection_probability} onChange={set("detection_probability")} />
            </Field>
          </>
        )}
        {calc.key === "ff" && (
          <>
            {form.device === "model" && form.model ? (
              <Field label="The device's life" help={from.device || null}>
                <p className="ivc-model">
                  {form.model.name || "Linked model"} ({form.model.unit || "no unit"}) ·{" "}
                  <button type="button" className="link" onClick={() => { setForm((f) => ({ ...f, device: "rate" })); setResult(null); }}>Type a failure rate instead</button>
                </p>
              </Field>
            ) : (
              <Field label="The device's failure rate (failures a year)" help={from.failure_rate || "Its hidden failures, e.g. 0.1 for one in ten years."}>
                <TextInput type="number" inputMode="decimal" min="0" step="any" value={form.failure_rate} onChange={set("failure_rate")} placeholder="e.g. 0.1" />
              </Field>
            )}
            {form.device !== "model" && models?.length > 0 && (
              <Field label="Or a model of its life" optional>
                <Select value="" onChange={(e) => pick(e.target.value, (model) => {
                  setForm((f) => ({ ...f, device: "model", model })); setFrom((s) => ({ ...s, device: null }));
                })}>
                  <option value="">Choose a non-repairable model…</option>
                  {models.map((m) => <option key={m.id} value={m.id}>{m.name}{m.unit ? ` (${m.unit})` : ""}</option>)}
                </Select>
              </Field>
            )}
            <Field label="Target unavailability (%)" optional
                   help={form.targetAssumed && Number(form.target) === 1
                     ? "Assumed: 1% (failed when needed at most 1 time in 100) is a common starting point for safety. Clear it to find the cheapest interval instead."
                     : "The most it may be failed when needed. Blank: the cheapest interval, from the costs."}>
              <TextInput type="number" inputMode="decimal" min="0" max="100" step="any" value={form.target}
                         onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, target: v, targetAssumed: false })); setResult(null); }} />
            </Field>
            <CostsToggle safety={safety} show={showCosts} onShow={() => { setShowCosts(true); setResult(null); }}
                         words="Costs are optional: the target alone gives the interval. Add them to see the cheapest interval too." />
            {showCosts && (
              <>
                <div className="ivc-row">
                  <Field label="Cost of a test ($)" optional help={from.test_cost || null}><TextInput type="number" inputMode="decimal" min="0" step="any" value={form.test_cost} onChange={set("test_cost")} /></Field>
                  <Field label="Cost of a repair ($)" optional><TextInput type="number" inputMode="decimal" min="0" step="any" value={form.repair_cost} onChange={set("repair_cost")} /></Field>
                </div>
                <div className="ivc-row">
                  <Field label="Demands a year" optional help="How often it's needed (the trip, the relief)."><TextInput type="number" inputMode="decimal" min="0" step="any" value={form.demand_rate} onChange={set("demand_rate")} /></Field>
                  <Field label="Cost of a demand on a failed device ($)" optional><TextInput type="number" inputMode="decimal" min="0" step="any" value={form.consequence_cost} onChange={set("consequence_cost")} /></Field>
                </div>
              </>
            )}
          </>
        )}
        {calc.key === "fixed" && (
          <>
            <Field label="The part's life" help={from.model || (form.model ? null : "A non-repairable model fitted to its failures.")}>
              {models === null && !form.model ? <p className="ivc-model">Reading your models…</p> : (
                <Select value={form.model?.model_id || (form.model ? "__given" : "")}
                        onChange={(e) => pick(e.target.value, (model) => setForm((f) => ({ ...f, model })))}>
                  {!form.model && <option value="">Choose a non-repairable model…</option>}
                  {form.model && !form.model.model_id && <option value="__given">{form.model.name || "From the evidence"}</option>}
                  {(models || []).map((m) => <option key={m.id} value={m.id}>{m.name}{m.unit ? ` (${m.unit})` : ""}</option>)}
                </Select>
              )}
            </Field>
            <div className="ivc-row">
              <Field label="Planned replacement ($)" help={from.planned_cost || null}><TextInput type="number" inputMode="decimal" min="0" step="any" value={form.planned_cost} onChange={set("planned_cost")} placeholder="e.g. 150" /></Field>
              <Field label="Replacement after a failure ($)"><TextInput type="number" inputMode="decimal" min="0" step="any" value={form.unplanned_cost} onChange={set("unplanned_cost")} placeholder="e.g. 400" /></Field>
            </div>
          </>
        )}
        {answerUnitWords(calc.key, form) && <p className="ivc-unit lib-date">{answerUnitWords(calc.key, form)}</p>}
        <div className="ivc-go">
          <button type="submit" className="secondary" disabled={busy}>{busy && !result ? "Working it out…" : result ? "Work it out again" : "Work it out"}</button>
        </div>
      </form>
      {failed && <p className="field-error" role="alert">{failed}</p>}
      {result && <Result k={calc.key} out={result.out} task={task} use={use} />}
    </Modal>
  );
}

const WHAT = {
  pf: "A failure often gives a warning first: a noise, a leak, a rise in temperature. The time from that first sign to the failure is the P-F interval. "
    + "Checking at least every half P-F interval finds the warning with time to act; that's all this needs.",
  ff: "A protective device (a trip, a relief valve, a standby pump) can fail without anyone knowing; only a test shows it. "
    + "This finds the longest time between tests that keeps the chance it's failed when needed within your target, or else the cheapest.",
  fixed: "Replacing a wearing part on a schedule costs less than waiting for it to fail only when failures cost more than planned replacements. "
    + "This finds the replacement age with the lowest cost over time, against running it to failure.",
};

function startForm(key, task) {
  if (key === "pf") {
    return { pf_interval: "", pf_unit: isUseUnit(task?.unit) ? taskUnit(task.unit) : "weeks", act_time: "", onset_rate: "", inspection_cost: "", found_cost: "", failure_cost: "", detection_probability: "100" };
  }
  if (key === "ff") {
    return { device: "rate", model: null, failure_rate: "", target: "1", targetAssumed: true, test_cost: "", repair_cost: "", demand_rate: "", consequence_cost: "" };
  }
  return { model: null, planned_cost: "", unplanned_cost: "" };
}

function modelOf(ref) {
  return { model_id: ref.modelId, name: ref.name, distribution_id: ref.distribution_id, params: ref.params, extras: ref.extras || null, unit: ref.unit || "" };
}

// "an hour", "a day": a cost rate per one of the unit.
const perOne = (unit) => {
  const one = String(unit || "").replace(/s$/, "") || "unit";
  return `${/^(hour|h$)/i.test(one) ? "an" : "a"} ${one}`;
};

// The interval "Use" writes: the calculator's rounded one, or (fixed) the optimal age rounded down in the model's unit.
const sameUse = (a, b) => !!a && !!b && Number(a.value) === Number(b.value) && a.unit === b.unit;

// The cost inputs' header: on a safety or environmental failure, a "Show costs" link and why
// they don't decide the task; otherwise a line saying what they add.
function CostsToggle({ safety, show, onShow, words }) {
  if (safety && !show) {
    return (
      <p className="ivc-costs">
        A safety or environmental failure: the task must make the risk tolerable whatever it costs.{" "}
        <button type="button" className="link" onClick={onShow}>Show costs</button>
      </p>
    );
  }
  return <p className="ivc-costs">{words}</p>;
}

function useOf(key, result) {
  if (!result) return null;
  const out = result.out;
  if (key === "fixed") {
    if (!out.beneficial || out.optimal_time == null) return null;
    const value = roundDown(out.optimal_time);
    const unit = taskUnit(out.unit) || "hours";
    return value ? { value, unit } : null;
  }
  return out.recommended ? { value: out.recommended.value, unit: out.recommended.unit } : null;
}

function Result({ k, out, task, use }) {
  const yours = task?.interval ? withUnit(task.interval, task.unit) : null;
  if (k === "pf") {
    const at = out.at_recommended;
    const c = out.cost_optimal;
    const priced = out.run_to_failure_cost_rate != null;
    return (
      <div className="ivc-result" role="status">
        <p className="ivc-answer">{out.summary}</p>
        <dl className="ivc-facts">
          <dt>{out.basis === "net_pf" ? "Net P-F interval" : "Half the P-F interval"}</dt>
          <dd>{withUnit(out.interval, out.unit)} (rounded down to {withUnit(use.value, use.unit)})</dd>
          {at.detection_probability < 0.9999 && <><dt>Warnings found in time</dt><dd>{pct(at.detection_probability)}</dd></>}
          {priced && <><dt>Cost a year there</dt><dd>{money(at.cost_rate)}, against {money(out.run_to_failure_cost_rate)} letting it fail</dd></>}
          {c && <><dt>Cheapest interval</dt><dd>{withUnit(c.interval, c.unit)}: {money(c.at_recommended.cost_rate)} a year at {withUnit(c.recommended.value, c.recommended.unit)}</dd></>}
          {out.current && (
            <><dt>Yours now</dt><dd>
              {yours}{out.current.within ? " (within the P-F limit)" : " (longer than the P-F limit: warnings can be missed)"}
              {out.current.cost_rate != null ? `, ${money(out.current.cost_rate)} a year` : ""}
            </dd></>
          )}
        </dl>
        {!priced && <p className="rw-fhelp">Costs only matter for whether the check pays for itself, not for the P-F interval.</p>}
      </div>
    );
  }
  if (k === "ff") {
    const at = out.at_recommended;
    return (
      <div className="ivc-result" role="status">
        <p className="ivc-answer">{out.summary}</p>
        <dl className="ivc-facts">
          {out.current && (
            <><dt>Yours now</dt><dd>
              {yours} → {pct(out.current.mean_unavailability)} unavailability
              {out.current.meets_target === false ? " (misses the target)" : out.current.meets_target ? " (meets the target)" : ""}
            </dd></>
          )}
          <dt>{out.basis === "target" ? `Longest that meets ${pct(out.target_unavailability)}` : "Cheapest interval"}</dt>
          <dd>{withUnit(out.interval, out.unit)} (rounded down to {withUnit(use.value, use.unit)})</dd>
          <dt>Failed when needed</dt><dd>{pct(at.mean_unavailability)} of the time at {withUnit(use.value, use.unit)}</dd>
          {at.cost_rate != null && <><dt>Cost a year</dt><dd>{money(at.cost_rate)}</dd></>}
          {out.cost_optimal && (
            <><dt>Cheapest interval</dt><dd>
              {withUnit(out.cost_optimal.interval, out.cost_optimal.unit)}: {money(out.cost_optimal.at_recommended.cost_rate)} a year
              {out.cost_optimal.meets_target ? " (meets the target)" : " (misses the target)"}
            </dd></>
          )}
          {at.multiple_failures_per_year != null && <><dt>Demands on a failed device</dt><dd>{num(at.multiple_failures_per_year)} a year</dd></>}
        </dl>
      </div>
    );
  }
  const unit = taskUnit(out.unit);
  return (
    <div className="ivc-result" role="status">
      <p className="ivc-answer">{out.recommendation}</p>
      {out.beneficial && (
        <dl className="ivc-facts">
          <dt>Best age</dt><dd>{withUnit(out.optimal_time, unit)} (rounded down to {withUnit(use.value, use.unit)})</dd>
          <dt>Cost rate</dt><dd>{money(out.optimal_cost_rate)} {perOne(unit)}, against {money(out.run_to_failure_cost_rate)} running to failure</dd>
          {yours && <><dt>Yours now</dt><dd>{yours}</dd></>}
        </dl>
      )}
    </div>
  );
}
