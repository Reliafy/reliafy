// Rearranging the RCM tab's tree: what a drag can drop where, and the one
// batch each drop sends (POST /api/maintenance/rcm/apply). The row menus'
// "Move to…" picker and Move up / down use the same plans, so the keyboard
// and a phone can do every move a drag can.
//
// What can be dragged (a wide screen):
// - a function: onto another position (it moves there, with everything under
//   it), or before / after another function (the order; on another position,
//   it moves there and goes in that place);
// - a performance standard: before / after another standard (the order; of
//   another function, it moves there), or onto another function on any
//   position. It carries everything under it: the functional failures that
//   breach it, their failure modes, decisions and tasks (one batch: the
//   standard's move, then each failure's move, breaching it again there);
// - a functional failure: onto a function, a standard (it breaches that one)
//   or "No standard", or before / after another functional failure (it takes
//   that one's standard);
// - one failure mode, or several picked with Shift / Ctrl / Cmd-click: onto a
//   functional failure, "Not under a functional failure" or a position, or
//   before / after another failure mode;
// - a task (a failure mode's Task cell): onto another failure mode (it moves:
//   it stops preventing the mode it came from; to link one task to several
//   modes, use the mode's "Add a task…" › Use an existing task), or onto a
//   position (the task moves there).
//
// The rules the tree knows (what can go inside what, "it's there already")
// are checked here at once. The rest (open work orders, recorded failures,
// a same-named mode on the other position, a task that can't reach) only the
// server knows: the page asks it with a dry run while the pointer rests on a
// row, and the server checks every drop again.
//
// Pure functions (no React), tested in rcmDrag.test.js.

const q = (s) => `“${String(s || "").trim().slice(0, 60) || "(no name)"}”`;
const textOf = (r) => (r?.type === "pos" ? r.ref.name : r?.ref.text) || "";
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

// What a drag carries: {kind, keys, task?}. kind is fn, std, fail, modes or
// task; keys the rows dragged (for a task, the failure mode it's dragged
// from); task: {id, name, position_id}.
export function dragSource(whole, key, { picked = null, task = null } = {}) {
  const r = whole.rows.get(key);
  if (!r) return null;
  if (task) {
    if (r.type !== "mode" || !task.id) return null;
    return { kind: "task", keys: [key], task: { id: task.id, name: task.name || task.text || "", position_id: task.position_id || r.ref.position_id } };
  }
  if (r.type === "fn" || r.type === "fail") return { kind: r.type, keys: [key] };
  if (r.type === "std") return r.ref.legacy ? null : { kind: "std", keys: [key] };
  if (r.type === "mode") {
    // A picked mode drags every mode picked; another drags alone.
    const keys = picked && picked.has(key) ? [...picked].filter((k) => whole.rows.get(k)?.type === "mode") : [key];
    return { kind: "modes", keys };
  }
  return null;
}

// Why a row can't be dragged (shown as its tooltip), or null.
export function dragBlock(r) {
  if (r?.type === "std" && r.ref.legacy) return "This is the function's one performance standard text. Add it as a performance standard (Add a performance standard… on the function) to move it.";
  return null;
}

// The words for what's dragged: "“No flow”", "3 failure modes", "the task “Grease bearings”".
export function sourceWords(whole, src) {
  if (src.kind === "task") return `the task ${q(src.task.name)}`;
  if (src.kind === "modes" && src.keys.length > 1) return plural(src.keys.length, "failure mode");
  if (src.kind === "std") {
    // A standard carries the functional failures under it: say how many.
    const n = failsUnder(whole, src.keys[0]).length;
    const r = whole.rows.get(src.keys[0]);
    return `the performance standard ${q(textOf(r))}${n ? ` and its ${n === 1 ? "functional failure" : plural(n, "functional failure")}` : ""}`;
  }
  return q(textOf(whole.rows.get(src.keys[0])));
}

// The functional failures under a standard's row (those breaching it), in order.
export const failsUnder = (whole, stdKey) => (whole.rows.get(stdKey)?.kids || []).filter((k) => whole.rows.get(k)?.type === "fail");

// Is `key` the row `top` or a row inside it?
function within(whole, key, top) {
  for (let k = key, guard = 0; k != null && guard < 10000; k = whole.rows.get(k)?.parent, guard += 1) if (k === top) return true;
  return false;
}

