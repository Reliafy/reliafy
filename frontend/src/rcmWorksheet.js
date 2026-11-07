// The RCM worksheet's rows and columns, as the Explorer's RCM tab draws them
// on the asset tree (TreePane, explorerRcm.js): the RCM hierarchy as the index
// (function → functional failure → failure mode), and the worksheet's columns
// beside it (effects, consequence, decision, task, interval, the evidence
// check...). A failure mode's decision is its task, so the task is columns on
// the mode's row, not a level of its own.
//
// Pure functions (no React), tested in rcmWorksheet.test.js: the display
// built from a position's functions with each row's roll-up of what's inside
// it, the columns, the filter chips, the sort that keeps the tree, the checks
// on a cell's value (as the server checks it), and what's remembered on this
// device.

import { filterRows } from "./outlineTree.js";
import { charCount } from "./maintenanceText.js";
import { limitWords } from "./rcmStandards.js";
import { doctrineRefusal, modeAnswers } from "./decisionCheck.js";

// A function's text is a short statement (what it must do); the standard of
// performance has its own field. Kept to 200 characters where it's typed (the
// server takes longer, and a longer one saved before stays as it is).
export const FUNCTION_MAX = 200;
export const FUNCTION_NUDGE = "Keep it short. Put the performance standard in its own field.";
// The counter for a function's text being typed (`before`: its saved text).
export const functionCount = (value, before = null) => charCount(value, { max: FUNCTION_MAX, before });

// The RCM's levels, as classic RCM reads them: a function, held to its
// performance standards; each functional failure the loss of a standard (or
// of the whole function); each failure mode a cause of that loss. A standard
// is a level of the Explorer's tree (explorerRcm.js); the study worksheet
// (buildRcmDisplay) shows a function's standards on its row.
export const LEVELS = [
  { type: "fn", label: "Function", plural: "Functions", child: "standards" },
  { type: "std", label: "Performance standard", plural: "Performance standards", child: "failures" },
  { type: "fail", label: "Functional failure", plural: "Functional failures", child: "modes" },
  { type: "mode", label: "Failure mode", plural: "Failure modes", child: null },
];
export const LEVEL_OF = Object.fromEntries(LEVELS.map((l, i) => [l.type, { ...l, depth: i }]));
// The RCM in the Explorer's tree (explorerRcm.js) has three more kinds of row:
// the positions themselves, a function's functional failures that breach no
// one standard (while it has a list), and a position's failure modes under no
// functional failure yet.
LEVEL_OF.pos = { type: "pos", label: "Position", plural: "Positions", child: "functions", depth: 0 };
LEVEL_OF.nostd = { type: "nostd", label: "No performance standard", plural: "No performance standard", child: "failures", depth: 0 };
LEVEL_OF.unassigned = { type: "unassigned", label: "Not under a functional failure", plural: "Unassigned", child: "modes", depth: 0 };
// A function's failure modes placed directly under it (written on the FME(C)A
// tab, where a worksheet goes straight from a function to its modes), shown
// on the RCM tab under one group row until a functional failure is written.
LEVEL_OF.nofail = { type: "nofail", label: "No functional failure yet", plural: "No functional failure yet", child: "modes", depth: 0 };
export const NOFAIL_HINT = "Add a performance standard and a functional failure to finish the RCM.";
// A reference row under a functional failure: a lower functional failure that
// causes it (a view of a row that lives on a position below, never edited here).
LEVEL_OF.cause = { type: "cause", label: "Caused by", plural: "Causes below", child: null, depth: 0 };

export const OUTCOME_LABEL = {
  on_condition: "On condition",
  fixed_interval: "Fixed interval",
  rtf: "Run to failure",
  failure_finding: "Failure finding",
  redesign: "Redesign",
  accept: "Accept",
};
// The four consequence categories ("hidden", the old fifth value, still read:
// it's the evident-or-hidden answer now, modeAnswers in decisionCheck.js).
export const CATEGORY_LABEL = {
  safety: "Safety",
  environmental: "Environmental",
  operational: "Operational",
  non_operational: "Non-operational",
};
export const CONSEQUENCE_LABEL = { ...CATEGORY_LABEL, hidden: "Hidden" };
export const EVIDENT_LABEL = { evident: "Evident", hidden: "Hidden" };

// A mode's two answers in words, as the server's exports write them: "Hidden ·
// Safety", "Operational" (evident: most failures are, so only the category),
// "Hidden" or "Evident" (the category to say), "" (neither answered).
export function consequenceText(m) {
  const { hidden, consequence } = modeAnswers(m);
  const category = CATEGORY_LABEL[consequence] || consequence || "";
  if (hidden) return ["Hidden", category].filter(Boolean).join(" · ");
  return category || (hidden === false ? "Evident" : "");
}
export const isHidden = (m) => modeAnswers(m).hidden === true;
export const categoryOf = (m) => modeAnswers(m).consequence;
export const STATUS_LABEL = {
  supported: "Supported",
  contradicted: "Contradicted",
  inconclusive: "Inconclusive",
  unevidenced: "Not linked",
  stale: "Stale link",
  linked: "Linked",
  // A combination of tasks with evidence for some of its tasks, not all.
  partly: "Partly evidenced",
};
// A report or a function's notes and rationale (evidence type "working": they
// hold the working behind its performance standard): linked, not checked
// (nothing is computed from them), so the check names what's linked and never
// says it's supported.
export const LINKED_LABEL = { report: "Report linked", working: "Notes linked" };
export const isLinkedOnly = (d) => d?.status === "linked";
// The kinds of evidence a decision can link, as the decision dialog offers
// them: models (a model or saved analysis, checked) when the decision expects
// one, then a report and a function's notes and rationale (linked, not checked).
export const EVIDENCE_KIND_LABEL = { model: "Models", report: "Reports", working: "Function notes" };
export const evidenceKinds = (expectedType) => [...(expectedType ? ["model"] : []), "report", "working"];
// The kind the dialog opens on: what's linked now, else models when expected, else reports.
export function startKind(evidence, expectedType) {
  const t = evidence?.type;
  if (t === "report" || t === "working") return t;
  return expectedType ? "model" : "report";
}
// The words for a decision's evidence check ("Supported", "Report linked"...);
// "" when there's nothing worth showing.
export function checkLabel(d) {
  const s = shownStatus(d?.status);
  if (!s) return "";
  if (s === "linked") return LINKED_LABEL[d.evidence_kind] || STATUS_LABEL.linked;
  return STATUS_LABEL[s] || s;
}
// A decision's evidence check worth showing: one with linked evidence (a
// decision with nothing linked yet, "unevidenced", is quiet: most RCM is done
// from judgement, and nothing is wrong with it).
export const shownStatus = (s) => (s && s !== "unevidenced" ? s : null);
const RTF_LABEL = { random: "random", uneconomic: "not economic" };

