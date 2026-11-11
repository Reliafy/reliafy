// The Explorer's Missions tab (Derryn, 9 Nov 2026: "Products need an RBD tab, called Missions";
// "Missions are RBDs, so they belong to positions"): a tree-table like the Modelling tab. Under
// each position with an RBD hang that RBD's missions (name, phases, length, the chance of
// completing it once worked out); a position with none says so and offers to build one. Under a
// mission, each phase's row has its own length in the same column (the mission's is their total). A
// mission is the RBD flown through phases: each phase its duration, the blocks it doesn't need,
// vote counts and its own Use / Environment covariate values. Missions never come down from the
// position above: a sub-position has its own RBD's missions. Pure functions, tested in
// explorerMissions.test.js; the cells are drawn by MissionTable.jsx, a mission opens in the table
// area (MissionPane.jsx). The links come from GET /api/maintenance/position-missions.
//
// One RBD per mission: Add a mission builds the new mission an RBD of its own from what's inside
// the position (rows with rbd.mission_rbd); missions stored on a position's RBD before that keep
// working as they were. Each phase sets each block Working, Standby or Not needed (blockState,
// withBlockState: the pane's phase × block grid, MissionBlockGrid.jsx).
//
// Under each mission hang its phases, one row each, in order (Derryn, 10 Nov 2026: "on the
// missions page I need to be able to add phases below the mission in the tree"). The menus
// (right-click, ⋯, Shift+F10) start with what goes under the row: a position's Add a mission (or
// Build an RBD…), a mission's Add a phase (saved at the end, then opened in the pane to be named),
// a phase's Open… (the pane at that phase), Move earlier / Move later, Delete…. A phase is changed
// through the mission's own update route, with the pane's phase helpers (editablePhase, newPhase,
// movePhase, cleanPhases: changedPhases).

import { reliabilityPercent } from "./rbdMission.js";

export const MISSION_TYPE = "mission";
export const PHASE_TYPE = "phase";
// A row of the Missions tab's own: a mission, or one of its phases.
export const isMissionRow = (r) => r?.type === MISSION_TYPE || r?.type === PHASE_TYPE;
export const isPhaseRow = (r) => r?.type === PHASE_TYPE;
export const missionKey = (rbdId, missionId) => `MS:${rbdId}:${missionId}`;
export const phaseKey = (rbdId, missionId, i) => `MP:${rbdId}:${missionId}:${i}`;
// Phases a mission can have (the pane's Add a phase stops there too).
export const MAX_PHASES = 50;

// Reads of the missions that can overlap (one after a save, one more once the saved mission's
// result is worked out): `const latest = asked()` as each read starts; when its answer comes,
// `latest()` says whether it is still the last one asked for. An earlier read's answer, arriving
// late, is then dropped rather than put over the newer one.
export function latestOnly() {
  let last = 0;
  return () => {
    const mine = ++last;
    return () => mine === last;
  };
}

// The pane's address value (?mission=<rbd id>:<mission id>&on=<position id>) and back.
export const missionParam = (rbdId, missionId) => `${rbdId}:${missionId}`;
export function parseMissionParam(value) {
  const text = String(value || "");
  const at = text.indexOf(":");
  if (at <= 0 || at === text.length - 1) return null;
  return { rbdId: text.slice(0, at), missionId: text.slice(at + 1) };
}

export const MISSION_COLUMNS = [
  { id: "phases", label: "Phases", width: 230, title: "How many phases, and their names" },
  { id: "duration", label: "Length", width: 130, num: true, title: "A phase's own length; a mission's is every phase added up. In the RBD's unit" },
  { id: "reliability", label: "Completes", width: 150, num: true, title: "The chance the mission completes, once worked out" },
  { id: "rbd", label: "RBD", width: 200, title: "The diagram the mission is flown on" },
];
export const MISSION_TREE_HEAD = "Position, and its missions";

const noStatus = () => ({ overdue: 0, open_work: 0, alarms: 0, next_due: null, not_analysed: 0, positions: 0, empty: 0 });