// Is position `inner` the position `outer` or one inside it (the positions tree)?
export function positionWithin(whole, inner, outer) {
  const seen = new Set();
  for (let p = inner; p && !seen.has(p); p = whole.rows.get(p)?.ref?.parent_id) {
    if (p === outer) return true;
    seen.add(p);
  }
  return false;
}

// ids in a new order: `moving` (in their order) taken out and put before or
// after `at` (null: at the end).
export function place(ids, moving, at, zone) {
  const out = ids.filter((id) => !moving.includes(id));
  let i = at == null ? out.length : out.indexOf(at);
  if (i < 0) i = out.length;
  else if (zone === "after") i += 1;
  out.splice(i, 0, ...moving);
  return out;
}

const same = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);
const fnIdsOf = (whole, posKey) => (whole.rows.get(posKey)?.kids || []).filter((k) => whole.rows.get(k)?.type === "fn");
const failIdsOf = (whole, fnKey) => (whole.rows.get(fnKey)?.ref.failures || []).map((f) => f.id);
const modeIdsOf = (whole, ffKey) => (whole.rows.get(ffKey)?.ref.modes || []).map((m) => m.id);
const stdIdsOf = (whole, fnKey) => (whole.rows.get(fnKey)?.ref.standards || []).map((s) => s.id);
const op = (doName, args) => ({ do: `failure_modes.${doName}`, args });
const taskOp = (doName, args) => ({ do: `tasks.${doName}`, args });
const hasList = (whole, fnKey) => (whole.rows.get(fnKey)?.ref.standards || []).length > 0;

// Which drop zones a row offers what's dragged: some of before, into, after.
// [] with `reason`: it can't go there (the reason is said). [] with no
// reason: the row is what's dragged, or inside it (nothing is shown).
export function dropZones(whole, src, targetKey) {
  const t = whole.rows.get(targetKey);
  if (!t || !src) return { zones: [] };
  if (src.kind !== "task" && src.keys.some((k) => within(whole, targetKey, k))) return { zones: [] };
  const no = (reason) => ({ zones: [], reason });
  if (src.kind === "fn") {
    if (t.type === "pos") return { zones: ["into"] };
    if (t.type === "fn") return { zones: ["before", "after"] };
    return no("A function goes on a position: drop it on a position, or before or after another function.");
  }
  if (src.kind === "std") {
    if (t.type === "fn") return { zones: ["into"] };
    if (t.type === "std") return { zones: t.ref.legacy ? ["into"] : ["before", "after"] };
    return no("A performance standard belongs to a function: drop it on a function, or before or after another standard.");
  }
  if (src.kind === "fail") {
    if (t.type === "fn" || t.type === "std" || t.type === "nostd") return { zones: ["into"] };
    if (t.type === "fail") return { zones: ["before", "after"] };
    return no("A functional failure goes under a function or a performance standard: drop it there, or before or after another functional failure.");
  }
  if (src.kind === "modes") {
    if (t.type === "fail" || t.type === "unassigned" || t.type === "pos") return { zones: ["into"] };
    if (t.type === "mode") return { zones: t.ref.functional_failure_id ? ["before", "after"] : ["into"] };
    const many = src.keys.length > 1;
    return no(`${many ? "Failure modes go" : "A failure mode goes"} under a functional failure: drop ${many ? "them" : "it"} on one, or before or after a failure mode.`);
  }
  if (src.kind === "task") {
    if (t.type === "mode" || t.type === "pos") return t.key === src.keys[0] ? { zones: [] } : { zones: ["into"] };
    return no("A task goes on a failure mode (it moves to that one) or on a position: drop it on one.");
  }
  return { zones: [] };
}

// The zone under the pointer: `frac` is how far down the row it is (0-1).
export function zoneAt(zones, frac) {
  if (!zones.length) return null;
  const into = zones.includes("into");
  const edges = zones.includes("before");
  if (into && !edges) return "into";
  if (!into) return frac < 0.5 ? "before" : "after";
  return frac < 0.28 ? "before" : frac > 0.72 ? "after" : "into";
}