// Which decisions take a task and an interval (as the decision dialog asks).
export const TASK_OUTCOMES = new Set(["on_condition", "fixed_interval", "rtf", "failure_finding"]);
export const INTERVAL_OUTCOMES = new Set(["on_condition", "fixed_interval", "failure_finding"]);

export const blank = () => ({
  modes: 0, undecided: 0, tasks: 0, hidden: 0, safety: 0,
  supported: 0, contradicted: 0, unsure: 0, stale: 0, unlinked: 0,
});

// A failure mode's own counts (each 0 or 1).
export function modeCounts(m) {
  const d = m.decision;
  const s = d?.status;
  return {
    modes: 1,
    undecided: d ? 0 : 1,
    tasks: hasTask(m) ? 1 : 0,
    hidden: isHidden(m) ? 1 : 0,
    safety: categoryOf(m) === "safety" || categoryOf(m) === "environmental" ? 1 : 0,
    supported: s === "supported" ? 1 : 0,
    contradicted: s === "contradicted" ? 1 : 0,
    // Linked evidence that doesn't settle it (the wrong kind, a unit mismatch...).
    unsure: s === "inconclusive" ? 1 : 0,
    stale: s === "stale" ? 1 : 0,
    // Nothing linked, or (a combination of tasks) nothing for some of its tasks.
    unlinked: s === "unevidenced" || s === "partly" ? 1 : 0,
  };
}

export const hasTask = (m) => !!(m && (tasksOf(m).length || (m.decision && (String(m.decision.task || "").trim() || m.decision.interval))));

// A failure mode's tasks: every live task serving it, its decision's own
// first (the server's `tasks` on the mode, also on its decision). Takes the
// mode or its decision; an older read with only the decision's one task
// gives that.
export function tasksOf(x) {
  if (!x) return [];
  if (Array.isArray(x.tasks) && x.tasks.length) return x.tasks;
  if ("decision" in x && !("outcome" in x)) return tasksOf(x.decision);
  if (x.task_id || (x.outcome && String(x.task || "").trim()) || x.interval != null) {
    return [{ id: x.task_id || null, name: x.task || "", text: x.task || "", interval: x.interval, unit: x.interval_unit, shared_with: 0 }];
  }
  return [];
}

// "+1 task" / "+2 tasks": the tasks beyond the decision's own.
export function moreTasks(d) {
  const n = tasksOf(d).length - 1;
  return n > 0 ? `+${n} task${n === 1 ? "" : "s"}` : "";
}

// "Weekly pH check · every 1 week": one task's line, and the tooltip listing them all.
// A task raised by an event says so: "Re-dose · on event: 120 mm on POOL-RAIN".
export const taskLine = (t) => [t.text || t.name, everyText(t) || null].filter(Boolean).join(" · ");
export const tasksTip = (d) => tasksOf(d).map((t) => taskLine(t) + (t.shared_with ? ` (shared with ${t.shared_with} other failure mode${t.shared_with === 1 ? "" : "s"})` : "")).join("\n");

// The display: rows {key, type, ref, at, parent, kids, depth, sum} keyed by
// the node's id (a repeated id gets a suffix, so every row is drawn), and the
// tops. `at` is where the node is: [function, failure, mode] indexes. `sum`
// counts the failure modes inside the row (for a mode, the mode itself).
export function buildRcmDisplay(functions) {
  const rows = new Map();
  const roots = [];
  const counts = { fn: 0, fail: 0, mode: 0 };
  const keyFor = (id, type, at) => {
    let key = typeof id === "string" && id ? id : `${type}:${at.join(".")}`;
    while (rows.has(key)) key += "~";
    return key;
  };
  const add = (type, ref, at, parent) => {
    const key = keyFor(ref.id, type, at);
    const r = { key, type, ref, at, parent, kids: [], depth: at.length - 1, sum: blank() };
    rows.set(key, r);
    (parent == null ? roots : rows.get(parent).kids).push(key);
    counts[type] += 1;
    return r;
  };
  (functions || []).forEach((fn, fi) => {
    const f = add("fn", fn, [fi], null);
    (fn.failures || []).forEach((fail, xi) => {
      const x = add("fail", fail, [fi, xi], f.key);
      (fail.modes || []).forEach((mode, mi) => {
        const m = add("mode", mode, [fi, xi, mi], x.key);
        m.sum = modeCounts(mode);
        for (const k of Object.keys(m.sum)) {
          x.sum[k] += m.sum[k];
          f.sum[k] += m.sum[k];
        }
      });
    });
  });
  return { rows, roots, counts };
}

// The function a row sits under (a failure's parent is its standard, or the
// "No standard" row, in the Explorer's tree; the function itself in the
// study worksheet). null for a row under none.
export function functionOf(display, r) {
  for (let at = r?.parent; at != null; at = display.rows.get(at)?.parent) {
    const up = display.rows.get(at);
    if (!up) return null;
    if (up.type === "fn") return up;
  }
  return null;
}

// The functional failures on a position, for a failure mode's "Under" choice.
export function failuresOn(display, positionId) {
  const out = [];
  for (const r of display.rows.values()) {
    if (r.type === "fail" && r.ref.position_id === positionId) {
      const fn = functionOf(display, r);
      out.push({ id: r.key, text: r.ref.text, function: fn?.ref.text || "" });
    }
  }
  return out;
}

// A combination of tasks (RCM II): a decision with two or more outcomes, a
// regular inspection plus a fixed-time replacement, each with its own task.
// The server's `outcomes` on the decision ([{outcome, task, interval,
// interval_unit, task_id}], the first the decision's own), only on a combination.
export const isCombination = (d) => Array.isArray(d?.outcomes) && d.outcomes.length > 1;

// A combination's member as a line: "Fixed interval: Replace the bearing · every 24 months".
export function memberLine(o) {
  const label = OUTCOME_LABEL[o.outcome] || o.outcome;
  if (o.outcome === "redesign") return `${label} (until the change is made)`;
  if (!o.task_id && !o.task) return `${label}: no task now`;
  return `${label}: ${[o.task, o.interval != null ? `every ${intervalText(o)}` : null].filter(Boolean).join(" · ")}`;
}

