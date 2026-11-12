// What a task costs each time it's done, as the RCM shows it (Nov 2026). The figure is kept with
// the task on its position (the Explorer's Maintenance tab: typed, or from its LSA at trade
// rates); the RCM reads it and says where it came from, and never asks for it again. Tested in
// taskCosts.test.js.

const plainMoney = (v) => `$${v}`;

// One task's line on a failure mode's step 3: "Check the seal: $40 each time (typed on the task)."
// or "Replace the seal: no cost yet." `t`: a task as the RCM read lists it ({name, cost}).
export function taskCostLine(t, money = plainMoney) {
  const c = t?.cost;
  const name = t?.name || "This task";
  if (!c || c.amount == null) return `${name}: no cost yet.`;
  const where = c.source === "typed" ? "typed on the task" : c.complete ? "from its LSA" : "from its LSA, partly priced";
  return `${name}: ${money(c.amount)} each time (${where}).`;
}

// A saved calculation behind the decision used another cost than the task has now: the decision
// keeps its saved figures until it's calculated again, and says so.
export function costChangedText(c, money = plainMoney) {
  return `“${c.task}” now costs ${money(c.now)} each time; the saved calculation used ${money(c.used)}. `
    + "The decision keeps its figures until you calculate again.";
}