// The drop worked out: {ops, extraUndo, text, done} to send; {refuse} when it
// can't (said at once); {none: true} when it would change nothing. extraUndo:
// reorders the Undo adds after the server's own undo list, so a moved thing
// comes back to exactly where it was. text: what it will do (the tooltip);
// done: what it did (the toast).
export function planDrop(whole, src, targetKey, zone) {
  const { zones, reason } = dropZones(whole, src, targetKey);
  if (!zones.length) return reason ? { refuse: reason } : { none: true };
  if (!zones.includes(zone)) zone = zones.includes("into") ? "into" : zones[0];
  const t = whole.rows.get(targetKey);
  const what = sourceWords(whole, src);
  const plan = (ops, text, done, extraUndo = []) => ({ ops, text, done, extraUndo });
  const where = (z) => (z === "before" ? "before" : "after");
  if (src.kind === "fn") return planFunction(whole, src, t, zone, what, plan, where);
  if (src.kind === "std") return planStandard(whole, src, t, zone, what, plan, where);
  if (src.kind === "fail") return planFailure(whole, src, t, zone, what, plan, where);
  if (src.kind === "modes") return planModes(whole, src, t, zone, what, plan, where);
  if (src.kind === "task") return planTask(whole, src, t, what, plan);
  return { none: true };
}

function planFunction(whole, src, t, zone, what, plan, where) {
  const f = whole.rows.get(src.keys[0]);
  const from = f.ref.position_id;
  const back = [op("reorder", { parent_id: from, ids: fnIdsOf(whole, from) })];
  if (t.type === "pos") {
    if (t.key === from) return { refuse: "It's on this position already. To change the order, drop it before or after another function." };
    return plan([op("move_function", { function_id: f.key, position_id: t.key })],
      `Move ${what} to ${q(textOf(t))}, with everything under it`, `Moved ${what} to ${q(textOf(t))}.`, back);
  }
  const to = t.ref.position_id;
  const ids = place(fnIdsOf(whole, to), [f.key], t.key, zone);
  if (to === from) {
    if (same(ids, fnIdsOf(whole, to))) return { none: true };
    return plan([op("reorder", { parent_id: to, ids })], `Put ${what} ${where(zone)} ${q(textOf(t))}`, `Moved ${what}.`);
  }
  const pos = whole.rows.get(to);
  return plan([op("move_function", { function_id: f.key, position_id: to }), op("reorder", { parent_id: to, ids })],
    `Move ${what} to ${q(textOf(pos))}, ${where(zone)} ${q(textOf(t))}`, `Moved ${what} to ${q(textOf(pos))}.`, back);
}

function planStandard(whole, src, t, zone, what, plan, where) {
  const s = whole.rows.get(src.keys[0]);
  const from = s.ref.function_id;
  const std = s.ref.standard_id;
  const fails = failsUnder(whole, s.key);
  const toFn = t.type === "fn" ? t.key : t.ref.function_id;
  const fnRow = whole.rows.get(toFn);
  const place2 = t.type === "fn" || t.ref.legacy ? null : t.ref.standard_id;
  if (toFn === from) {
    if (!place2) return { refuse: "It's a performance standard of this function already. To change the order, drop it before or after another performance standard." };
    // The order among the function's standards (its failures go with it on screen).
    const ids = place(stdIdsOf(whole, from), [std], place2, zone);
    if (same(ids, stdIdsOf(whole, from))) return { none: true };
    return plan([op("reorder_standards", { function_id: from, standard_ids: ids })], `Put ${what} ${where(zone)} ${q(textOf(t))}`, `Moved ${what}.`);
  }
  // To another function: the standard, then each functional failure under it
  // (with its failure modes, decisions and tasks), breaching it again there.
  // One batch: all of it moves, or none. Undo moves them back (the server's
  // undo list) and puts the standards and failures back in their order.
  const ops = [op("move_standard", { standard_id: std, function_id: toFn }),
    ...fails.map((ff) => op("move_functional_failure", { functional_failure_id: ff, function_id: toFn, standard_id: std }))];
  if (place2) ops.push(op("reorder_standards", { function_id: toFn, standard_ids: place(stdIdsOf(whole, toFn), [std], place2, zone) }));
  const back = [op("reorder_standards", { function_id: from, standard_ids: stdIdsOf(whole, from) })];
  if (fails.length) back.push(op("reorder", { parent_id: from, ids: failIdsOf(whole, from) }));
  const carry = fails.length ? `, with ${fails.length === 1 ? "its failure modes and tasks" : "their failure modes and tasks"}` : "";
  return plan(ops, `Move ${what} to ${q(textOf(fnRow))}${place2 ? `, ${where(zone)} ${q(textOf(t))}` : ""}${carry}`,
    `Moved ${what} to ${q(textOf(fnRow))}.`, back);
}