// A combination's member's evidence as a line (the worksheet's Evidence card):
// "Fixed interval: Supported · Bearing replacement (the decision's)", or
// "Fixed interval: none linked"; a redesign needs none.
export function memberEvidenceLine(o) {
  return `${OUTCOME_LABEL[o.outcome] || o.outcome}: ${memberEvidenceText(o)}`;
}

// The same without the outcome (on the member's own task row): "Supported ·
// Bearing replacement (the decision's)", "none linked", "needs no evidence".
export function memberEvidenceText(o) {
  if (!o.status) return "needs no evidence";
  if (o.status === "unevidenced") return "none linked";
  const check = o.status === "linked" ? LINKED_LABEL[o.evidence_kind] || STATUS_LABEL.linked : STATUS_LABEL[o.status] || o.status;
  const what = o.artifact_name ? ` · ${o.artifact_name}` : "";
  return `${check}${what}${o.evidence_from === "decision" ? " (the decision's)" : ""}`;
}

// ---- a failure mode's decision and its tasks, as one section (the details) -----------
// In RCM the decision is the choice of task: the details show the decision in
// words, then one row per member task (RcmModeTasks.jsx).

// The rows under a decision: [{key, outcome, task, member}]. A combination: one
// per member (task null when it schedules none now: a redesign, or a task that
// has gone), then any other task linked to the mode. Otherwise the mode's tasks,
// the first the decision's own (its outcome the decision's when the task has none).
// Only tasks with an id (the Explorer's) are rows; `d` null: the tasks linked
// before any decision.
export function decisionRows(d, tasks) {
  const live = (tasks || []).filter((t) => t?.id);
  if (isCombination(d)) {
    const used = new Set();
    const rows = d.outcomes.map((o, i) => {
      const task = live.find((t) => t.id === o.task_id) || null;
      if (task) used.add(task.id);
      return { key: task ? task.id : `member:${o.outcome}:${i}`, outcome: o.outcome, task, member: o };
    });
    return [...rows, ...live.filter((t) => !used.has(t.id)).map((t) => ({ key: t.id, outcome: t.outcome || null, task: t, member: null }))];
  }
  return live.map((t, i) => ({
    key: t.id, outcome: t.outcome || (d && i === 0 && SCHEDULED_OUTCOMES.has(d.outcome) ? d.outcome : null), task: t, member: null,
  }));
}

// The decision card's lines (a failure mode's details, "Proactive task or default action"): the
// decision in words with its task, one line per task: [{key, kind, name,
// every, task, member}]. "On condition", "Weekly level check", "every 1 week".
// A combination: one line per member (its task, or "no task now"; a redesign
// "until the change is made"), then any other task linked to the mode. Run to
// failure, redesign and accept: the decision and its action on failure, then
// any task linked to the mode. A decision whose tasks have no ids (outside the
// Explorer) is read from the decision itself.
export function decisionCardLines(d, tasks) {
  if (!d) return [];
  const rows = decisionRows(d, tasks);
  const own = (o) => {
    const t = String(o.task || "").trim();
    return { name: t || null, every: INTERVAL_OUTCOMES.has(o.outcome) && o.interval != null && o.interval !== "" ? everyText(o) || null : null };
  };
  // `at`: which part of the decision the line is (a combination's member index; 0 the
  // decision's own task; null a task linked outside the decision), for its on_found.
  const at = (row, i) => (isCombination(d) ? (row.member ? d.outcomes.indexOf(row.member) : null) : i === 0 ? 0 : null);
  const found = (row, i) => {
    const where = at(row, i);
    if (where == null || !FINDS.has(row.outcome)) return null;
    return { at: where, text: (isCombination(d) ? row.member?.on_found : d.on_found) || "" };
  };
  const line = (row, i) => {
    const base = { key: row.key, outcome: row.outcome || null, kind: row.outcome ? OUTCOME_LABEL[row.outcome] || row.outcome : null, found: found(row, i) };
    if (row.task) return { ...base, name: row.task.text || row.task.name || null, every: everyText(row.task) || null, task: row.task, member: row.member };
    if (row.outcome === "redesign") return { ...base, name: "until the change is made", every: null, task: null, member: row.member };
    const m = row.member && !row.member.task_id && (row.member.task || row.member.interval != null) ? own(row.member) : { name: "no task now", every: null };
    return { ...base, ...m, task: null, member: row.member };
  };
  if (isCombination(d)) {
    if (rows.length) return rows.map(line);
    return d.outcomes.map((o, i) => line({ key: `member:${o.outcome}:${i}`, outcome: o.outcome, task: null, member: o }, i));
  }
  const head = { key: "decision", outcome: d.outcome || null, kind: decisionText(d) || null, ...own(d), task: null, member: null,
    found: FINDS.has(d.outcome) ? { at: 0, text: d.on_found || "" } : null };
  if (!INTERVAL_OUTCOMES.has(d.outcome)) return [head, ...rows.map((row) => line(row, null))];
  return rows.length ? rows.map(line) : [head];
}

// ---- what each task card is for (Derryn, 9 Nov 2026) ----------------------------------
// "You have an on-condition task, but then you might have an inspection for that, and that
// needs to be much more clear": each card leads with its role by its kind, then the task.
// An on-condition check and a failure-finding check say, on a second line, what's done when
// the check finds it (the decision's or the member's on_found).
const FINDS = new Set(["on_condition", "failure_finding"]);
export const FOUND_EMPTY = "Say what's done when the check finds it";
export const ROLE = {
  on_condition: { lead: "Check:", then: "Then, if found:" },
  failure_finding: { lead: "Check it still works:", then: "Then, if failed:" },
  fixed_interval: { lead: "Do:" },
  rtf: { lead: "When it fails:" },
  accept: { lead: "Accepted:" },
  redesign: { lead: "Change:" },
};
// Whether a kind of task checks something (and so says what's done when it finds it).
export const findsSomething = (outcome) => FINDS.has(outcome);
// The first line of a text (an accept's or a redesign's card shows the notes' first line).
export const firstLine = (text) => String(text || "").split("\n").map((l) => l.trim()).find(Boolean) || "";
// A card's role line in words: "Check: Weekly level check · every 1 week"; "When it fails: Replace the pump".
// A redesign or accept reads the failure mode's notes (`notes`), where its rationale is written.
export function roleLine(l, notes = "") {
  const role = ROLE[l.outcome];
  if (!role) return { lead: l.kind ? `${l.kind}:` : null, name: l.name || null, every: l.every || null };
  if (l.outcome === "accept" || (l.outcome === "redesign" && !l.task)) {
    return { lead: role.lead, name: firstLine(notes) || null, every: l.outcome === "redesign" && l.member ? "until the change is made" : null };
  }
  return { lead: role.lead, name: l.name || null, every: l.every || null };
}
export const roleLineText = (l, notes = "") => {
  const x = roleLine(l, notes);
  return [[x.lead, x.name].filter(Boolean).join(" "), x.every].filter(Boolean).join(" · ");
};

