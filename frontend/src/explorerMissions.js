// The Explorer's Missions tab (Derryn, 9 Nov 2026: "Products need an RBD tab, called Missions";
// "Missions are RBDs, so they belong to positions"): a tree-table like the Modelling tab. Under
// each position with an RBD hang that RBD's missions (name, phases, length, the chance of
// completing it once worked out); a position with none says so and offers to build one. A
// mission is the RBD flown through phases: each phase its duration, the blocks it doesn't need,
// vote counts and its own Use / Environment covariate values. Missions never come down from the
// position above: a sub-position has its own RBD's missions. Pure functions, tested in
// explorerMissions.test.js; the cells are drawn by MissionTable.jsx, a mission opens in the table
// area (MissionPane.jsx). The links come from GET /api/maintenance/position-missions.

import { reliabilityPercent } from "./rbdMission.js";

export const MISSION_TYPE = "mission";
export const isMissionRow = (r) => r?.type === MISSION_TYPE;
export const missionKey = (rbdId, missionId) => `MS:${rbdId}:${missionId}`;

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
  { id: "duration", label: "Length", width: 130, num: true, title: "The whole mission, every phase added up, in the RBD's unit" },
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
export const lengthText = (v, unit) => (v == null ? "—" : `${fmt(v)}${unitWord(unit) ? ` ${unitWord(unit)}` : ""}`);
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
export function graftMissions(display, links = []) {
  const rows = new Map();
  for (const [k, r] of display.rows) rows.set(k, { ...r, kids: [...r.kids] });
  const out = { ...display, rows, missions: true };
  for (const r of rows.values()) {
    if (r.type === "pos") Object.assign(r, { msum: { rbds: 0, missions: 0 }, mall: { rbds: 0, missions: 0 }, rbds: [] });
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
        rows.set(key, {
          key, type: MISSION_TYPE, parent: pk, kids: [], depth: p.depth + 1, own: noStatus(), sum: noStatus(),
          ref: {
            name: m.name, mission: m, rbd: link.rbd, position_id: pk, many: list.filter((l) => l.rbd).length > 1,
            search: [m.name, ...(m.phase_names || []), link.rbd.name].filter(Boolean).join(" ").toLowerCase(),
          },
        });
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

const count = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;

// A position row's roll-up: open, its own ("No RBD yet · Build from what's inside…", "No missions
// yet", "2 missions"); closed, everything inside it too ("5 missions inside").
export function rollupText(r, open = false) {
  if (!r?.msum) return "";
  const own = r.msum;
  if (open) {
    if (!own.rbds) return "No RBD yet · Build from what's inside…";
    return own.missions ? count(own.missions, "mission") : "No missions yet · Add a mission";
  }
  const all = r.mall || own;
  if (all.missions) return own.missions === all.missions ? count(all.missions, "mission") : `${count(all.missions, "mission")} here and inside`;
  return own.rbds ? "No missions yet" : "No RBD yet";
}

// The phases cell: "3 phases: Take-off, Survey, Landing".
export function phasesText(m) {
  const n = m?.phases || 0;
  if (!n) return "No phases yet";
  const names = (m.phase_names || []).join(", ");
  return `${count(n, "phase")}${names ? `: ${names}` : ""}`;
}

// A mission row's ⋯ (Open, Delete…) and a position's (Add a mission, Open the RBD, Build…).
export function missionRowActions(r, { viewOnly = null } = {}) {
  const off = viewOnly ? { disabled: true, title: viewOnly } : {};
  return [
    { id: "mission-open", label: "Open" },
    { id: "mission-rbd", label: "Show the RBD" },
    { id: "mission-delete", label: "Delete…", ...off },
  ];
}
export function positionMissionActions(r, { viewOnly = null } = {}) {
  const off = viewOnly ? { disabled: true, reason: viewOnly, title: viewOnly } : {};
  const usable = (r?.rbds || []).filter((l) => l.rbd && !l.rbd.repairable && !l.rbd.network);
  const out = [];
  for (const l of usable) {
    out.push({ id: `mission-add:${l.rbd.id}`, label: usable.length > 1 ? `Add a mission to ${l.rbd.name}` : "Add a mission", ...off });
  }
  if ((r?.rbds || []).some((l) => l.rbd && (l.rbd.repairable || l.rbd.network)) && !usable.length) {
    out.push({ id: "mission-none", label: "Add a mission", disabled: true,
      reason: "Missions are flown on a non-repairable block diagram", title: "Missions are flown on a non-repairable block diagram" });
  }
  for (const l of (r?.rbds || []).filter((x) => x.rbd)) {
    out.push({ id: `mission-open-rbd:${l.rbd.id}`, label: (r.rbds.length > 1 ? `Open ${l.rbd.name}` : "Open the RBD") });
  }
  if (!(r?.rbds || []).some((l) => l.rbd)) out.push({ id: "mission-build-rbd", label: "Build an RBD from what's inside…", ...off });
  return out;
}

// The positions to open when the tab opens: the way down to the one picked.
export function openForMissions(display, positionKey) {
  const out = [];
  for (let k = positionKey; k != null; k = display.rows.get(k)?.parent) out.push(k);
  return out;
}

// ---- a mission's phases, as the pane edits them -------------------------------------------------

let phaseKey = 0;
// A phase as the pane holds it: the stored phase with a key of its own (for React) and its
// duration as typed.
export function editablePhase(p = {}) {
  return {
    key: ++phaseKey,
    name: p.name || "",
    duration: p.duration ?? "",
    not_needed: [...(p.not_needed || [])],
    votes: { ...(p.votes || {}) },
    values: { ...(p.values || {}) },
    block_values: Object.fromEntries(Object.entries(p.block_values || {}).map(([k, v]) => [k, { ...v }])),
  };
}
export const newPhase = (i) => editablePhase({ name: `Phase ${i + 1}` });

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
  const parts = [skipped.length ? `Doesn't need ${skipped.length === 1 ? labelOf.get(skipped[0]) : `${skipped.length} blocks`}` : "Needs every block"];
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