function planFailure(whole, src, t, zone, what, plan, where) {
  const x = whole.rows.get(src.keys[0]);
  const from = x.ref.function_id;
  const had = x.ref.standard?.id || null;
  const back = [op("reorder", { parent_id: from, ids: failIdsOf(whole, from) })];
  const moveTo = (fnKey, standardId) => op("move_functional_failure", {
    functional_failure_id: x.key, function_id: fnKey, ...(standardId ? { standard_id: standardId } : {}),
  });
  if (t.type === "fail") {
    const toFn = t.ref.function_id;
    const theirs = hasList(whole, toFn) ? t.ref.standard?.id || null : null;
    const ids = place(failIdsOf(whole, toFn), [x.key], t.key, zone);
    if (toFn === from) {
      const ops = [];
      if (hasList(whole, from) && theirs !== had) {
        ops.push(op("update_functional_failure", { functional_failure_id: x.key, standard_id: theirs || "none" }));
      }
      if (!same(ids, failIdsOf(whole, from))) ops.push(op("reorder", { parent_id: from, ids }));
      if (!ops.length) return { none: true };
      return plan(ops, `Put ${what} ${where(zone)} ${q(textOf(t))}`, `Moved ${what}.`);
    }
    const fnRow = whole.rows.get(toFn);
    return plan([moveTo(toFn, theirs), op("reorder", { parent_id: toFn, ids })],
      `Move ${what} under ${q(textOf(fnRow))}, ${where(zone)} ${q(textOf(t))}`, `Moved ${what} under ${q(textOf(fnRow))}.`, back);
  }
  const toFn = t.type === "fn" ? t.key : t.ref.function_id;
  const fnRow = whole.rows.get(toFn);
  const standard = t.type === "std" && !t.ref.legacy ? t.ref.standard_id : null;
  if (toFn === from) {
    if (t.type === "fn" || t.ref.legacy) return { refuse: "It's under this function already. Drop it on one of its performance standards, or before or after another functional failure." };
    if ((standard || null) === had) return { refuse: standard ? "It breaches this performance standard already." : "It's under No performance standard already." };
    return plan([op("update_functional_failure", { functional_failure_id: x.key, standard_id: standard || "none" })],
      standard ? `${what} breaches ${q(textOf(t))} instead` : `${what} breaches no one performance standard (the whole function)`,
      standard ? `${what} now breaches ${q(textOf(t))}.` : `${what} now breaches the whole function.`);
  }
  const note = standard ? `, breaching ${q(textOf(t))}` : hasList(whole, toFn) ? ", under No performance standard" : "";
  return plan([moveTo(toFn, standard)], `Move ${what} under ${q(textOf(fnRow))}${note}, with its failure modes`,
    `Moved ${what} under ${q(textOf(fnRow))}.`, back);
}