// One card line in words: "On condition · Weekly level check · every 1 week".
export const cardLineText = (l) => [l.kind, l.name, l.every].filter(Boolean).join(" · ");

// The outcomes another task can add to a decision, as a combination of tasks
// (RCM II): two or more scheduled tasks, or a redesign beside one; none for a
// decision that stands alone (run to failure, accept) or while a scheduled
// member has no task (its interval is missing: decide it first).
const COMBINES = ["on_condition", "fixed_interval", "failure_finding", "redesign"];
const SCHEDULED_OUTCOMES = new Set(COMBINES.slice(0, 3));
function combines(list) {
  if (new Set(list).size !== list.length || list.some((o) => !COMBINES.includes(o))) return false;
  const scheduled = list.filter((o) => SCHEDULED_OUTCOMES.has(o)).length;
  return list.includes("redesign") ? scheduled === 1 : scheduled >= 2;
}
// `mode`: the failure mode, so the RCM decision diagram's refusals apply too
// (a second scheduled task only on a safety or environmental consequence;
// failure finding only on a hidden failure).
export function addableOutcomes(d, mode = null) {
  if (!d) return [];
  const members = isCombination(d) ? d.outcomes : [{ outcome: d.outcome, task_id: d.task_id }];
  if (members.some((o) => SCHEDULED_OUTCOMES.has(o.outcome) && !o.task_id)) return [];
  const have = members.map((o) => o.outcome);
  const answers = mode ? modeAnswers(mode) : null;
  return COMBINES.filter((o) => !have.includes(o) && combines([...have, o])
    && !(answers && doctrineRefusal(answers.hidden, answers.consequence, [...have, o])));
}

// The decision as the server takes it back with one more member: each member
// it has by its task (task_id, so a task's name and interval are left as they
// are), its own evidence and on_found kept; the decision's evidence kept (its notes
// are the failure mode's, saved on their own).
// `member`: {outcome} (a redesign), {outcome, task, interval, interval_unit}
// (a new task) or {outcome, task_id} (an existing one).
export function decisionWithMember(d, member) {
  const ref = (e) => (e?.type && e?.id ? { type: e.type, id: e.id } : null);
  const keep = (o) => ({
    outcome: o.outcome,
    ...(o.task_id ? { task_id: o.task_id } : {}),
    ...(ref(o.evidence) ? { evidence: ref(o.evidence) } : {}),
    ...(o.on_found ? { on_found: o.on_found } : {}),
  });
  const members = isCombination(d) ? d.outcomes.map(keep) : [keep({ outcome: d.outcome, task_id: d.task_id, on_found: d.on_found })];
  const out = { outcomes: [...members, member] };
  if (ref(d.evidence)) out.evidence = ref(d.evidence);
  return out;
}

// ---- step 3 edited in place (a failure mode's details) ------------------------
// The failure mode's details choose the decision with one tap (RcmModeTasks:
// "Which task is worth doing?"), so each tap sends the whole decision, built
// here from the one it replaces. The evidence goes with it when it fits any
// decision (a report or function notes) or the outcome hasn't changed (a model
// fits the outcome it was linked for). The notes are the failure mode's (one
// place since Nov 2026), never sent with a decision; on_found, left out, is kept
// by the server while the kind of task stays.

const LINKED_EVIDENCE = new Set(["report", "working"]);
const evidenceRef = (e) => (e?.type && e?.id ? { type: e.type, id: e.id } : null);

// The task a scheduled outcome keeps when the decision changes to it: a
// combination's member of the same kind, else the decision's own task, else
// the first task linked to the mode (so changing the kind of task never drops
// the task that does the work). Null for an outcome that schedules nothing.
export function keptTask(d, tasks, outcome) {
  if (!SCHEDULED_OUTCOMES.has(outcome)) return null;
  const member = isCombination(d) ? d.outcomes.find((o) => o.outcome === outcome && o.task_id) : null;
  return member?.task_id || d?.task_id || (tasks || []).find((t) => t.id)?.id || null;
}

// The decision with its outcome changed (rtfBasis for run to failure), as
// the server takes it: a scheduled outcome adopts the task it keeps (by id,
// so its name and interval stay as they are); run to failure keeps what's done
// on failure when it was run to failure already.
export function decisionWithOutcome(d, tasks, outcome, rtfBasis = null) {
  const out = {};
  const same = d && d.outcome === outcome && (outcome !== "rtf" || d.rtf_basis === rtfBasis);
  const ev = evidenceRef(d?.evidence);
  const task = keptTask(d, tasks, outcome);
  if (task) out.outcomes = [{ outcome, task_id: task }];
  else out.outcome = outcome;
  if (outcome === "rtf") {
    out.rtf_basis = rtfBasis;
    if (d?.outcome === "rtf" && String(d.task || "").trim()) out.task = d.task;
  }
  if (ev && (LINKED_EVIDENCE.has(ev.type) || same)) out.evidence = ev;
  return out;
}

// The tasks that come off the failure mode when the decision changes to
// `outcome` (null: the decision cleared): every task when nothing is
// scheduled any more; from a combination, every task but the one kept. A plain
// decision changing its kind of task keeps its tasks.
export function tasksDropped(d, tasks, outcome) {
  const live = (tasks || []).filter((t) => t.id);
  if (!outcome || !SCHEDULED_OUTCOMES.has(outcome)) return live;
  if (!isCombination(d)) return [];
  const kept = keptTask(d, tasks, outcome);
  return live.filter((t) => t.id !== kept);
}

// A scheduled decision with no task yet, given its task: a new one ({task,
// interval, interval_unit}) or an existing one ({task_id}).
export function decisionWithFirstTask(d, member) {
  const ev = evidenceRef(d?.evidence);
  const found = member.on_found ? { on_found: member.on_found } : {};
  const out = member.task_id
    ? { outcomes: [{ outcome: d.outcome, task_id: member.task_id, ...found }] }
    : { outcome: d.outcome, task: member.task, interval: member.interval, interval_unit: member.interval_unit, ...found };
  if (ev) out.evidence = ev;
  return out;
}

