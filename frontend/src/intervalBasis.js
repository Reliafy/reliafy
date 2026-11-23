// "Interval based on" (Derryn, 23 Nov 2026: Calculate… and Based on are one idea, and "the saved
// result shouldn't be a separate page, it should just be the calculation"): one line in a task's
// panel saying what its interval rests on, from the calculation saved with it (its inputs, from
// GET …/failure-modes/<id>/interval-inputs) or its other evidence. The calculation itself opens in
// place (IntervalCalculator, inline). Pure: tested in intervalBasis.test.js.
import { everyText } from "./rcmWorksheet.js";

const num = (v) => Number(Number(v).toPrecision(4)).toLocaleString("en-GB");
const blank = (v) => v === "" || v == null;
const dollars = (v) => `$${num(v)}`;

// The line, without the evidence's status: "Every 50 hours · from a P-F interval of 120 hours".
//   task      the task (its interval now)
//   got       the interval inputs read for its failure mode (null while reading)
//   evidence  the decision's (or the member's) evidence: {artifact_name, headline?} or null; a saved
//             calculation's headline ("Check every 60 hours") leads, else the task's interval
export function basisLine(task, got, evidence = null) {
  const every = everyText(task);
  const lead = evidence?.headline || (every ? every[0].toUpperCase() + every.slice(1) : "No interval yet");
  const prev = got?.previous;
  if (prev?.kind === "on_condition_interval" && !blank(prev.inputs?.pf_interval)) {
    const i = prev.inputs;
    const act = !blank(i.act_time) && Number(i.act_time) > 0 ? `, ${num(i.act_time)} to act` : "";
    const finds = !blank(i.detection_probability) && Number(i.detection_probability) < 1
      ? `, a check finding ${Math.round(Number(i.detection_probability) * 100)}%` : "";
    const unit = i.pf_unit ? ` ${i.pf_unit}` : "";
    return { text: `${lead} · from a P-F interval of ${num(i.pf_interval)}${unit}${act}${finds}`, worked: true };
  }
  if (prev?.kind === "failure_finding_interval") {
    const i = prev.inputs || {};
    const rate = !blank(i.failure_rate) ? `${num(i.failure_rate)} failures a year` : "the device's life model";
    const target = !blank(i.target_unavailability) ? `, at most ${num(Number(i.target_unavailability) * 100)}% unavailable` : ", the cheapest";
    return { text: `${lead} · from ${rate}${target}`, worked: true };
  }
  if (got?.life_model && !blank(got.costs?.planned_cost) && !blank(got.costs?.unplanned_cost) && evidence?.artifact_name) {
    return {
      text: `${lead} · from ${got.life_model.name || "its life model"}, ${dollars(got.costs.planned_cost)} planned against ${dollars(got.costs.unplanned_cost)} a failure`,
      worked: true,
    };
  }
  if (evidence?.artifact_name) return { text: `${lead} · from ${evidence.artifact_name}`, worked: false };
  return { text: `${lead} · not worked out yet`, worked: false };
}

// The one action beside it: work it out (nothing yet) or change it.
export const basisAction = (line) => (line.worked ? "Change…" : "Work it out…");