function planModes(whole, src, t, zone, what, plan, where) {
  const modes = src.keys.map((k) => whole.rows.get(k)).filter(Boolean);
  const many = modes.length > 1;
  const backs = [];
  for (const ff of new Set(modes.map((m) => m.ref.functional_failure_id).filter(Boolean))) {
    backs.push(op("reorder", { parent_id: ff, ids: modeIdsOf(whole, ff) }));
  }
  const backsFor = (ff) => backs.filter((b) => b.args.parent_id !== ff);
  const posName = (pos) => q(textOf(whole.rows.get(pos)));
  // The operations that put them under functional failure `ff` (null: under
  // none) of position `pos`: assigned there, or moved from another position.
  const under = (pos, ff) => {
    const ops = [];
    for (const m of modes) {
      if (m.ref.position_id !== pos) {
        ops.push(op("move", { failure_mode_id: m.key, position_id: pos, ...(ff ? { functional_failure_id: ff } : {}) }));
      } else if ((m.ref.functional_failure_id || null) !== (ff || null)) {
        ops.push(op("assign", { failure_mode_id: m.key, ...(ff ? { functional_failure_id: ff } : {}) }));
      }
    }
    return ops;
  };
  if (t.type === "mode" && t.ref.functional_failure_id) {
    const ff = t.ref.functional_failure_id;
    const ops = under(t.ref.position_id, ff);
    const moving = ops.length > 0;
    const ids = place(modeIdsOf(whole, ff), modes.map((m) => m.key), t.key, zone);
    if (!same(ids, modeIdsOf(whole, ff))) ops.push(op("reorder", { parent_id: ff, ids }));
    if (!ops.length) return { none: true };
    const ffRow = whole.rows.get(ff);
    return plan(ops, moving ? `Put ${what} under ${q(textOf(ffRow))}, ${where(zone)} ${q(textOf(t))}` : `Put ${what} ${where(zone)} ${q(textOf(t))}`,
      moving ? `Moved ${what} under ${q(textOf(ffRow))}.` : `Moved ${what}.`, backsFor(ff));
  }
  if (t.type === "fail") {
    const ops = under(t.ref.position_id, t.key);
    if (!ops.length) return { refuse: many ? "They're all under it already." : "It's under this functional failure already." };
    const away = ops.some((o) => o.do === "failure_modes.move");
    return plan(ops, `Put ${what} under ${q(textOf(t))}${away ? ` on ${posName(t.ref.position_id)}, with decisions and tasks` : ""}`,
      `Moved ${what} under ${q(textOf(t))}.`, backsFor(t.key));
  }
  const pos = t.type === "pos" ? t.key : t.ref.position_id;
  if (t.type === "pos") {
    // Onto a position: the modes on another position move there, under none.
    const ops = under(pos, null).filter((o) => o.do === "failure_modes.move");
    if (!ops.length) {
      return { refuse: `${many ? "They're" : "It's"} on this position already: drop ${many ? "them" : "it"} on a functional failure, or on “Not under a functional failure”.` };
    }
    return plan(ops, `Move ${what} to ${posName(pos)}, not under a functional failure`, `Moved ${what} to ${posName(pos)}.`, backs);
  }
  const ops = under(pos, null);
  if (!ops.length) return { refuse: `${many ? "They're" : "It's"} not under a functional failure already.` };
  return plan(ops, `Put ${what} on ${posName(pos)}, not under a functional failure`,
    `Moved ${what} to ${posName(pos)}, not under a functional failure.`, backs);
}

function planTask(whole, src, t, what, plan) {
  const from = whole.rows.get(src.keys[0]);
  const tk = src.task;
  if (t.type === "pos") {
    if (t.key === tk.position_id) return { refuse: "The task is on this position already." };
    return plan([taskOp("move", { task_id: tk.id, position_id: t.key })], `Move ${what} to ${q(textOf(t))}`, `Moved ${what} to ${q(textOf(t))}.`);
  }
  if ((t.ref.tasks || []).some((x) => x.id === tk.id)) return { refuse: "The task prevents this failure mode already." };
  const ops = [taskOp("unlink", { task_id: tk.id, failure_mode_id: from.key })];
  // A task serves failure modes on its own position and the positions inside it.
  const reach = positionWithin(whole, t.ref.position_id, tk.position_id);
  if (!reach) ops.push(taskOp("move", { task_id: tk.id, position_id: t.ref.position_id }));
  ops.push(taskOp("link", { task_id: tk.id, failure_mode_id: t.key }));
  return plan(ops, `Move ${what} to ${q(textOf(t))}${reach ? "" : ` on ${q(textOf(whole.rows.get(t.ref.position_id)))}`}: it stops preventing ${q(textOf(from))}`,
    `Moved ${what} to ${q(textOf(t))}.`);
}

// The row to show after a drop: the first thing moved (a task: the mode it
// went to).
export const shownAfter = (src, targetKey) => (src.kind === "task" ? targetKey : src.keys[0]);

// The Undo batch: the server's undo list, then the reorders that put moved
// things back in their places.
export const undoBatch = (answer, extraUndo = []) => [...(answer?.undo || []), ...extraUndo];