// The decision as the server takes it back with what's done when one of its checks
// finds it (`at`: the combination's member index, 0 the decision's own task) set to
// `text` ("" clears it): every member by its task (task_id) where it has one, so
// nothing else changes.
export function decisionWithOnFound(d, at, text) {
  const ev = evidenceRef(d?.evidence);
  // A member's own evidence goes back with it (a single decision's is the decision's, below).
  const member = (o, own, ownEvidence = true) => ({
    outcome: o.outcome,
    ...(o.task_id ? { task_id: o.task_id }
      : Object.fromEntries(["task", "interval", "interval_unit"].filter((k) => o[k] != null && o[k] !== "").map((k) => [k, o[k]]))),
    ...(ownEvidence && evidenceRef(o.evidence) ? { evidence: evidenceRef(o.evidence) } : {}),
    ...(own ? { on_found: text } : {}),
  });
  const out = isCombination(d)
    ? { outcomes: d.outcomes.map((o, i) => member(o, i === at)) }
    : d.task_id ? { outcomes: [member(d, true, false)] } : member(d, true, false);
  if (ev) out.evidence = ev;
  return out;
}

// A decision as the server takes it back: the fields a decision is made of,
// without the evidence check the server added. A combination goes back whole
// (its members, the change applied to the first: the decision's own task), so
// editing one cell never drops the other tasks.
export function decisionBody(d, patch = {}) {
  if (!d) return null;
  if (isCombination(d)) {
    const given = (v) => v !== undefined && v !== null && v !== "";
    // Each member goes back with its own evidence, if any (only {type, id}: the read adds its check).
    const keep = (o) => ({
      ...Object.fromEntries(["outcome", "task", "interval", "interval_unit", "on_found"].filter((k) => given(o[k])).map((k) => [k, o[k]])),
      ...(o.evidence?.type && o.evidence?.id ? { evidence: { type: o.evidence.type, id: o.evidence.id } } : {}),
    });
    const first = keep(d.outcomes[0]);
    for (const k of ["task", "interval", "interval_unit"]) {
      if (!(k in patch)) continue;
      if (given(patch[k])) first[k] = patch[k];
      else delete first[k];
    }
    if (first.interval != null && !first.interval_unit) first.interval_unit = "hours";
    if (first.interval == null) delete first.interval_unit;
    const out = { outcomes: [first, ...d.outcomes.slice(1).map(keep)] };
    const v = "evidence" in patch ? patch.evidence : d.evidence;
    if (given(v)) out.evidence = v;
    return out;
  }
  const out = {};
  // The notes are the failure mode's (one place since Nov 2026): never sent with a decision.
  for (const k of ["outcome", "rtf_basis", "task", "interval", "interval_unit", "on_found", "evidence"]) {
    if (d[k] !== undefined && d[k] !== null && d[k] !== "") out[k] = d[k];
  }
  for (const [k, v] of Object.entries(patch)) {
    if (v === null || v === "") delete out[k];
    else out[k] = v;
  }
  if (out.interval != null && !out.interval_unit) out.interval_unit = "hours";
  if (out.interval == null) delete out.interval_unit;
  return out;
}

// A row's text (the node's description).
export const nameOf = (r) => r.ref.text || r.ref.name || "";

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;

// "580 hours", "1 month": units are stored as typed (usually plural), so
// singularise them for an interval of exactly 1.
export function intervalText(d) {
  if (!d || d.interval == null || d.interval === "") return "";
  const u = d.interval_unit || "";
  const unit = Number(d.interval) === 1 && /[a-z]s$/i.test(u) ? u.slice(0, -1) : u;
  return `${Number(d.interval).toLocaleString("en-AU", { maximumSignificantDigits: 6 })} ${unit}`.trim();
}

// A task's trigger (the server's `trigger`, with its words in `text`): what
// raises its work order besides, or instead of, its interval.
// "on event: 120 mm on POOL-RAIN", "on event: Lightning strike".
export function triggerText(trigger) {
  return trigger?.text ? `on event: ${trigger.text}` : "";
}
// Raised only by its trigger: the interval is kept but doesn't run.
export const onEventOnly = (x) => !!(x?.trigger && !x.trigger.with_interval);
// When a task (or a decision: interval_unit for unit) is done, as the
// worksheet's Interval column says it: "6 months", "on event: 120 mm on
// POOL-RAIN", or both ("6 months or on event: …").
export function whenText(x) {
  if (!x) return "";
  if (onEventOnly(x)) return triggerText(x.trigger);
  const every = intervalText({ interval: x.interval, interval_unit: x.interval_unit ?? x.unit });
  return [every, triggerText(x.trigger)].filter(Boolean).join(" or ");
}
// The same with "every" before an interval: a task card's chip.
export function everyText(x) {
  if (!x) return "";
  if (onEventOnly(x)) return triggerText(x.trigger);
  const every = x.interval != null && (x.interval_unit ?? x.unit)
    ? `every ${intervalText({ interval: x.interval, interval_unit: x.interval_unit ?? x.unit })}` : "";
  return [every, triggerText(x.trigger)].filter(Boolean).join(" or ");
}

export function decisionText(d) {
  if (!d) return "";
  if (isCombination(d)) return d.outcomes.map((o) => OUTCOME_LABEL[o.outcome] || o.outcome).join(" + ");
  const label = OUTCOME_LABEL[d.outcome] || d.outcome || "";
  return d.outcome === "rtf" && RTF_LABEL[d.rtf_basis] ? `${label} (${RTF_LABEL[d.rtf_basis]})` : label;
}

// ---- a functional failure caused by lower ones (the Explorer's RCM tab) ------------
// A functional failure's counted causes (on positions inside its own), each
// with its chain's roll-up, are read with it (ref.causes, ref.below). Its own
// failure modes are what `sum` counts; the chain below is shown beside, never
// added in, so nothing is counted twice.

// The part of a functional failure's row that comes from below, or null: how
// many failure modes below still need a decision, how many tasks are below,
// whether a linked failure below isn't finished, and whether it has failure
// modes of its own.
export function belowOf(r) {
  if (r.type !== "fail") return null;
  const causes = (r.ref.causes || []).filter((c) => c.inside);
  if (!causes.length) return null;
  const b = r.ref.below || {};
  return { undecided: b.undecided || 0, tasks: b.tasks || 0, unfinished: causes.some((c) => !c.covered), own: r.sum.modes > 0 };
}

