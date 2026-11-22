// The RBD Calculator's "As of now" from the tree: each block's age read from the item fitted at
// the position it stands for (POST /api/maintenance/rbd-ages-now). A block the user has already
// set keeps their value; a block with an age gets it as "Running" with where it came from; a
// block with none says why, so nothing is quietly taken as new. Pure, so `node --test` covers it.
import { formatNumber } from "./format.js";

const BASIS = {
  counter: "its counter",
  plan: "its counter and operating plan",
  duty: "its duty (no counter)",
  continuous: "running all the time since it was fitted (no counter or duty): check it",
  calendar: "the time since it was fitted",
};

// {states, sources}: the states with each untouched block filled in, and per block the words
// beside it ({text, guessed}) — where the age came from, or why there's none.
export function prefillAges(ages, blocks, states) {
  const next = { ...states };
  const sources = {};
  for (const b of blocks || []) {
    const row = ages?.blocks?.[b.id];
    const own = states?.[b.id];
    const touched = own && (own.mode !== "new" || own.value !== "") && !own.fromTree;
    if (row && row.age != null && Number.isFinite(Number(row.age))) {
      const value = String(Number(Number(row.age).toPrecision(4)));
      if (!touched) next[b.id] = { mode: "age", value, fromTree: true };
      sources[b.id] = {
        text: `${formatNumber(Number(value))} from ${row.item ? `${row.item}: ` : ""}${BASIS[row.basis] || "the tree"}`
          + (row.note ? ` (${row.note})` : ""),
        guessed: row.basis === "continuous",
      };
    } else if (row?.reason) {
      sources[b.id] = { text: `No age: ${row.reason}.`, missing: true };
    } else if (ages && (ages.unlinked || []).includes(b.id)) {
      sources[b.id] = { text: "No age: this block stands for no position on the tree. Enter its age.", missing: true };
    }
  }
  return { states: next, sources };
}

// The blocks a result ran as new although "As of now" was asked for: their labels.
export function takenAsNew(result) {
  const state = result?.current_state;
  if (!state) return [];
  return (result.nodes || [])
    .filter((n) => n.type === "component" && n.joint_age == null && !(n.id in state))
    .map((n) => n.label || n.id);
}