// What the server said beyond "done" (links removed, tasks unlinked), once
// each.
export function answerNotes(answer) {
  const out = [];
  const results = answer?.results || [];
  // Failures the same batch moves on (a standard dragged with its failures):
  // a standard's "they stay with the old function" isn't so, so it's not said.
  const carried = new Set(results.filter((r) => r.do === "failure_modes.move_functional_failure").map((r) => r.result?.moved));
  for (const r of results) {
    if (r.do === "failure_modes.move_standard" && (r.result?.unlinked_functional_failure_ids || []).every((id) => carried.has(id))) continue;
    const note = r.result?.note;
    if (note && !out.includes(note)) out.push(note);
  }
  return out;
}

// A refusal in plain words: the server's "Nothing was changed: op 1
// (failure_modes.move): It's already on Pump A…" without the batch's
// bookkeeping.
export function refusalText(err) {
  const raw = String(err?.data?.failed?.error || err?.data?.detail || err?.message || "It can't go there.");
  return raw.replace(/^Nothing was changed:\s*/, "").replace(/^op \d+ \([\w.]+\):\s*/, "").trim();
}

// ---- Move to… (the row menus and the panel's ⋯: the keyboard's, a phone's and a long way's move) ----
// One picker for every kind: the asset tree with the RCM in it (the same rows,
// names and icons as the Explorer's tree), where the places that kind can go
// are picked and the rest are greyed, each with a short reason. Picking one is
// a drop "into" that row (planDrop with zone "into"), so it's the same move,
// the same checks and the same Undo.
//
// The places each kind goes:
// - a function: a position;
// - a performance standard: a function;
// - a functional failure: a performance standard, a function's "No
//   performance standard" (offered on every function with a list, even
//   before one is there), or a function with no list;
// - failure modes: a functional failure, or a position's "Not under a
//   functional failure" (offered on every position);
// - a task: a failure mode, or a position (the task moves there).

const MOVE_REASON = {
  std: { pos: "A performance standard goes under a function." },
  fail: {
    pos: "A functional failure goes under a performance standard, or a function's “No performance standard”.",
    fn: "Pick one of its performance standards, or its “No performance standard”.",
  },
  modes: { any: "A failure mode goes under a functional failure, or a position's “Not under a functional failure”." },
  modesMany: { any: "Failure modes go under a functional failure, or a position's “Not under a functional failure”." },
  task: { any: "A task goes on a failure mode, or on a position." },
};
const HERE = "It's here now.";

// The rows a kind's picker shows (the rest are left out): a function's, only
// positions; a standard's, down to functions; and so on.
const SHOWS = {
  fn: new Set(["pos"]),
  std: new Set(["pos", "fn"]),
  fail: new Set(["pos", "fn", "std", "nostd"]),
  modes: new Set(["pos", "fn", "std", "nostd", "fail", "unassigned"]),
  task: new Set(["pos", "fn", "std", "nostd", "fail", "unassigned", "mode"]),
};

// The whole tree plus the empty groups a picker offers ("No performance
// standard" on a function with a list, "Not under a functional failure" on a
// position) where the tree has none yet: rows of their own (keys N:… and
// U:…), so planDrop treats them as it treats the real ones.
export function withMoveGroups(whole) {
  const rows = new Map(whole.rows);
  for (const r of whole.rows.values()) {
    if (r.type === "pos" && !rows.has(`U:${r.key}`)) {
      rows.set(`U:${r.key}`, { key: `U:${r.key}`, type: "unassigned", parent: r.key, kids: [], depth: r.depth + 1, synthetic: true,
        ref: { id: `U:${r.key}`, text: "Not under a functional failure", position_id: r.key } });
    }
    if (r.type === "fn" && (r.ref.standards || []).length && !rows.has(`N:${r.key}`)) {
      rows.set(`N:${r.key}`, { key: `N:${r.key}`, type: "nostd", parent: r.key, kids: [], depth: r.depth + 1, synthetic: true,
        ref: { id: `N:${r.key}`, text: "No performance standard", position_id: r.ref.position_id, function_id: r.key, function_text: r.ref.text || "" } });
    }
  }
  return { ...whole, rows };
}