// The Decision cell's part from below: "explained below", "2 to decide below";
// with no failure modes of its own, "Explained below · 2 to decide".
export function belowDecisionText(r) {
  const b = belowOf(r);
  if (!b) return "";
  if (b.own) return b.undecided ? `${b.undecided.toLocaleString("en-AU")} to decide below` : b.unfinished ? "not finished below" : "explained below";
  return `Explained below${b.undecided ? ` · ${b.undecided.toLocaleString("en-AU")} to decide` : b.unfinished ? " · not finished" : ""}`;
}

// Does what's below still need work (the amber part of the cell)?
export const belowPending = (r) => {
  const b = belowOf(r);
  return !!b && (b.undecided > 0 || b.unfinished);
};

// What's inside a row, in words: "5 failure modes · 2 to decide · 3 with a task".
export function insideWords(r) {
  const s = r.sum;
  if (r.type === "mode") return "";
  if (r.type === "fail" && !s.modes && (r.ref.causes || []).length) return r.ref.explained_below ? "Explained below" : "No failure modes of its own";
  if (!s.modes) {
    // A function's failures sit under its standards in the Explorer's tree,
    // so its own kids aren't them: the read says how many it has.
    const fails = r.type === "fn" && Array.isArray(r.ref.failures) ? r.ref.failures.length : r.kids.length;
    if (r.type === "std" && !fails) return r.ref.legacy ? "Nothing inside yet" : "No functional failure written yet";
    return fails ? plural(fails, "functional failure") + ", no failure modes yet" : "Nothing inside yet";
  }
  return [
    plural(s.modes, "failure mode"),
    s.undecided ? `${s.undecided.toLocaleString("en-AU")} to decide` : "all decided",
    s.tasks ? `${s.tasks.toLocaleString("en-AU")} with a task` : null,
  ].filter(Boolean).join(" · ");
}

// The phone's second line: the main columns, in words.
export function phoneLine(r) {
  if (r.type === "std") return [limitWords(r.ref), insideWords(r)].filter(Boolean).join(" · ");
  if (r.type === "cause") {
    const s = r.sum;
    const where = r.ref.inside === false ? `no longer inside ${r.ref.effect_position || "it"}` : null;
    return [`on ${r.ref.on}`, where, s.modes ? (s.undecided ? `${s.undecided} to decide` : "all decided") : "no failure modes yet",
      s.tasks ? plural(s.tasks, "task") : null].filter(Boolean).join(" · ");
  }
  if (r.type === "fail" && belowOf(r)) {
    return belowOf(r).own ? `${insideWords(r)} · ${belowDecisionText(r)}` : belowDecisionText(r);
  }
  if (r.type !== "mode") return insideWords(r);
  const d = r.ref.decision;
  return [consequenceText(r.ref), d ? decisionText(d) : "To decide", isCombination(d) ? "" : whenText(d), d?.task || tasksOf(r.ref)[0]?.text, moreTasks(r.ref)]
    .filter(Boolean).join(" · ");
}

// The evidence checks inside a row: [{kind, n, label}] (kind: supported,
// contradicted, unsure, stale), for the parent rows' Evidence check cell. Only
// linked evidence counts: a decision with nothing linked yet isn't "to check".
export function checkCounts(r) {
  const s = r.sum;
  return [
    { kind: "contradicted", n: s.contradicted, label: "contradicted" },
    { kind: "unsure", n: s.unsure, label: "inconclusive" },
    { kind: "stale", n: s.stale, label: "stale" },
    { kind: "supported", n: s.supported, label: "supported" },
  ].filter((c) => c.n > 0);
}

// ---- columns -----------------------------------------------------------------

// Every column but the index (the description, always shown first). `on`: in
// the default set (fits 1440 px wide with the menu open). `min`: the least
// it's narrowed to so a table fits its pane (its header still whole). `text(r)`: the cell
// as plain text (the phone's second line, the CSV of what's shown). `sort(r)`:
// the value it sorts by, null for blank (blanks go last); a row with things
// inside it sorts by what's inside. `edit`: the field edited in the cell
// ("text", "choice" or "number"), and `can(r)` the rows that allow it.
const CONS_RANK = { safety: 0, environmental: 1, operational: 3, non_operational: 4 };
// Safety first; a hidden mode just before the evident ones of its category (one with none yet after the serious ones).
const consRank = (m) => (categoryOf(m) ? CONS_RANK[categoryOf(m)] ?? null : isHidden(m) ? 2 : null) - (isHidden(m) && categoryOf(m) ? 0.5 : 0);
const OUT_RANK = { on_condition: 0, fixed_interval: 1, failure_finding: 2, rtf: 3, redesign: 4, accept: 5 };
const STATUS_RANK = { contradicted: 0, stale: 1, inconclusive: 3, supported: 4, linked: 5 };
const isMode = (r) => r.type === "mode";
const d = (r) => r.ref.decision || null;

