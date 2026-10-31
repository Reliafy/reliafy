// Rearranging the RCM tab's tree: what a drag can drop where, and the one
// batch each drop sends (POST /api/maintenance/rcm/apply). The row menus'
// "Move to…" pickers and Move up / down use the same plans, so the keyboard
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

// ---- Move to… (the row menus: the keyboard's and a phone's way to do every move) ----
// The places a row's "Move to…" offers, grouped by position, in tree order:
// [{id, name, depth, items: [{key, label}]}]. Each is a drop "into" that row
// (planDrop with zone "into"), offered only where it would do something.
export function moveChoices(whole, src) {
  if (!src) return [];
  const groups = [];
  const seen = new Set();
  const walk = (keys, depth) => {
    for (const k of keys) {
      const p = whole.rows.get(k);
      if (!p || seen.has(k)) continue;
      seen.add(k);
      if (p.type !== "pos") {
        // The pane's own headings ("No home yet") and items carrying positions: what's inside them.
        if (p.type === "group" || p.type === "item" || p.type === "loc") walk(p.kids, depth);
        continue;
      }
      const items = [];
      const offer = (key, label) => {
        if (planDrop(whole, src, key, "into").ops) items.push({ key, label });
      };
      if (src.kind === "fn" || src.kind === "task") offer(p.key, src.kind === "task" ? "The position itself" : p.ref.name || "(no name)");
      for (const fk of p.kids) {
        const fn = whole.rows.get(fk);
        if (!fn || fn.type !== "fn") continue;
        if (src.kind === "std" || src.kind === "fail") offer(fn.key, textOf(fn));
        for (const sk of fn.kids) {
          const c = whole.rows.get(sk);
          if (!c) continue;
          if (c.type === "std" && src.kind === "fail" && !c.ref.legacy) offer(c.key, `${textOf(fn)} › performance standard ${textOf(c)}`);
          if (c.type === "nostd" && src.kind === "fail") offer(c.key, `${textOf(fn)} › No performance standard`);
          const fails = c.type === "fail" ? [c]
            : (c.type === "std" || c.type === "nostd") ? c.kids.map((x) => whole.rows.get(x)).filter((x) => x?.type === "fail") : [];
          for (const ff of fails) {
            if (src.kind === "modes") offer(ff.key, `${textOf(fn)} › ${textOf(ff)}`);
            if (src.kind === "task") {
              for (const mk of ff.kids) if (whole.rows.get(mk)?.type === "mode") offer(mk, `${textOf(ff)} › ${textOf(whole.rows.get(mk))}`);
            }
          }
        }
      }
      // Its "Not under a functional failure" row (on the mode's own position, that's the one), else the position.
      if (src.kind === "modes") offer(whole.rows.has(`U:${p.key}`) ? `U:${p.key}` : p.key, "Not under a functional failure");
      if (src.kind === "task") {
        for (const mk of whole.rows.get(`U:${p.key}`)?.kids || []) offer(mk, `Not under a functional failure › ${textOf(whole.rows.get(mk))}`);
      }
      if (items.length) groups.push({ id: p.key, name: p.ref.name || "(no name)", depth, items });
      walk(p.kids, depth + 1);
    }
  };
  walk(whole.roots || [], 0);
  return groups;
}

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
// dragged, Move up / down among siblings (a standard has its own), and on a
// failure mode with a task, Move a task…. With failure modes picked, Move to…
// takes them all. [{id, label, disabled?}]
export function moveItems(whole, r, { picked = null } = {}) {
  const s = r ? dragSource(whole, r.key, { picked }) : null;
  if (!s) return [];
  const n = s.kind === "modes" ? s.keys.length : 1;
  const label = {
    fn: "Move to another position…", std: "Move to another function…", fail: "Move to…",
    modes: n > 1 ? `Move ${n} failure modes to…` : "Move to…",
  }[s.kind];
  const out = [{ id: "move-to", label }];
  if (s.kind !== "std" && !(r.type === "mode" && !r.ref.functional_failure_id)) {
    out.push({ id: "step-up", label: "Move up", disabled: !stepTarget(whole, r.key, -1) });
    out.push({ id: "step-down", label: "Move down", disabled: !stepTarget(whole, r.key, 1) });
  }
  if (r.type === "mode" && (r.ref.tasks || []).some((t) => t.id)) out.push({ id: "move-task", label: "Move a task…" });
  return out;
}