// Where what's moved is now (the row it would be dropped "into" to stay put).
function hereOf(whole, src) {
  const r = whole.rows.get(src.keys[0]);
  if (!r) return null;
  if (src.kind === "task") return r.key;
  if (src.kind === "fn") return r.ref.position_id;
  if (src.kind === "std") return r.ref.function_id;
  if (src.kind === "fail") {
    const up = whole.rows.get(r.parent);
    return up?.type === "std" && up.ref.legacy ? up.ref.function_id : r.parent;
  }
  if (src.kind === "modes") {
    if (src.keys.length > 1) return null;
    return r.ref.functional_failure_id || `U:${r.ref.position_id}`;
  }
  return null;
}

// The picker's tree for what's moved (`src`, rcmDrag.dragSource):
// {nodes: Map key → {key, type, name, depth, parent, kids, ok, reason, here, fitted}, roots, here}.
// ok: it can go there (picking it moves it); else `reason` says why not, in
// a few words. here: where it is now. Branches with nowhere to go and not
// where it is are left out.
export function moveTree(whole, src) {
  const nodes = new Map();
  const roots = [];
  if (!src || !SHOWS[src.kind]) return { nodes, roots, here: null };
  const w = withMoveGroups(whole);
  const shows = SHOWS[src.kind];
  const here = hereOf(w, src);
  const words = MOVE_REASON[src.kind === "modes" && src.keys.length > 1 ? "modesMany" : src.kind] || {};
  const judge = (r) => {
    if (r.key === here) return { ok: false, reason: HERE };
    const sel = selectable(w, src, r);
    if (!sel) return { ok: false, reason: words[r.type] || words.any || "It can't go there." };
    const p = planDrop(w, src, r.key, "into");
    if (p.ops) return { ok: true, reason: null };
    if (p.none || /already/i.test(p.refuse || "")) return { ok: false, reason: HERE };
    return { ok: false, reason: p.refuse || "It can't go there." };
  };
  // The RCM rows under a row, the empty groups where the tree would put them.
  const kidsOf = (r) => {
    const ks = [...(r.kids || [])];
    if (r.type === "fn" && w.rows.get(`N:${r.key}`)?.synthetic) ks.push(`N:${r.key}`);
    if (r.type === "pos" && w.rows.get(`U:${r.key}`)?.synthetic) {
      const at = ks.findIndex((k) => w.rows.get(k)?.type === "pos");
      ks.splice(at < 0 ? ks.length : at, 0, `U:${r.key}`);
    }
    return ks;
  };
  const seen = new Set();
  // Returns the node keys kept under `keys`.
  const walk = (keys, depth, parent) => {
    const out = [];
    for (const k of keys) {
      const r = w.rows.get(k);
      if (!r || seen.has(k)) continue;
      seen.add(k);
      // The pane's own headings and items carrying positions: what's inside them, at this depth.
      if (r.type === "group" || r.type === "item" || r.type === "loc") {
        out.push(...walk(r.kids, depth, parent));
        continue;
      }
      if (!shows.has(r.type)) continue;
      // A functional failure under a function's one text: the function is the place (the text's row isn't shown).
      if (src.kind === "fail" && r.type === "std" && r.ref.legacy) continue;
      // What's moved, and what's inside it: never shown as a place.
      if (src.kind !== "task" && src.keys.includes(k)) continue;
      const node = { key: k, type: r.type, name: (r.type === "pos" ? r.ref.name : r.ref.text) || "(no name)", depth, parent,
        kids: [], fitted: r.type === "pos" ? !!r.ref.item : false, ...judge(r) };
      node.here = k === here;
      nodes.set(k, node);
      node.kids = walk(kidsOf(r), depth + 1, k);
      if (node.ok || node.here || node.kids.length) out.push(k);
      else nodes.delete(k);
    }
    return out;
  };
  roots.push(...walk(w.roots || [], 0, null));
  return { nodes, roots, here: nodes.has(here) ? here : null };
}

// Is a row of a kind that what's moved goes into (before the server's and the
// tree's own checks)?
function selectable(whole, src, r) {
  switch (src.kind) {
    case "fn": return r.type === "pos";
    case "std": return r.type === "fn";
    case "fail": return r.type === "std" || r.type === "nostd" || (r.type === "fn" && !(r.ref.standards || []).length);
    case "modes": return r.type === "fail" || r.type === "unassigned";
    case "task": return r.type === "mode" || r.type === "pos";
    default: return false;
  }
}