// A function's performance standards are rows in the tree (each one's limit
// in its details), not a column: a saved choice that still names the old
// Performance standard column just drops it (loadPrefs keeps known ids only).
export const COLUMNS = [
  {
    id: "effects", label: "Failure effects", width: 180, min: 112, on: true,
    title: "What happens when the failure mode occurs",
    text: (r) => (isMode(r) ? r.ref.effects || "" : ""),
    sort: (r) => (isMode(r) ? r.ref.effects || null : null),
    edit: "text", can: isMode, field: "effects",
  },
  {
    id: "consequence", label: "Consequence", width: 114, min: 98, on: true,
    title: "Safety, environmental, operational or non-operational; for a hidden failure, what the multiple failure would do",
    text: (r) => (isMode(r) ? consequenceText(r.ref) : consequenceSum(r)),
    sort: (r) => (isMode(r) ? (categoryOf(r.ref) || isHidden(r.ref) ? consRank(r.ref) : null) : r.sum.safety ? 0 : r.sum.hidden ? 2 : null),
    edit: "choice", can: isMode, field: "consequence", labels: CATEGORY_LABEL,
    options: Object.entries(CATEGORY_LABEL).map(([value, label]) => ({ value, label })),
  },
  {
    id: "evident", label: "Evident or hidden", width: 120, min: 120, on: false,
    title: "Hidden: the failure can't be seen in normal operation",
    text: (r) => (isMode(r) ? (isHidden(r.ref) ? "Hidden" : modeAnswers(r.ref).hidden === false ? "Evident" : "") : r.sum.hidden ? `${r.sum.hidden} hidden` : ""),
    sort: (r) => (isMode(r) ? (isHidden(r.ref) ? 0 : modeAnswers(r.ref).hidden === false ? 1 : null) : r.sum.hidden ? 0 : null),
  },
  {
    id: "decision", label: "Decision", width: 150, min: 84, on: true,
    title: "The maintenance decision for the failure mode",
    text: (r) => (isMode(r) ? decisionText(d(r)) || "To decide"
      : [r.sum.modes ? (r.sum.undecided ? `${r.sum.undecided} to decide` : "All decided") : "", belowDecisionText(r)].filter(Boolean).join(" · ")),
    sort: (r) => (isMode(r) ? (d(r) ? OUT_RANK[d(r).outcome] ?? 9 : -1) : -r.sum.undecided),
  },
  {
    id: "task", label: "Task", width: 190, min: 110, on: true,
    title: "What is done (the decision's own task, and how many more), and for run-to-failure the action on failure",
    text: (r) => (isMode(r) ? [d(r)?.task || tasksOf(r.ref)[0]?.text || "", moreTasks(r.ref)].filter(Boolean).join(" · ")
      : [r.sum.tasks ? plural(r.sum.tasks, "task") : "", belowOf(r)?.tasks ? `${belowOf(r).tasks.toLocaleString("en-AU")} below` : ""].filter(Boolean).join(" · ")),
    sort: (r) => (isMode(r) ? d(r)?.task || null : r.sum.tasks || null),
    edit: "text", can: (r) => isMode(r) && TASK_OUTCOMES.has(d(r)?.outcome), field: "task", onDecision: true,
  },
  {
    id: "interval", label: "Interval", width: 92, min: 72, on: true, align: "num",
    title: "How often the task is done, in its unit",
    text: (r) => (isMode(r) ? whenText(d(r)) : ""),
    sort: (r) => (isMode(r) && d(r)?.interval && !onEventOnly(d(r)) ? Number(d(r).interval) : null),
    // A task raised by an event: its trigger is changed in the task's Edit… (Trigger).
    edit: "number", can: (r) => isMode(r) && INTERVAL_OUTCOMES.has(d(r)?.outcome) && !onEventOnly(d(r)), field: "interval", onDecision: true,
  },
  {
    id: "check", label: "Evidence check", width: 126, min: 112, on: true,
    title: "Whether the linked analysis backs the decision, checked each time the study opens (a linked report or working isn't checked)",
    text: (r) => (isMode(r) ? checkLabel(d(r)) : checkCounts(r).map((c) => `${c.n} ${c.label}`).join(", ")),
    sort: (r) => (isMode(r) ? STATUS_RANK[d(r)?.status] ?? null
      : r.sum.contradicted ? 0 : r.sum.stale ? 1 : r.sum.unsure ? 2 : r.sum.supported ? 4 : null),
  },
  {
    id: "evidence", label: "Evidence", width: 200, min: 90, on: false,
    title: "The saved model, analysis, report or working linked to the decision",
    text: (r) => (isMode(r) ? d(r)?.artifact_name || "" : ""),
    sort: (r) => (isMode(r) ? d(r)?.artifact_name || null : null),
  },
  {
    id: "detail", label: "What the evidence shows", width: 260, min: 160, on: false,
    text: (r) => (isMode(r) ? d(r)?.summary || d(r)?.reason || "" : ""),
    sort: (r) => (isMode(r) ? d(r)?.summary || d(r)?.reason || null : null),
  },
  {
    // The decision's notes are the failure mode's notes and rationale since Nov 2026 (one
    // place): the column reads them, merged with any decision notes kept from before.
    id: "dnotes", label: "Decision notes", width: 220, min: 110, on: false,
    title: "The failure mode's notes and rationale, where the decision's rationale is written",
    text: (r) => (isMode(r) && d(r) ? r.ref.notes || "" : ""),
    sort: (r) => (isMode(r) && d(r) ? r.ref.notes || null : null),
    edit: "text", can: (r) => isMode(r) && !!d(r), field: "notes",
  },
  {
    id: "notes", label: "Mode notes", width: 200, min: 96, on: false,
    title: "Notes on the failure mode itself (for example scores kept from an FMEA)",
    text: (r) => (isMode(r) ? r.ref.notes || "" : ""),
    sort: (r) => (isMode(r) ? r.ref.notes || null : null),
    edit: "text", can: isMode, field: "notes",
  },
  {
    id: "modes", label: "Failure modes", width: 104, min: 100, on: false, align: "num", sum: true,
    title: "How many failure modes are inside",
    text: (r) => (isMode(r) ? "" : String(r.sum.modes)),
    sort: (r) => (isMode(r) ? null : r.sum.modes),
  },
  {
    id: "undecided", label: "To decide", width: 90, min: 78, on: false, align: "num", sum: true,
    title: "Failure modes inside with no decision yet",
    text: (r) => (isMode(r) ? "" : r.sum.undecided ? String(r.sum.undecided) : ""),
    sort: (r) => (isMode(r) ? null : r.sum.undecided || null),
  },
];
export const COLUMN = Object.fromEntries(COLUMNS.map((c) => [c.id, c]));
export const NAME_COLUMN = { id: "name", label: "Function, performance standard, failure or mode", width: 270, min: 180 };
export const DEFAULT_COLUMNS = COLUMNS.filter((c) => c.on).map((c) => c.id);

// A parent row's consequences: the most serious kind inside it (all of them
// in consequenceWords, for its title).
function consequenceSum(r) {
  if (r.sum.safety) return `${r.sum.safety.toLocaleString("en-AU")} safety or env.`;
  return r.sum.hidden ? `${r.sum.hidden.toLocaleString("en-AU")} hidden` : "";
}
export function consequenceWords(r) {
  return [r.sum.safety ? `${plural(r.sum.safety, "failure mode")} with a safety or environmental consequence` : null,
    r.sum.hidden ? `${plural(r.sum.hidden, "hidden failure")}` : null].filter(Boolean).join("; ");
}

