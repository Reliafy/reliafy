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
import { tabPlace } from "./explorerTabs.js";

export const MISSION_TYPE = "mission";
export const PHASE_TYPE = "phase";
// Under each phase (Derryn, 15 Nov 2026): one row per covariate a life model of the mission's RBD
// leaves open (automatic: they come and go with the RBD's models, never typed in), then one row
// per node status rule (a block's state in the phase, added by hand; a block with none is Working).
export const MCOV_TYPE = "mcov";
export const MRULE_TYPE = "mrule";
// A row of the Missions tab's own: a mission, one of its phases, or a phase's covariate or rule.
export const isMissionRow = (r) => [MISSION_TYPE, PHASE_TYPE, MCOV_TYPE, MRULE_TYPE].includes(r?.type);
export const isPhaseRow = (r) => r?.type === PHASE_TYPE;
export const isCovRow = (r) => r?.type === MCOV_TYPE;
export const isRuleRow = (r) => r?.type === MRULE_TYPE;
export const missionKey = (rbdId, missionId) => `MS:${rbdId}:${missionId}`;
export const phaseKey = (rbdId, missionId, i) => `MP:${rbdId}:${missionId}:${i}`;
export const covKey = (rbdId, missionId, i, name) => `MC:${rbdId}:${missionId}:${i}:${encodeURIComponent(name)}`;
export const ruleKey = (rbdId, missionId, i, block) => `MR:${rbdId}:${missionId}:${i}:${encodeURIComponent(block)}`;
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

// The pane asking a new mission's name first (?mission=new&on=<position id>): nothing is saved
// until it's named.
export const NEW_MISSION = "new";

// The pane's address value (?mission=<rbd id>:<mission id>&on=<position id>) and back.
export const missionParam = (rbdId, missionId) => `${rbdId}:${missionId}`;
export function parseMissionParam(value) {
  const text = String(value || "");
  const at = text.indexOf(":");
  if (at <= 0 || at === text.length - 1) return null;
  return { rbdId: text.slice(0, at), missionId: text.slice(at + 1) };
}