// The drop a picked place makes: planDrop on the tree with its empty groups.
export const planMoveTo = (whole, src, key) => planDrop(whole.rows.has(key) ? whole : withMoveGroups(whole), src, key, "into");

// What the picker lists: with words typed, the places whose name has them and
// the rows above them (all open); else every row whose rows above are open.
// [{...node, open, match}] in tree order.
export function visibleNodes(tree, { query = "", open = new Set() } = {}) {
  const out = [];
  const t = query.trim().toLowerCase();
  let keep = null;
  if (t) {
    keep = new Set();
    for (const n of tree.nodes.values()) {
      if (!n.name.toLowerCase().includes(t)) continue;
      for (let k = n.key; k != null && !keep.has(k); k = tree.nodes.get(k)?.parent) keep.add(k);
    }
  }
  const walk = (keys) => {
    for (const k of keys) {
      const n = tree.nodes.get(k);
      if (!n || (keep && !keep.has(k))) continue;
      const isOpen = keep ? n.kids.some((c) => keep.has(c)) : open.has(k);
      out.push({ ...n, open: isOpen, match: !!t && n.name.toLowerCase().includes(t) });
      if (isOpen) walk(n.kids);
    }
  };
  walk(tree.roots);
  return out;
}

// What's open when the picker opens: the way down to where it is now (else
// the first level).
export function moveOpenAtStart(tree) {
  const open = new Set();
  if (tree.here) for (let k = tree.nodes.get(tree.here)?.parent; k != null; k = tree.nodes.get(k)?.parent) open.add(k);
  if (!open.size) for (const k of tree.roots) open.add(k);
  return open;
}

// The place picked in Move to…, kept when the tree is read again (the
// Explorer rebuilds it on every reload) while it's still there and can still
// be picked; else nothing picked.
export function keptMoveTarget(tree, to) {
  const n = to ? tree.nodes.get(to) : null;
  return n && n.ok ? to : "";
}

// What a move carries, as a string: the same thing moving gives the same
// string however often the tree is rebuilt.
export const moveSourceKey = (src) => (src ? `${src.kind}:${src.keys.join(",")}:${src.task?.id || ""}` : "");

// Move up / Move down in a row's menu (functions, functional failures,
// failure modes): the drop before the sibling above, or after the one below.
// null when there's none that way.
export function stepTarget(whole, key, by) {
  const r = whole.rows.get(key);
  if (!r) return null;
  let sibs;
  if (r.type === "fn") sibs = fnIdsOf(whole, r.ref.position_id);
  else if (r.type === "fail") sibs = (whole.rows.get(r.parent)?.kids || []).filter((k) => whole.rows.get(k)?.type === "fail");
  else if (r.type === "mode" && r.ref.functional_failure_id) sibs = (whole.rows.get(r.parent)?.kids || []).filter((k) => whole.rows.get(k)?.type === "mode");
  else return null;
  const i = sibs.indexOf(key);
  const j = i + by;
  if (i < 0 || j < 0 || j >= sibs.length) return null;
  return { key: sibs[j], zone: by < 0 ? "before" : "after" };
}

// The moves a row's menu adds (before its Delete): Move to… for what can be
// dragged (always: it's the way to move without dragging, and a long way),
// Move up / down among siblings (`steps`: only where there's no dragging; a
// standard has its own), and on a failure mode with a task, Move a task….
// With failure modes picked, Move to… takes them all. [{id, label, disabled?}]
export function moveItems(whole, r, { picked = null, steps = true } = {}) {
  const s = r ? dragSource(whole, r.key, { picked }) : null;
  if (!s) return [];
  const n = s.kind === "modes" ? s.keys.length : 1;
  const out = [{ id: "move-to", label: n > 1 ? `Move ${n} failure modes to…` : "Move to…" }];
  if (steps && s.kind !== "std" && !(r.type === "mode" && !r.ref.functional_failure_id)) {
    out.push({ id: "step-up", label: "Move up", disabled: !stepTarget(whole, r.key, -1) });
    out.push({ id: "step-down", label: "Move down", disabled: !stepTarget(whole, r.key, 1) });
  }
  if (r.type === "mode" && (r.ref.tasks || []).some((t) => t.id)) out.push({ id: "move-task", label: "Move a task…" });
  return out;
}
