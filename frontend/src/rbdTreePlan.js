// A repairable RBD's maintenance plan read from the tree (Derryn, 12 Nov 2026: "The RBD maintenance
// plan needs to come from the Explorer maintenance tasks. It can't be the other way around.").
// A block standing for a position takes its planned work from that position's tasks on the
// Explorer's Maintenance tab, read each time (backend/maintenance/rbd_tree_plan.py); nothing is
// copied into the diagram. The RBD keeps only its own settings for such a block, in
// data.tree_settings (an on-condition block's replacement threshold, cost and time off-line, an age
// replacement's early-renewal age, a proof test's first test, coverage and full test), plus its
// duty, crew priority and (for a task in no package) its maintenance group.
import { explorerPath } from "./assetTree.js";
import { taskSummary } from "./rbdMaintenancePlan.js";

// What the diagram may set for a tree-linked block, by what its task does (as the backend's SETTINGS).
export const TREE_SETTINGS = {
  age: ["opportunity"],
  block: [],
  condition: ["threshold", "cost", "duration"],
  test: ["offset", "coverage", "full_test"],
};

const blank = (v) => v == null || v === "";
const pick = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => !blank(v)));

// A tree-linked block's data for calculation: its own plan replaced by its position's task (none:
// it runs to failure), with the diagram's own settings for it. The same rule as rbd_tree_plan.merge.
// tree_settings stay on the result: the server merges the data it's sent once more, so dropping
// them here lost every on-condition, proof-test and early-renewal setting.
export function mergeTreeData(data = {}, row) {
  const { preventive: _p, inspection: _i, ...out } = data;
  const settings = data.tree_settings || {};
  out.tree_plan = { position_id: row.position.id, task_id: row.used ?? null };
  const plan = row.plan;
  if (!plan) return out;
  const own = pick(Object.fromEntries((TREE_SETTINGS[plan.task] || []).map((k) => [k, settings?.[k]])));
  if (plan.task === "test") {
    out.inspection = pick({ interval: plan.interval, duration: plan.duration, cost: plan.cost, ...own });
    delete out.maintenance_group;
    return out;
  }
  const pm = { policy: plan.task, interval: plan.interval, operating_interval: plan.operating_interval };
  if (plan.task === "condition") Object.assign(pm, { inspection_cost: plan.inspection_cost }, own);
  else Object.assign(pm, { duration: plan.duration, cost: plan.cost }, own);
  out.preventive = pick(pm);
  if (plan.group) out.maintenance_group = plan.group;
  return out;
}

// The diagram's nodes with every tree-linked block's plan read from its position; the rest as drawn.
export function applyTreePlan(nodes = [], plans) {
  const rows = plans?.blocks || {};
  if (!Object.keys(rows).length) return nodes;
  return nodes.map((n) => (rows[n.id] ? { ...n, data: mergeTreeData(n.data || {}, rows[n.id]) } : n));
}

// The block's tree row (or null): only for a repairable diagram linked to a position.
export const treeRow = (plans, id) => plans?.blocks?.[id] || null;

// Set one of the diagram's own settings for a tree-linked block (null clears it).
export function setTreeSetting(data = {}, key, value) {
  const next = { ...(data.tree_settings || {}), [key]: value };
  if (blank(value)) delete next[key];
  const out = { ...data, tree_settings: next };
  if (!Object.keys(next).length) delete out.tree_settings;
  return out;
}

// What's still to set on the RBD side for a tree-linked block, in plain words.
export function treeRowProblems(data = {}, row) {
  const plan = row?.plan;
  if (!plan) return [];
  const s = data.tree_settings || {};
  const out = [];
  if (plan.task === "condition") {
    const th = Number(s.threshold);
    if (blank(s.threshold) || !Number.isFinite(th) || th < 0 || th > 1) {
      out.push("Set the replacement threshold: a probability from 0 to 1 (e.g. 0.05).");
    }
  }
  if (plan.operating_interval != null && plan.interval == null && !(Number(data.duty) > 0 && Number(data.duty) <= 1)) {
    out.push("The task counts running hours: set how much of the time the block runs (Runs %) to turn them into calendar time.");
  }
  if (plan.task === "age" && !blank(s.opportunity) && !plan.group && blank(data.maintenance_group)) {
    out.push("Early renewal at a group stop needs a maintenance group.");
  }
  return out;
}

// Where a position's tasks are edited: its Maintenance tab in the Explorer (a task opened there,
// or Add task).
export function treeTaskPath(positionId, { taskId = null, add = false } = {}) {
  return explorerPath("positions", {
    sel: positionId, tab: "maintenance", ...(taskId ? { mtask: taskId } : {}), ...(add ? { addtask: positionId } : {}),
  });
}
export const treePositionPath = (positionId, tab = "maintenance") => explorerPath("positions", { sel: positionId, tab });

// A request's blocks: the ids and labels the backend maps to positions (and whether each has a
// repair time). A key for refetching when they change.
export function treeGraph(nodes = [], unit = "") {
  return {
    unit,
    nodes: nodes.filter((n) => n.type === "component").map((n) => ({
      id: n.id, type: n.type,
      data: { label: n.data?.label || "", ...(n.data?.repeat_of ? { repeat_of: n.data.repeat_of } : {}),
        ...(n.data?.repair ? { repair: true } : {}), ...(n.data?.instant_repair ? { instant_repair: true } : {}) },
    })),
  };
}
export const treeKey = (nodes = [], unit = "") => JSON.stringify(treeGraph(nodes, unit));

// A tree-linked block's planned work in words, for the block dialog: the same plan the Maintenance
// plan and the Calculator use (mergeTreeData), where it comes from, and where it's edited. Without
// it the dialog read the diagram's own (unused) plan and said "Run to failure" for a block whose
// position has a task.
export function treeBlockPlan(data = {}, row, unit = "") {
  const used = (row?.tasks || []).find((t) => t.used) || null;
  const pos = row.position;
  return {
    summary: taskSummary(mergeTreeData(data, row), unit),
    source: used ? `From the tree: “${used.name}” on ${pos.name}` : `From the tree: no maintenance tasks on ${pos.name}`,
    editPath: treeTaskPath(pos.id, used ? { taskId: used.id } : { add: true }),
    editLabel: used ? "Edit in the tree" : "Add a task in the tree",
  };
}
