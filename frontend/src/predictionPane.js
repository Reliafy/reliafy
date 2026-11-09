// "Add a prediction (parts count)…" in the Explorer's table area (PredictionPane.jsx): its heading,
// whether anything was changed since it opened, what each parts-list line uses, and the server's
// result in the words the result panel shows. The arithmetic is the server's
// (reliability_prediction.py); these only read it.
import { predictionAssign } from "./explorerModels.js";
import { fmtHours, fmtPerMillion, fmtQuantity, fmtReliability, partTypeMode } from "./predictions.js";

export const predictionTitle = (link = null) => (link ? "Refresh the prediction" : "Add a prediction");

// The mission time typed, in hours, or null (blank, zero or not a number).
export function missionHours(mission) {
  const s = String(mission ?? "").trim();
  const n = Number(s);
  return s !== "" && Number.isFinite(n) && n > 0 ? n : null;
}

// The prediction's own choices, in a form that compares: the environment, the mission time and
// what each line is given (a part type and quality factor, a rate, or left out).
export function predictionKey({ environment = "", mission = "", lines = [] } = {}) {
  return JSON.stringify({ environment: environment || "", mission: missionHours(mission), assign: predictionAssign(lines || []) });
}

// What a line uses: "excluded" (not electronic, left out), "rate" (a rate of the user's own), or
// "type" (a handbook part type, chosen or still to choose).
export const lineMode = (l = {}) => partTypeMode({
  record: l.record?.id ? l.record : l.record_id ? { id: l.record_id } : null,
  rate: l.rate_per_million_hours, rateMode: l.rate_mode, excluded: l.excluded,
});

// A change from the shared part-type controls (PartTypeCell.jsx: {record?, rate?, rateMode?,
// excluded?}) as the line's own fields.
export function lineChange(c = {}) {
  return {
    ...("record" in c ? { record: c.record, record_id: c.record ? c.record.id : null } : {}),
    ...("rate" in c ? { rate_per_million_hours: c.rate } : {}),
    ...("rateMode" in c ? { rate_mode: c.rateMode } : {}),
    ...("excluded" in c ? { excluded: c.excluded } : {}),
  };
}

const named = (l) => (Number(l.quantity) !== 1 && l.quantity != null ? `${l.name} ×${fmtQuantity(l.quantity)}` : l.name);

// The result panel: the total failure rate (per 10⁶ h), the MTBF (hours), the reliability over the
// mission time when one is typed (the server works it out at its default otherwise, which isn't
// shown), how many lines count, and the lines left out (not electronic; no part type yet).
export function predictionResult(result, mission = "") {
  if (!result) return null;
  const rate = result.failure_rate_per_million_hours || 0;
  const t = missionHours(mission);
  const counts = result.counts || {};
  const sameMission = t != null && Number(result.mission_time_hours) === t;
  return {
    rate: rate > 0 ? fmtPerMillion(rate) : null,
    mtbf: rate > 0 && result.mtbf_hours != null ? fmtHours(result.mtbf_hours) : null,
    reliability: rate > 0 && sameMission && result.reliability_at_mission != null ? fmtReliability(result.reliability_at_mission) : null,
    mission: t != null ? fmtHours(t) : null,
    counted: `${counts.assigned || 0} of ${counts.lines || 0} line${counts.lines === 1 ? "" : "s"} counted`,
    environment: result.environment?.name ? `${result.environment.name} (${result.environment.code})` : "",
    notElectronic: (result.excluded || []).map(named),
    noType: (result.unassigned || []).map(named),
  };
}