// Siblings in a column's order (dir 1 or -1), blanks last whichever way; a
// tie keeps the worksheet's own order. For flatten's `order`.
export function siblingOrder(display, sort) {
  const col = sort && COLUMN[sort.col];
  if (!col && sort?.col !== "name") return null;
  const value = sort.col === "name" ? (r) => nameOf(r) || null : col.sort;
  const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });
  return (keys) => keys
    .map((k, i) => ({ k, i, v: value(display.rows.get(k)) }))
    .sort((a, b) => {
      const an = a.v == null || a.v === "";
      const bn = b.v == null || b.v === "";
      if (an || bn) return an === bn ? a.i - b.i : an ? 1 : -1;
      const c = typeof a.v === "number" && typeof b.v === "number" ? a.v - b.v : collator.compare(String(a.v), String(b.v));
      return c ? c * sort.dir : a.i - b.i;
    })
    .map((x) => x.k);
}

// ---- filter ------------------------------------------------------------------

// The chips, each about the failure modes (and showing how many there are).
export const CHIPS = [
  { id: "undecided", label: "Needs a decision", test: (r) => isMode(r) && !d(r) },
  { id: "hidden", label: "Hidden failures", test: (r) => isMode(r) && isHidden(r.ref) },
  { id: "safety", label: "Safety or environment", test: (r) => isMode(r) && (categoryOf(r.ref) === "safety" || categoryOf(r.ref) === "environmental") },
  { id: "task", label: "Has a task", test: (r) => isMode(r) && hasTask(r.ref) },
  { id: "notask", label: "No task yet", test: (r) => isMode(r) && !hasTask(r.ref) },
  { id: "check", label: "Evidence to look at", title: "Linked evidence that contradicts the decision, doesn't settle it, or has gone (a stale link)",
    test: (r) => isMode(r) && ["contradicted", "inconclusive", "stale"].includes(d(r)?.status) },
];

export function chipCounts(display) {
  const out = Object.fromEntries(CHIPS.map((c) => [c.id, 0]));
  for (const r of display.rows.values()) {
    if (!isMode(r)) continue;
    for (const c of CHIPS) if (c.test(r)) out[c.id] += 1;
  }
  return out;
}

// What the filter's text is searched by: the description, the standard, the
// effects, the task and the notes (a function's hold the working behind its
// standards); and the FMEA's words on a mode (its cause, local and next effects,
// detection method, action and owner).
export function rowText(r) {
  const p = r.ref;
  return [p.text, p.standard, p.effects, p.notes, p.decision?.task, p.decision?.on_found,
    p.cause, p.effect_local, p.effect_next, p.detection_method, p.action, p.action_owner,
    ...tasksOf(p).map((t) => t.name), ...(p.standards || []).map((st) => [st.parameter, st.when, st.source].filter(Boolean).join(" ")),
    // A standard's own row: its structured limit, condition and source too.
    p.parameter, p.when, p.source]
    .filter(Boolean).join(" ").toLowerCase();
}

// The rows matching the text and every chip that's on, with the path to each.
// null when nothing filters.
export function computeFilter(display, { query = "", chips = [] } = {}) {
  const q = query.trim().toLowerCase();
  const tests = CHIPS.filter((c) => chips.includes(c.id));
  if (!q && !tests.length) return null;
  return filterRows(display, (r) => (!q || rowText(r).includes(q)) && tests.every((c) => c.test(r)));
}

// ---- a cell's value ---------------------------------------------------------

// A cell's new value, checked as the server will check it: a description
// can't be empty; an interval is a positive number (blank clears it). {value}
// or {error}.
export function checkValue(col, row, raw) {
  if (col === "name") {
    const text = String(raw ?? "").trim();
    if (!text) return { error: `Every ${LEVEL_OF[row.type].label.toLowerCase()} needs a description.` };
    if (row.type === "fn") {
      const c = functionCount(text, row.ref?.text ?? null);
      if (c.blocked) return { error: c.message };
    }
    return { value: text };
  }
  const c = COLUMN[col];
  if (c?.edit === "number") {
    const s = String(raw ?? "").trim();
    if (!s) return { value: null };
    const n = Number(s);
    if (!Number.isFinite(n)) return { error: "The task interval must be a number." };
    if (n <= 0) return { error: "The task interval must be positive." };
    return { value: n };
  }
  // The first RCM question: "evident" or "hidden" (blank: not answered).
  if (col === "hidden") return { value: raw === "hidden" ? true : raw === "evident" ? false : null };
  if (c?.edit === "choice") return { value: (c.labels || CONSEQUENCE_LABEL)[raw] ? raw : null };
  return { value: String(raw ?? "").trim() };
}

// ---- remembered on this device -----------------------------------------------

// The columns shown and their widths, and the row density. Storage can throw
// (private mode, blocked site data), so every read and write is guarded and
// the worksheet works without it.
const KEY = "reliafy.rcmWorksheet";

export function loadPrefs(storage = globalThis.localStorage) {
  const fallback = { cols: DEFAULT_COLUMNS, widths: {}, density: "comfortable" };
  try {
    const raw = storage?.getItem(KEY);
    const v = raw ? JSON.parse(raw) : {};
    const cols = Array.isArray(v.cols) ? v.cols.filter((c) => COLUMN[c]) : DEFAULT_COLUMNS;
    const widths = {};
    for (const [k, w] of Object.entries(v.widths || {})) if ((COLUMN[k] || k === "name") && Number.isFinite(w)) widths[k] = w;
    return {
      cols,
      widths,
      density: v.density === "compact" ? "compact" : "comfortable",
      // The Explorer's Evidence check column, when chosen on or off there
      // (left out: shown once the workspace has linked evidence).
      ...(typeof v.explorerCheck === "boolean" ? { explorerCheck: v.explorerCheck } : {}),
      // The columns were chosen in a Columns menu (else the usual ones, which
      // in the Explorer depend on the window's width). Columns kept from
      // before this was remembered count as chosen when they aren't the usual set.
      ...(v.colsChosen === true || (v.colsChosen !== false && Array.isArray(v.cols) && !sameSet(cols, DEFAULT_COLUMNS))
        ? { colsChosen: true } : {}),
    };
  } catch {
    return fallback;
  }
}

const sameSet = (a, b) => a.length === b.length && a.every((x) => b.includes(x));

export function savePrefs(prefs, storage = globalThis.localStorage) {
  try {
    // `open` (the rows open per study, before the RCM moved onto the tree) is
    // dropped from what an earlier version remembered.
    const { open: _open, ...rest } = prefs;
    storage?.setItem(KEY, JSON.stringify(rest));
  } catch {
    // Not remembered on this device; the worksheet still works.
  }
}

// A width kept between a column's least and 640 px.
export const clampCol = (w, min = 60) => Math.min(640, Math.max(min, Math.round(w)));
