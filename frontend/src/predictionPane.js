// "Add a prediction (parts count)…" in the Explorer's table area (PredictionPane.jsx): its heading,
// whether anything was changed since it opened, what each parts-list line uses, and the server's
// result in the words the result panel shows. The arithmetic is the server's
// (reliability_prediction.py); these only read it.
import { predictionAssign } from "./explorerModels.js";
import { isCovariateId } from "./covariate.js";
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
  return JSON.stringify({ environment: environment || "", mission: missionHours(mission), assign: predictionAssign(lines || []),
    left_out: leftOutKeys(lines || []) });
}

// ---- adding, leaving out and removing lines ---------------------------------------------------

// A line's own key: its parts-list entry, else (a product's bill of materials) its part number.
export const lineKey = (l = {}) => l.listing_id || l.reference || l.part_id || "";

// The lines left out of this prediction (they stay on the parts list), as the server takes them.
export const leftOutKeys = (lines = []) => lines.filter((l) => l.left_out).map(lineKey).filter(Boolean);

// The server's result line for each of the pane's lines: the result counts only the lines not
// left out, in order; a left-out line has none.
export function resultLines(lines = [], results = null) {
  const counted = results?.lines || [];
  let i = 0;
  return lines.map((l) => (l.left_out ? null : counted[i++] || null));
}

// A line as the pane first keeps it, from the server's (its chosen part type named from the result).
export function lineFromPreview(line, result = null) {
  return {
    ...line,
    record: line.record_id ? {
      id: line.record_id, name: result?.part_type || line.record_id,
      ...(result?.covariate ? { kind: "covariate_model" } : {}),
    } : null,
  };
}

// The parts list read again (after a part was added, removed or its quantity changed): the
// server's lines, in its order, each keeping what was chosen for it here (its part type, rate,
// "Not electronic", left out); a line new to the list comes as the server gives it. `added`: the
// keys of the lines that weren't there before.
export function mergeLines(old = [], fresh = [], results = null) {
  const mine = new Map(old.map((l) => [lineKey(l), l]));
  const out = [];
  const byResult = resultLines(fresh, results);
  const added = [];
  fresh.forEach((f, i) => {
    const had = mine.get(lineKey(f));
    if (had) {
      out.push({ ...had, quantity: f.quantity, position: f.position, assembly: f.assembly, role: f.role,
        listing_id: f.listing_id, part_id: f.part_id });
    } else {
      added.push(lineKey(f));
      out.push(lineFromPreview(f, byResult[i]));
    }
  });
  return { lines: out, added };
}

// The conditions the server started a line from (those its position fixes, a sample part's own),
// taken by a line on that part type with none of its own, so Conditions… shows what its rate was
// worked out under. The same list back when nothing changes.
export function adoptConditions(lines = [], fresh = []) {
  const theirs = new Map(fresh.map((f) => [lineKey(f), f]));
  const any = (c) => !!c && Object.keys(c).length > 0;
  let changed = false;
  const out = lines.map((l) => {
    const f = theirs.get(lineKey(l));
    if (!f || !f.record_id || f.record_id !== (l.record?.id || l.record_id) || !any(f.conditions) || any(l.conditions)) return l;
    changed = true;
    const cycles = f.cycles_per_hour != null && String(l.cycles_per_hour ?? "").trim() === "";
    return { ...l, conditions: { ...f.conditions }, ...(cycles ? { cycles_per_hour: f.cycles_per_hour } : {}) };
  });
  return changed ? out : lines;
}

// The positions a part can go on, for the "On" pickers: the position and those inside it
// (the server's branch), each with the parts already on its list (so they aren't offered again).
export function branchPositions(branch = [], lines = []) {
  return branch.map((b) => ({
    ...b,
    parts_list: lines.filter((l) => l.position?.id === b.id && l.part_id)
      .map((l) => ({ part: { id: l.part_id }, role: l.role || "component" })),
  }));
}

// The empty state's words.
export const noPartsText = (name) => `No parts listed on ${name} or inside it.`;

// The confirmation before a line comes off its parts list.
export function removeQuestion(line = {}) {
  const where = line.position?.name || "its position";
  return `Remove ${line.name} from ${where}’s parts list? It also leaves the BOM and the LSA. The part itself stays in your parts.`;
}

// A line's menu (the ⋯ button and right-click): change the quantity, leave out (or put back), and
// take it off its parts list. A product's bill of materials line isn't on a parts list: only
// "leave out" applies.
export function lineMenu(line = {}) {
  const listed = !!line.listing_id;
  const why = "It comes from the product's bill of materials, not a parts list";
  return [
    { id: "quantity", label: "Change quantity", disabled: !listed, reason: listed ? undefined : why },
    line.left_out ? { id: "back", label: "Put back in this prediction" } : { id: "out", label: "Leave out of this prediction" },
    { separator: true },
    { id: "remove", label: "Remove from the parts list…", danger: true, disabled: !listed, reason: listed ? undefined : why },
  ];
}

// A quantity typed in the Qty cell: a number more than 0, or null (leave it as it was).
export function quantityTyped(text, was) {
  const n = Number(String(text ?? "").trim());
  if (!String(text ?? "").trim() || !Number.isFinite(n) || n <= 0 || n === Number(was)) return null;
  return n;
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
    // A new part type clears the last one's conditions.
    ...("record" in c && (c.record?.kind === "covariate_model" || isCovariateId(c.record?.id)) ? { conditions: {}, cycles_per_hour: "" } : {}),
    // ... and a handbook part type's own environment and grade.
    ...("record" in c ? { environment: "", quality: "" } : {}),
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
    leftOut: (result.left_out || []).map(named),
    needsConditions: (result.needs_conditions || []).map(named),
    handbooks: handbooksText(result.handbooks),
    disclaimer: result.disclaimer || null,
  };
}

// Which lines used which handbook, in a line: "MIL-HDBK-217F N2: 3 lines · NSWC-11: 1 line".
export function handbooksText(handbooks = []) {
  return (handbooks || []).map((h) => `${h.short_name}: ${h.lines.length} line${h.lines.length === 1 ? "" : "s"}`).join(" · ");
}

// A line on an NSWC-11 part type (a covariate model: it takes conditions, not a quality factor).
export const isCovariateLine = (l = {}) => l.record?.kind === "covariate_model" || isCovariateId(l.record?.id || l.record_id);

// The Conditions… button's words for a line: "Conditions…" or "Conditions (3 set)…".
export function conditionsLabel(l = {}) {
  const n = Object.values(l.conditions || {}).filter((v) => String(v ?? "").trim() !== "").length;
  return n ? `Conditions (${n} set)…` : "Conditions…";
}