// A number to 3–4 significant figures; "—" for none.
export function fmt(v) {
  const x = Number(v);
  if (v == null || v === "" || !Number.isFinite(x)) return "—";
  if (x !== 0 && (Math.abs(x) < 0.001 || Math.abs(x) >= 1e9)) return x.toPrecision(3);
  const sig = Math.abs(x) >= 1000 ? 4 : 3;
  return Number(x.toPrecision(sig)).toLocaleString("en-AU", { maximumFractionDigits: 6 });
}
export const unitWord = (unit) => String(unit || "").trim().toLowerCase();
// "12.5 hours", "3 cycles"; a number alone with no unit.
export function lengthText(v, unit) {
  if (v == null) return "—";
  let u = unitWord(unit);
  if (Number(v) === 1 && u.endsWith("s")) u = u.slice(0, -1); // "1 hour"
  return `${fmt(v)}${u ? ` ${u}` : ""}`;
}
export const pct = reliabilityPercent;

// A mission's "Completes" cell: its chance, once worked out ("—" before), or how far it got.
export function completesText(m) {
  const r = m?.result;
  if (!r) return "—";
  if (r.reliability != null) return pct(r.reliability);
  return r.through ? `Waiting · ${pct(r.through.reliability)} to ${r.through.phase}` : "Needs values";
}

// The tree with each position's missions in it. The display given is left as it is; position rows
// gain `msum` (their own: rbds, missions), `mall` (theirs and inside) and `rbds` (their RBD links).
// `hasModel`: the positions whose model in use can be a mission's one block (GET
// /position-missions: has_model), so a leaf can have a mission too.
export function graftMissions(display, links = [], hasModel = []) {
  const withModel = new Set(hasModel || []);
  const rows = new Map();
  for (const [k, r] of display.rows) rows.set(k, { ...r, kids: [...r.kids] });
  const out = { ...display, rows, missions: true };
  for (const r of rows.values()) {
    if (r.type === "pos") Object.assign(r, { msum: { rbds: 0, missions: 0 }, mall: { rbds: 0, missions: 0 }, rbds: [], hasModel: withModel.has(r.key) });
  }
  const byPos = new Map();
  for (const link of links) {
    const p = rows.get(link.position_id);
    if (!p || p.type !== "pos") continue;
    if (!byPos.has(p.key)) byPos.set(p.key, []);
    byPos.get(p.key).push(link);
  }
  for (const [pk, list] of byPos) {
    const p = rows.get(pk);
    const keys = [];
    for (const link of list) {
      p.rbds.push(link);
      if (!link.rbd) continue;
      p.msum.rbds += 1;
      for (const m of link.missions || []) {
        const key = missionKey(link.rbd.id, m.id);
        const names = m.phase_names || [];
        const lengths = m.phase_durations || [];
        const kids = names.map((_, i) => phaseKey(link.rbd.id, m.id, i));
        rows.set(key, {
          key, type: MISSION_TYPE, parent: pk, kids, depth: p.depth + 1, own: noStatus(), sum: noStatus(),
          ref: {
            name: m.name, mission: m, rbd: link.rbd, position_id: pk, many: list.filter((l) => l.rbd).length > 1,
            search: [m.name, ...names, link.rbd.name].filter(Boolean).join(" ").toLowerCase(),
          },
        });
        names.forEach((name, i) => rows.set(kids[i], {
          key: kids[i], type: PHASE_TYPE, parent: key, kids: [], depth: p.depth + 2, own: noStatus(), sum: noStatus(),
          ref: {
            name, phase: { index: i, name, of: names.length, duration: lengths[i] ?? null }, mission: m, rbd: link.rbd, position_id: pk,
            search: String(name || "").toLowerCase(),
          },
        }));
        keys.push(key);
        p.msum.missions += 1;
      }
    }
    p.kids = [...keys, ...p.kids];
  }
  const done = new Set();
  const total = (k) => {
    const r = rows.get(k);
    if (done.has(k)) return r.mall;
    done.add(k);
    const t = { ...r.msum };
    for (const c of r.kids) {
      if (rows.get(c)?.type === "pos") {
        const s = total(c);
        t.rbds += s.rbds;
        t.missions += s.missions;
      }
    }
    r.mall = t;
    return t;
  };
  for (const r of rows.values()) if (r.type === "pos") total(r.key);
  return out;
}

