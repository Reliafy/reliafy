// Before an RBD is built from a structure: positions inside that look like units of one job
// ("Pump set 1", "Pump set 2") and aren't marked as a redundancy set are asked about, never
// assumed to be in series (rbd_derive.suspected_sets). These turn the answers into the build's
// `arrangements` and say what's still to answer.

export const HOW = [
  { value: "series", label: "Every one needed", title: "In series: the system stops if any one fails" },
  { value: "parallel", label: "Fewer will do", title: "Parallel: all run, and fewer than all can do the job" },
  { value: "standby", label: "Duty and standby", title: "One runs, the others wait to take over (cold standby)" },
];

const key = (set) => (set.position_ids || []).join(",");

// The words for a set: "Pump set 1 and Pump set 2".
export function setNames(set) {
  const n = set.names || [];
  return n.length < 2 ? n.join("") : `${n.slice(0, -1).join(", ")} and ${n[n.length - 1]}`;
}

// answers: {[set key]: {how, k}} -> [{position_ids, how, k}] for the sets answered.
export function arrangementsFrom(sets, answers) {
  return (sets || []).flatMap((s) => {
    const a = answers?.[key(s)];
    if (!a?.how) return [];
    const k = a.how === "series" ? undefined : Math.max(1, Math.min(Number(a.k) || 1, s.position_ids.length - 1));
    return [{ position_ids: s.position_ids, how: a.how, ...(k ? { k } : {}) }];
  });
}

// Why the build can't go ahead yet (a set not answered), or null.
export function askProblem(sets, answers) {
  const open = (sets || []).filter((s) => !answers?.[key(s)]?.how);
  return open.length ? `Say how ${setNames(open[0])} work together.` : null;
}

export const setKey = key;