export const MISSION_COLUMNS = [
  { id: "phases", label: "Phases or setting", width: 230, title: "A mission's phases; a phase's place in it; under a phase, a covariate's value or a block's state in it" },
  { id: "duration", label: "Length", width: 130, num: true, title: "A phase's own length; a mission's is every phase added up. In the RBD's unit" },
  { id: "reliability", label: "Completes", width: 190, num: true, title: "The chance the mission completes, once worked out; a phase's, the chance of getting through it once started" },
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
// A chance as a percentage: past 99.99% (or under 0.01%) it reads "> 99.99%" ("< 0.01%"), not
// a string of nines no one can act on ("99.999985%").
export function pct(v) {
  const r = Number(v);
  if (v == null || v === "" || !Number.isFinite(r)) return "—";
  if (r > 0.9999 && r < 1) return "> 99.99%";
  if (r > 0 && r < 0.0001) return "< 0.01%";
  return reliabilityPercent(r);
}

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
export function graftMissions(display, links = [], hasModel = [], otherModel = []) {
  const withModel = new Set(hasModel || []);
  const withOther = new Set(otherModel || []);
  const rows = new Map();
  for (const [k, r] of display.rows) rows.set(k, { ...r, kids: [...r.kids] });
  const out = { ...display, rows, missions: true };
  for (const r of rows.values()) {
    if (r.type === "pos") Object.assign(r, { msum: { rbds: 0, missions: 0, done: 0, with: 0 }, mall: { rbds: 0, missions: 0, done: 0, with: 0 }, rbds: [], hasModel: withModel.has(r.key), otherModel: withOther.has(r.key) && !withModel.has(r.key) });
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
        names.forEach((name, i) => {
          const set = (m.phase_settings || [])[i] || { covariates: [], rules: [] };
          const covs = (m.covariates || []).map((c) => ({ ...c, ...((set.covariates || []).find((x) => x.name === c.name) || {}) }));
          const under = [];
          const phaseRef = { index: i, name, of: names.length, duration: lengths[i] ?? null };
          for (const c of covs) {
            const ck = covKey(link.rbd.id, m.id, i, c.name);
            under.push(ck);
            rows.set(ck, {
              key: ck, type: MCOV_TYPE, parent: kids[i], kids: [], depth: p.depth + 3, own: noStatus(), sum: noStatus(),
              ref: { name: c.name, cov: c, phase: phaseRef, mission: m, rbd: link.rbd, position_id: pk, search: String(c.name).toLowerCase() },
            });
          }
          for (const rule of set.rules || []) {
            const rk = ruleKey(link.rbd.id, m.id, i, rule.block);
            under.push(rk);
            rows.set(rk, {
              key: rk, type: MRULE_TYPE, parent: kids[i], kids: [], depth: p.depth + 3, own: noStatus(), sum: noStatus(),
              ref: { name: rule.label, rule, phase: phaseRef, mission: m, rbd: link.rbd, position_id: pk, search: String(rule.label).toLowerCase() },
            });
          }
          rows.set(kids[i], {
            key: kids[i], type: PHASE_TYPE, parent: key, kids: under, depth: p.depth + 2, own: noStatus(), sum: noStatus(),
            ref: {
              name, phase: phaseRef, settings: { covariates: covs, rules: set.rules || [], votes: set.votes || {} },
              result: phaseResult(m.result, i), mission: m, rbd: link.rbd, position_id: pk,
              search: String(name || "").toLowerCase(),
            },
          });
        });
        keys.push(key);
        p.msum.missions += 1;
        // Worked out: its chance of completing is in (not one still waiting on a value).
        if (m.result?.reliability != null) p.msum.done += 1;
      }
    }
    p.kids = [...keys, ...p.kids];
  }
  const done = new Set();
  const total = (k) => {
    const r = rows.get(k);
    if (done.has(k)) return r.mall;
    done.add(k);
    const t = { ...r.msum, with: r.msum.missions ? 1 : 0 };
    for (const c of r.kids) {
      if (rows.get(c)?.type === "pos") {
        const s = total(c);
        t.rbds += s.rbds;
        t.missions += s.missions;
        t.done += s.done;
        t.with += s.with;
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

// Why a position can't have a mission, in words (a roll-up's short form, or the menu's sentence).
// `otherModel`: its model in use can't be a block (a condition-and-life model, say: GET
// /position-missions: other_model).
export function noMissionWhy(r, short = false) {
  const linked = (r?.rbds || []).some((l) => l.rbd && !l.rbd.mission_rbd);
  if (r?.otherModel) {
    return short ? "its model can't be a block"
      : `Its model in use can't be a block in a mission's RBD (only a life distribution or a covariate model can): give it one in ${tabPlace("models")}, or add positions inside it`;
  }
  if (linked) {
    return short ? "its RBD can't take missions"
      : "Missions are flown on a non-repairable block diagram: give it a life model, or add positions inside it";
  }
  return short ? "needs a life model or positions inside"
    : `Give it a life model in ${tabPlace("models")}, or add positions inside it: a mission's RBD is built from them`;
}

// A position row's roll-up: its own ("2 missions", or "No missions yet · Add a mission" wherever
// one can be added); closed, everything inside it too ("5 missions here and inside").
export function rollupText(r, open = false) {
  if (!r?.msum) return "";
  const own = r.msum;
  const none = canAddMission(r) ? "No missions yet · Add a mission" : `No missions yet · ${noMissionWhy(r, true)}`;
  if (open) return own.missions ? count(own.missions, "mission") : none;
  const all = r.mall || own;
  if (all.missions) return own.missions === all.missions ? count(all.missions, "mission") : `${count(all.missions, "mission")} here and inside`;
  return none;
}

// The roll-up over the tab for the position picked (the Explorer aggregates downwards): its own
// missions, kept as they are, then everything below it at any depth, and how many have their
// chance worked out. "2 missions here · 5 on 3 positions below · 4 of 7 worked out"; with none of
// its own where one can be added, it ends "· Add a mission" (MissionRollup's button).
export function headRollupText(r) {
  if (!r?.msum) return "";
  const own = r.msum;
  const all = r.mall || own;
  const below = all.missions - own.missions;
  if (!all.missions) return rollupText(r, true);
  const parts = [own.missions ? `${count(own.missions, "mission")} here` : "No missions here"];
  if (below) {
    const on = all.with - (own.missions ? 1 : 0);
    parts.push(`${below.toLocaleString("en-AU")} on ${count(on, "position")} below`);
  }
  parts.push(`${all.done.toLocaleString("en-AU")} of ${all.missions.toLocaleString("en-AU")} worked out`);
  if (!own.missions && canAddMission(r)) parts.push("Add a mission");
  return parts.join(" · ");
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
  // A covariate row: set in its details (it comes from the RBD's models, so it can't be deleted).
  if (isCovRow(r)) {
    const none = r.ref.cov.value == null;
    return [
      { id: "mission-cov-set", label: none ? "Set the value…" : "Change the value…", ...off },
      { id: "mission-cov-clear", label: "Clear the value", ...(viewOnly ? off : none ? { disabled: true, reason: "It has no value of its own in this phase.", title: "It has no value of its own in this phase." } : {}) },
    ];
  }
  if (isRuleRow(r)) {
    return [
      { id: "mission-rule-edit", label: "Edit…", ...off },
      { id: "mission-rule-delete", label: "Delete…", danger: true, ...off },
    ];
  }
  if (isPhaseRow(r)) {
    const { index, of } = r.ref.phase;
    const first = "It's the first phase already.";
    const last = "It's the last phase already.";
    return [
      { id: "mission-rule-add", label: "Add node status rule…", ...(viewOnly ? off : (r.ref.mission.blocks || []).length ? {}
        : { disabled: true, reason: "The mission's RBD has no blocks yet.", title: "The mission's RBD has no blocks yet." }) },
      { separator: true },
      { id: "mission-phase-open", label: "Open in the mission editor…" },
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
    { id: "mission-open", label: "Open in the mission editor" },
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
    const why = noMissionWhy(r);
    out.push({ id: "mission-none", label: "Add a mission", disabled: true, reason: why, title: why });
  }
  for (const l of linked) {
    out.push({ id: `mission-open-rbd:${l.rbd.id}`, label: (linked.length > 1 ? `Open ${l.rbd.name}` : "Open the RBD") });
  }
  if (!linked.length) out.push({ id: "mission-build-rbd", label: "Build an RBD from what's inside…", ...off });
  // Which positions inside back each other up: a mission built from the tree wires them so.
  if (hasInside(r)) out.push({ id: "mission-redundancy", label: "Redundancy inside…", ...off });
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
    guaranteed: [...(p.guaranteed || [])],
    dormancy: { ...(p.dormancy || {}) },
    start_probability: { ...(p.start_probability || {}) },
    models: Object.fromEntries(Object.entries(p.models || {}).map(([k, v]) => [k, { ...v }])),
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

// A phase's covariate value that follows a schedule over the phase (#372): {expression} in the
// phase's own time t, or {table: [{t, value}], period?}.
export function isSchedule(v) {
  return !!v && typeof v === "object" && !Array.isArray(v) && ("expression" in v || "table" in v);
}
// A schedule in words, short: "follows 100 if t % 24 < 16 else 40" / "follows a table of 3 steps".
export function scheduleWords(v) {
  if (!isSchedule(v)) return "";
  if (v.expression != null) return `follows ${v.expression}`;
  const n = (v.table || []).length;
  return `follows a table of ${n} step${n === 1 ? "" : "s"}${v.period ? `, repeating every ${fmt(Number(v.period))}` : ""}`;
}

// A value typed as a number when it is one; text (a choice) otherwise; a schedule as it is; null
// for blank.
export function typed(v) {
  if (v == null) return null;
  if (isSchedule(v)) return v;
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
    const gu = (r.guaranteed || []).filter((id) => ids.has(id) && !nn.includes(id) && !sb.includes(id));
    if (gu.length) out.guaranteed = [...new Set(gu)];
    const dorm = {};
    for (const [id, f] of Object.entries(r.dormancy || {})) {
      const x = Number(f);
      if (sb.includes(id) && Number.isFinite(x) && x > 0) dorm[id] = Math.min(x, 1);
    }
    if (Object.keys(dorm).length) out.dormancy = dorm;
    // The chance a standby block starts when called on (0–1; kept below 1, standby blocks only).
    const starts = {};
    for (const [id, p] of Object.entries(r.start_probability || {})) {
      const x = Number(p);
      if (sb.includes(id) && Number.isFinite(x) && x >= 0 && x < 1) starts[id] = x;
    }
    if (Object.keys(starts).length) out.start_probability = starts;
    // A block's own life model in the phase (set through the API or the connector) rides along.
    const models = Object.fromEntries(Object.entries(r.models || {}).filter(([id, m]) => ids.has(id) && m));
    if (Object.keys(models).length) out.models = models;
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
  { id: "standby", label: "Standby", title: "Idle until the phase needs it (a block it backs up fails), then running: idle it doesn't age (cold) or ages at its dormancy (warm), and it may fail to start" },
  { id: "guaranteed", label: "Guaranteed working", title: "Running and ageing, but it can't fail in this phase (one that failed earlier stays failed)" },
  { id: "off", label: "Not needed", title: "The phase works without it; its clock keeps running, so a failure now is found by a later phase that needs it" },
];
// Short words for a cell or a row.
export const STATE_SHORT = { working: "Working", standby: "Standby", guaranteed: "Guaranteed", off: "Not needed" };
// A rule's state as the server names it (phase_rules: not_needed) and as the grid does (off).
export const ruleState = (s) => (s === "not_needed" ? "off" : s);
export function blockState(phase, id) {
  if ((phase?.standby || []).includes(id)) return "standby";
  if ((phase?.guaranteed || []).includes(id)) return "guaranteed";
  if ((phase?.not_needed || []).includes(id)) return "off";
  return "working";
}
// The phase's lists with block `id` set to `state`: {standby, guaranteed, not_needed, dormancy,
// start_probability} (a patch for the phase). `dormancy` (0–1) and `start` (the chance it starts,
// 0–1) go with standby only; another state drops them. Left null, a standby block keeps its own.
export function withBlockState(phase, id, state, dormancy = null, start = null) {
  const standby = (phase?.standby || []).filter((x) => x !== id);
  const guaranteed = (phase?.guaranteed || []).filter((x) => x !== id);
  const notNeeded = (phase?.not_needed || []).filter((x) => x !== id);
  const dorm = { ...(phase?.dormancy || {}) };
  const starts = { ...(phase?.start_probability || {}) };
  delete dorm[id];
  delete starts[id];
  if (state === "standby") {
    standby.push(id);
    const f = Number(dormancy ?? phase?.dormancy?.[id] ?? 0);
    if (Number.isFinite(f) && f > 0) dorm[id] = Math.min(f, 1);
    const p = Number(start ?? phase?.start_probability?.[id] ?? 1);
    if (Number.isFinite(p) && p >= 0 && p < 1) starts[id] = p;
  } else if (state === "guaranteed") guaranteed.push(id);
  else if (state === "off") notNeeded.push(id);
  return { standby, guaranteed, not_needed: notNeeded, dormancy: dorm, start_probability: starts };
}
// "Standby (warm, ages at 20%; starts 95%)", "Standby (cold)", "Guaranteed working", "Not needed".
export function ruleText(rule) {
  const s = ruleState(rule?.state);
  if (s === "standby") {
    const warm = Number(rule.dormancy) > 0 ? `warm, ages at ${fmt(Number(rule.dormancy) * 100)}%` : "cold";
    const p = Number(rule.start_probability ?? 1);
    return `Standby (${warm}${Number.isFinite(p) && p < 1 ? `; starts ${fmt(p * 100)}%` : ""})`;
  }
  return BLOCK_STATES.find((x) => x.id === s)?.label || "Working";
}
// The blocks shown faded in a phase's drawing: those it doesn't need and those standing by.
export const fadedIn = (phase) => new Set([...(phase?.not_needed || []), ...(phase?.standby || [])]);

// ---- the tree's phase details: its covariates, rules and result ----------------------------------

// A phase's own result from the mission's kept result (summary.result.phases): {completes (the
// chance of getting through it once started), atEnd (the mission still going at its end),
// waiting}; null before the mission is worked out.
export function phaseResult(result, i) {
  const row = result?.phases?.[i];
  if (!row) return null;
  if (row.waiting) return { waiting: true, completes: null, atEnd: null };
  return { waiting: false, completes: row.conditional_failure == null ? null : 1 - row.conditional_failure, atEnd: row.reliability_at_end ?? null };
}

// A covariate value with its unit: "35 °C", "12%", "Desert" (a choice).
export function covValueText(v, unit) {
  if (v == null || v === "") return "—";
  if (isSchedule(v)) return scheduleWords(v);
  const u = String(unit || "").trim();
  const num = typeof v === "number" ? fmt(v) : String(v);
  if (!u) return num;
  return u === "%" ? `${num}%` : `${num} ${u}`;
}
// What a covariate row says about its value in the phase: {text, flag ("needs" when a block has
// no value at all, "unset" when the phase has none of its own and a fallback stands in, else
// null), title}.
export function covStatus(cov) {
  if (cov?.value != null) return { text: covValueText(cov.value, cov.unit), flag: null, title: "Set for this phase" };
  if ((cov?.missing || []).length) {
    return { text: "Needs a value", flag: "needs", title: `No value: ${cov.missing.join(", ")} can't be worked out in this phase until it has one` };
  }
  const from = { default: "the model's default", diagram: "the RBD's value", own: "the block's own value", override: "a block's own value in this phase", mixed: "each block's own" }[cov?.source] || "a fallback";
  return {
    text: cov?.used != null ? `Not set · uses ${covValueText(cov.used, cov.unit)}` : "Not set",
    flag: "unset",
    title: `Not set for this phase: ${from} stands in`,
  };
}
// A phase's line in its details: "2 covariates set, 1 needs a value · 1 rule".
export function phaseSettingsText(settings) {
  const covs = settings?.covariates || [];
  const set = covs.filter((c) => c.value != null).length;
  const needs = covs.filter((c) => c.value == null && (c.missing || []).length).length;
  const parts = [];
  if (covs.length) parts.push(`${set} of ${count(covs.length, "covariate")} set${needs ? `, ${needs} need${needs === 1 ? "s" : ""} a value` : ""}`);
  const rules = (settings?.rules || []).length;
  parts.push(rules ? count(rules, "node status rule") : "Every block working");
  return parts.join(" · ");
}
// The phase with one covariate's value set (blank clears it): its stored values changed.
export const withCovValue = (phase, name, value) => withValue(phase, name, value);

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

// A covariate row's blocks: "Feeds Pump A and Pump B".
export function feedsList(cov) {
  const names = cov?.feeds || [];
  if (!names.length) return "";
  return `Feeds ${names.length === 1 ? names[0] : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`}`;
}

// The blocks still without a value in a phase: [labels], each once.
export const phaseNeeds = (rows) => [...new Set(rows.flatMap((r) => r.missing || []))];

// A phase's line under its name: "Doesn't need Camera · Motors: 4 of 6 · 2 values set".
export function phaseLine(phase, { blocks = [], votes = [] } = {}) {
  const labelOf = new Map(blocks.map((b) => [b.id, b.label]));
  const skipped = (phase.not_needed || []).filter((id) => labelOf.has(id));
  const standing = (phase.standby || []).filter((id) => labelOf.has(id));
  const parts = [skipped.length ? `Doesn't need ${skipped.length === 1 ? labelOf.get(skipped[0]) : `${skipped.length} blocks`}`
    : standing.length ? "Every block working or standing by" : "Every block in use, wired as in the RBD"];
  if (standing.length) parts.push(`${standing.length === 1 ? labelOf.get(standing[0]) : `${standing.length} blocks`} on standby`);
  const held = (phase.guaranteed || []).filter((id) => labelOf.has(id));
  if (held.length) parts.push(`${held.length === 1 ? labelOf.get(held[0]) : `${held.length} blocks`} guaranteed working`);
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

// ---- blocks with no model (a placeholder stands in) --------------------------------------------

const listed = (names) => (names.length <= 1 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`);

// What a result that rests on placeholders has to say, or null when every block it needs has a
// model: {n, of, names, count ("3 of 5 blocks have no model"), list ("Battery, … and Fuel
// system"), without (the chance with those blocks left out; null when there is none to give)}.
// `result`: a calculation (placeholders: [{id, label}], blocks) or a list row's kept result
// (placeholders: [labels], without_placeholders: the number).
//
// Placeholders are counted through every sub-system (`placeholder_blocks`: {basic, placeholders,
// mostly}): a sub-system whose blocks are all placeholders is one of `names`; one with only some
// is in `partly`. `basic`/`guessed`: the basic blocks and how many are placeholders ("27 of 27
// basic blocks are placeholders"); `mostly`: half or more, so the warning is made prominent.
export function placeholderWarning(result) {
  const label = (p) => (typeof p === "string" ? p : p.label);
  const names = (result?.placeholders || []).map(label);
  const partly = (result?.partly_placeholders || []).map(label);
  if (!names.length && !partly.length) return null;
  const n = names.length;
  const of = Number(result.blocks) || null;
  const w = result.without_placeholders;
  const without = w == null ? null : typeof w === "number" ? w : w.reliability ?? null;
  const held = result.placeholder_blocks || null;
  const basic = Number(held?.basic) || null;
  const guessed = Number(held?.placeholders) || null;
  const nested = !!held?.nested && basic != null && guessed != null;
  const mostly = held ? !!held.mostly || (basic ? guessed * 2 >= basic : false) : (of ? n * 2 >= of : false);
  let count;
  if (nested) {
    count = `${guessed.toLocaleString("en-AU")} of ${basic.toLocaleString("en-AU")} basic blocks ${guessed === 1 ? "is a placeholder" : "are placeholders"}`;
  } else if (!n) {
    count = `${listed(partly)} ${partly.length === 1 ? "rests" : "rest"} partly on placeholders`;
  } else {
    count = of && of > n ? `${n} of ${of} blocks have no model` : of === n && n > 1 ? `none of the ${n} blocks has a model`
      : n === 1 ? (of === 1 ? "the block has no model" : "1 block has no model") : `${n} blocks have no model`;
  }
  return {
    n, of, names, partly, basic, guessed, nested, mostly, count, list: listed(names.length ? names : partly),
    // Leaving every block out would leave nothing to work out.
    canLeaveOut: n > 0 && !(of != null && n >= of),
    without: result.reliability == null ? null : without,
  };
}
// The chip's tone for a figure worked out on placeholders: danger when most of it rests on them.
export function placeholderTone(result) {
  const ph = placeholderWarning(result);
  return ph ? (ph.mostly ? "danger" : "warning") : null;
}
// The Completes cell's hover for a mission worked out on placeholders.
export function placeholderTitle(result) {
  const ph = placeholderWarning(result);
  if (!ph) return "";
  if (!ph.n) return `Not a real figure: ${ph.count}.`;
  const nested = ph.nested;
  return `Not a real figure: ${nested ? `${ph.count}. ` : ""}${ph.list} ${ph.n === 1 ? "has" : "have"} no model, so a placeholder stands in.`
    + (ph.without != null ? ` Without ${ph.n === 1 ? "it" : "them"}: ${pct(ph.without)}.` : "");
}
// Every phase with the placeholder blocks Not needed (left out of the mission): the rows to keep.
export function leaveOut(rows, ids) {
  return rows.map((r) => ids.reduce((p, id) => ({ ...p, ...withBlockState(p, id, "off") }), r));
}

// The answer in words, first: "The mission completes with probability 98.2%. Survey is the
// riskiest phase." Or, waiting on values: "Worked out to the end of Take-off (99.9%); Cruise needs
// values first."
export function answerText(result) {
  if (!result) return "";
  if (result.reliability != null) {
    const risky = result.riskiest && (result.phases || []).length > 1 ? ` ${result.riskiest.name} is the riskiest phase.` : "";
    const ph = placeholderWarning(result);
    if (ph && ph.mostly) return `Not a real figure: ${ph.count}, so most of this answer rests on invented lives. With placeholders standing in, the mission completes with probability ${pct(result.reliability)}.`;
    if (ph) return `Not a real figure yet: ${ph.count}. With a placeholder standing in for ${ph.n === 1 ? "it" : "each"}, the mission completes with probability ${pct(result.reliability)}.`;
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