// Positions inside it to build an RBD from (a leaf has none: its own life model is what it has).
const hasInside = (r) => (r?.kids || []).some((k) => !String(k).startsWith("MS:"));
const count = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;

// The position's own linked RBDs (not a mission's own) a mission can start from a copy of.
const usableRbds = (r) => (r?.rbds || []).filter((l) => l.rbd && !l.rbd.mission_rbd && !l.rbd.repairable && !l.rbd.network);
// A position can have a mission when its RBD can be built: from the positions inside, a copy of its
// own non-repairable RBD, or (a leaf) one block from its own model in use.
export const canAddMission = (r) => hasInside(r) || !!r?.hasModel || usableRbds(r).length > 0;

// A position row's roll-up: its own ("2 missions", or "No missions yet · Add a mission" wherever
// one can be added); closed, everything inside it too ("5 missions here and inside").
export function rollupText(r, open = false) {
  if (!r?.msum) return "";
  const own = r.msum;
  const none = canAddMission(r) ? "No missions yet · Add a mission" : "No missions yet";
  if (open) return own.missions ? count(own.missions, "mission") : none;
  const all = r.mall || own;
  if (all.missions) return own.missions === all.missions ? count(all.missions, "mission") : `${count(all.missions, "mission")} here and inside`;
  return none;
}

// The phases cell: "3 phases: Take-off, Survey, Landing".
export function phasesText(m) {
  const n = m?.phases || 0;
  if (!n) return "No phases yet";
  const names = (m.phase_names || []).join(", ");
  return `${count(n, "phase")}${names ? `: ${names}` : ""}`;
}

// A phase row's cells and phone line: "Phase 2 of 3".
export const phaseOfText = (p) => `Phase ${p.index + 1} of ${p.of}`;
// A phase row's own length, in its mission's unit: "0.25 hours" ("" when the read has none).
export const phaseLengthText = (p, unit) => (p?.duration == null ? "" : lengthText(p.duration, unit));

// A mission row's ⋯ (Add a phase, then Open, Show the RBD, Delete…), a phase row's (Open…, Move
// earlier, Move later, Delete…) and a position's (Add a mission, Open the RBD, Build…).
export function missionRowActions(r, { viewOnly = null } = {}) {
  const off = viewOnly ? { disabled: true, reason: viewOnly, title: viewOnly } : {};
  if (isPhaseRow(r)) {
    const { index, of } = r.ref.phase;
    const first = "It's the first phase already.";
    const last = "It's the last phase already.";
    return [
      { id: "mission-phase-open", label: "Open…" },
      { id: "mission-phase-earlier", label: "Move earlier", ...(viewOnly ? off : index === 0 ? { disabled: true, reason: first, title: first } : {}) },
      { id: "mission-phase-later", label: "Move later", ...(viewOnly ? off : index >= of - 1 ? { disabled: true, reason: last, title: last } : {}) },
      { id: "mission-phase-delete", label: "Delete…", danger: true, ...off },
    ];
  }
  const full = `A mission has at most ${MAX_PHASES} phases.`;
  return [
    { id: "mission-phase-add", label: "Add a phase",
      ...(viewOnly ? off : (r?.ref?.mission?.phases || 0) >= MAX_PHASES ? { disabled: true, reason: full, title: full } : {}) },
    { separator: true },
    { id: "mission-open", label: "Open" },
    { id: "mission-rbd", label: r?.ref?.rbd?.mission_rbd ? "Open its RBD" : "Show the RBD" },
    { id: "mission-delete", label: "Delete…", ...off },
  ];
}
// A position's menu (one RBD per mission): Add a mission builds the mission an RBD of its own from
// what's inside the position (or from a copy of the position's own non-repairable RBD where it has
// nothing inside, else one block from its own model in use); then Open for each RBD linked to the position, and Build an RBD from what's
// inside… while it has none of its own.
export function positionMissionActions(r, { viewOnly = null } = {}) {
  const off = viewOnly ? { disabled: true, reason: viewOnly, title: viewOnly } : {};
  const linked = (r?.rbds || []).filter((l) => l.rbd && !l.rbd.mission_rbd);
  const out = [];
  if (canAddMission(r)) out.push({ id: "mission-new", label: "Add a mission", ...off });
  else {
    const why = linked.length ? "Missions are flown on a non-repairable block diagram: give it a life model, or add positions inside it"
      : "Give it a life model on the Modelling tab, or add positions inside it: a mission's RBD is built from them";
    out.push({ id: "mission-none", label: "Add a mission", disabled: true, reason: why, title: why });
  }
  for (const l of linked) {
    out.push({ id: `mission-open-rbd:${l.rbd.id}`, label: (linked.length > 1 ? `Open ${l.rbd.name}` : "Open the RBD") });
  }
  if (!linked.length) out.push({ id: "mission-build-rbd", label: "Build an RBD from what's inside…", ...off });
  return out;
}

// The positions to open when the tab opens: the way down to the one picked.
export function openForMissions(display, positionKey) {
  const out = [];
  for (let k = positionKey; k != null; k = display.rows.get(k)?.parent) out.push(k);
  return out;
}

// ---- a mission's phases, as the pane edits them -------------------------------------------------

let phaseSeq = 0;
// A phase as the pane holds it: the stored phase with a key of its own (for React) and its
// duration as typed.
export function editablePhase(p = {}) {
  return {
    key: ++phaseSeq,
    name: p.name || "",
    duration: p.duration ?? "",
    not_needed: [...(p.not_needed || [])],
    standby: [...(p.standby || [])],
    votes: { ...(p.votes || {}) },
    values: { ...(p.values || {}) },
    block_values: Object.fromEntries(Object.entries(p.block_values || {}).map(([k, v]) => [k, { ...v }])),
  };
}
// A new phase, named "Phase <n>" from the count (i), skipping a name the phases given already have.
export function newPhase(i, phases = []) {
  const taken = new Set(phases.map((p) => String(p.name || "").trim().toLowerCase()));
  let n = i + 1;
  while (taken.has(`phase ${n}`)) n += 1;
  return editablePhase({ name: `Phase ${n}` });
}

// Move phase i by dir (−1 earlier, +1 later); out of range leaves them.
export function movePhase(phases, i, dir) {
  const j = i + dir;
  if (j < 0 || j >= phases.length) return phases;
  const out = [...phases];
  [out[i], out[j]] = [out[j], out[i]];
  return out;
}

// A value typed as a number when it is one; text (a choice) otherwise; null for blank.
export function typed(v) {
  if (v == null) return null;
  const s = String(v).trim();
  if (s === "") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : s;
}

// The phase with one covariate's value for the phase set (blank takes it off).
export function withValue(phase, name, value) {
  const values = { ...(phase.values || {}) };
  if (String(value ?? "").trim() === "") delete values[name];
  else values[name] = value;
  return { ...phase, values };
}

// The phase with one block's own value for an input set (blank takes it off).
export function withBlockValue(phase, blockId, key, value) {
  const all = { ...(phase.block_values || {}) };
  const one = { ...(all[blockId] || {}) };
  if (String(value ?? "").trim() === "") delete one[key];
  else one[key] = value;
  if (Object.keys(one).length) all[blockId] = one;
  else delete all[blockId];
  return { ...phase, block_values: all };
}

// The phases as they're saved: trimmed names, numeric durations, values typed, nothing empty; and
// what's wrong in plain words. `blocks` and `votes` (the mission's) drop what's no longer there.
export function cleanPhases(rows, { blocks = [], votes = [] } = {}) {
  const ids = new Set(blocks.map((b) => b.id));
  const voteIds = new Set(votes.map((v) => v.id));
  const errors = [];
  const seen = new Set();
  const phases = (rows || []).map((r, i) => {
    const name = String(r.name || "").trim().slice(0, 80);
    const where = name ? `“${name}”` : `Phase ${i + 1}`;
    if (!name) errors.push(`${where} needs a name.`);
    else if (seen.has(name.toLowerCase())) errors.push(`Two phases are named “${name}”.`);
    seen.add(name.toLowerCase());
    const duration = Number(r.duration);
    if (String(r.duration ?? "").trim() === "" || !Number.isFinite(duration) || duration < 0) errors.push(`${where} needs a duration of 0 or more.`);
    const out = { name, duration };
    const nn = (r.not_needed || []).filter((id) => ids.has(id));
    if (nn.length) out.not_needed = [...new Set(nn)];
    const sb = (r.standby || []).filter((id) => ids.has(id) && !nn.includes(id));
    if (sb.length) out.standby = [...new Set(sb)];
    const v = {};
    for (const [id, n] of Object.entries(r.votes || {})) {
      if (!voteIds.has(id) || String(n ?? "").trim() === "") continue;
      const num = Number(n);
      if (!Number.isInteger(num) || num < 1) errors.push(`${where}: a vote count must be a whole number of 1 or more.`);
      else v[id] = num;
    }
    if (Object.keys(v).length) out.votes = v;
    const values = {};
    for (const [k, x] of Object.entries(r.values || {})) {
      const t = typed(x);
      if (t != null) values[k] = t;
    }
    if (Object.keys(values).length) out.values = values;
    const bv = {};
    for (const [id, vals] of Object.entries(r.block_values || {})) {
      if (!ids.has(id)) continue;
      const one = {};
      for (const [k, x] of Object.entries(vals || {})) {
        const t = typed(x);
        if (t != null) one[k] = t;
      }
      if (Object.keys(one).length) bv[id] = one;
    }
    if (Object.keys(bv).length) out.block_values = bv;
    return out;
  });
  return { phases, errors };
}

// A saved mission's phases (GET …/missions/{id}) changed by `change` (editable rows in, rows out)
// and made ready to save: {phases, errors}, as the pane saves them. The tree's Add a phase, Move
// earlier / later and Delete… go through here.
export function changedPhases(detail, change) {
  const rows = (detail?.mission?.phases || []).map(editablePhase);
  return cleanPhases(change(rows), { blocks: detail?.blocks || [], votes: detail?.votes || [] });
}
// The tree's Add a phase: a new one at the end, saved with a duration of 0 until it's given one.
export const withNewPhase = (rows) => [...rows, { ...newPhase(rows.length, rows), duration: 0 }];
// Phase i taken out (movePhase moves one).
export const withoutPhase = (rows, i) => rows.filter((_, j) => j !== i);

// ---- each block's state in each phase (the pane's phase × block grid) --------------------------

// A block in a phase is Working (the default), on Standby or Not needed (stored as the phase's
// `standby` and `not_needed` lists; one or neither).
export const BLOCK_STATES = [
  { id: "working", label: "Working", title: "Running and needed: it ages and can fail in this phase" },
  { id: "standby", label: "Standby", title: "There but not running: it neither ages nor fails in this phase, and counts as working if it was working when the phase began" },
  { id: "off", label: "Not needed", title: "The phase works without it; its clock keeps running, so a failure now is found by a later phase that needs it" },
];
export function blockState(phase, id) {
  if ((phase?.standby || []).includes(id)) return "standby";
  if ((phase?.not_needed || []).includes(id)) return "off";
  return "working";
}
// The phase's lists with block `id` set to `state`: {standby, not_needed} (a patch for the phase).
export function withBlockState(phase, id, state) {
  const standby = (phase?.standby || []).filter((x) => x !== id);
  const notNeeded = (phase?.not_needed || []).filter((x) => x !== id);
  if (state === "standby") standby.push(id);
  else if (state === "off") notNeeded.push(id);
  return { standby, not_needed: notNeeded };
}
// The blocks shown faded in a phase's drawing: those it doesn't need and those standing by.
export const fadedIn = (phase) => new Set([...(phase?.not_needed || []), ...(phase?.standby || [])]);

// ---- a phase's covariates: what each block uses and where it comes from ------------------------

const norm = (t) => String(t ?? "").toLowerCase().replace(/_/g, " ").split(/\s+/).filter(Boolean).join(" ");

// The covariate rows (GET …/missions/{id}: covariates) for one phase, as the server works them out
// (rbd_missions.phase_rows): each row with the phase's value; each block with this phase's own
// (`override`), the value it uses (`used`) and where it comes from (`source`: override, own,
// phase, diagram, default; null when it has none: `missing`); a row's `missing` lists those blocks.
export function phaseCovariates(rows = [], phase = {}) {
  const values = phase.values || {};
  const bv = phase.block_values || {};
  return rows.map((row) => {
    const hit = Object.keys(values).find((k) => norm(k) === norm(row.name));
    const raw = hit != null ? values[hit] : null;
    const value = String(raw ?? "").trim() === "" ? null : raw;
    const blocks = (row.blocks || []).map((b) => {
      const o = (bv[b.id] || {})[b.key];
      const override = String(o ?? "").trim() === "" ? null : o;
      let used = null;
      let source = null;
      if (override != null) [used, source] = [override, "override"];
      else if (b.own != null) [used, source] = [b.own, "own"];
      else if (value != null) [used, source] = [value, "phase"];
      else if (row.diagram != null && row.diagram !== "") [used, source] = [row.diagram, "diagram"];
      else if (b.default != null) [used, source] = [b.default, "default"];
      return { ...b, override, used, source, missing: source == null };
    });
    return { ...row, value, blocks, missing: blocks.filter((b) => b.missing).map((b) => b.label) };
  });
}

// Where a block's value comes from, in words.
export const SOURCE_WORDS = {
  override: "this block's own in this phase",
  own: "set on the block in the RBD",
  phase: "this phase",
  diagram: "the RBD's value",
  default: "the model's default",
};

// "Feeds Input bearing and Output bearing (2 blocks)".
export function feedsText(row) {
  const names = (row?.blocks || []).map((b) => b.label);
  if (!names.length) return "";
  const list = names.length === 1 ? names[0] : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  return `Feeds ${list} (${count(names.length, "block")})`;
}

// The blocks still without a value in a phase: [labels], each once.
export const phaseNeeds = (rows) => [...new Set(rows.flatMap((r) => r.missing || []))];

// A phase's line under its name: "Doesn't need Camera · Motors: 4 of 6 · 2 values set".
export function phaseLine(phase, { blocks = [], votes = [] } = {}) {
  const labelOf = new Map(blocks.map((b) => [b.id, b.label]));
  const skipped = (phase.not_needed || []).filter((id) => labelOf.has(id));
  const standing = (phase.standby || []).filter((id) => labelOf.has(id));
  const parts = [skipped.length ? `Doesn't need ${skipped.length === 1 ? labelOf.get(skipped[0]) : `${skipped.length} blocks`}`
    : standing.length ? "Every block working or standing by" : "Needs every block"];
  if (standing.length) parts.push(`${standing.length === 1 ? labelOf.get(standing[0]) : `${standing.length} blocks`} on standby`);
  for (const v of votes) {
    const n = phase.votes?.[v.id];
    if (String(n ?? "").trim() !== "") parts.push(`${v.label}: ${n} of ${v.inputs}`);
  }
  const nv = Object.values(phase.values || {}).filter((x) => String(x ?? "").trim() !== "").length;
  if (nv) parts.push(`${count(nv, "value")} set`);
  const no = Object.values(phase.block_values || {}).reduce((t, o) => t + Object.keys(o || {}).length, 0);
  if (no) parts.push(`${count(no, "block override")}`);
  return parts.join(" · ");
}

// The answer in words, first: "The mission completes with probability 98.2%. Survey is the
// riskiest phase." Or, waiting on values: "Worked out to the end of Take-off (99.9%); Cruise needs
// values first."
export function answerText(result) {
  if (!result) return "";
  if (result.reliability != null) {
    const risky = result.riskiest && (result.phases || []).length > 1 ? ` ${result.riskiest.name} is the riskiest phase.` : "";
    return `The mission completes with probability ${pct(result.reliability)}.${risky}`;
  }
  const waiting = (result.phases || []).filter((p) => p.waiting).map((p) => p.name);
  const first = waiting[0];
  if (result.through) return `Worked out to the end of ${result.through.phase} (${pct(result.through.reliability)} still going); ${first} needs values first.`;
  return `${first || "The first phase"} needs values first, so nothing is worked out yet.`;
}

// A phase's chance of completing once started: 1 − (failing in it, given it was reached).
export function phaseCompletes(row) {
  if (!row || row.waiting || row.conditional_failure == null) return null;
  return 1 - row.conditional_failure;
}
