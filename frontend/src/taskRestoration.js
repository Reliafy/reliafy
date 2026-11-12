// What a replace-or-restore task leaves the item as, on the Explorer's task panel
// (backend/maintenance/restoration.py): as new, or restored partly (Kijima I: a share of the age
// gained since the last task; Kijima II: a share of its whole age), every Nth task a full
// replacement; whether its interval counts running hours; its age limit at a shutdown. The form
// says "restores X%"; the server stores q = 1 − X/100. Pure functions, tested on their own.

export const RESTORE_CHOICES = [
  ["as_new", "As new (replaced, or fully restored)"],
  ["kijima1", "Restores part of the age gained since the last task (Kijima I)"],
  ["kijima2", "Restores part of its whole age (Kijima II)"],
];

const text = (v) => (v == null ? "" : String(v));
const pct = (q) => (q == null ? "" : String(Number(((1 - Number(q)) * 100).toPrecision(6))));

// The form's fields from a task as read (its own restoration, not one a decision set for a mode).
export function restorationForm(task) {
  const own = task?.restoration?.own || null;
  const kind = own?.kind && own.kind !== "as_new" ? own.kind : "as_new";
  return {
    restoreKind: kind,
    restores: kind === "as_new" ? "" : pct(own.q),
    replaceEvery: text(own?.replace_every),
    replacementCost: text(own?.replacement_cost),
    runningHours: task?.basis_set === "operating",
    olderThan: text(task?.older_than?.value),
    olderUnit: task?.older_than?.unit || "months",
  };
}

// What's wrong with the fields, in words (null: nothing).
export function restorationProblem(f) {
  if (f.restoreKind !== "as_new") {
    const x = Number(f.restores);
    if (f.restores === "" || !Number.isFinite(x) || x < 0 || x > 100) return "Say how much of its age the task takes away: 0% to 100%.";
    if (f.replaceEvery !== "") {
      const n = Number(f.replaceEvery);
      if (!Number.isInteger(n) || n < 2 || n > 100) return "Every Nth task is a whole number from 2 to 100.";
      if (x === 100) return "A task that restores 100% renews it every time: it needs no full replacement.";
    }
    if (f.replacementCost !== "" && !(Number(f.replacementCost) >= 0)) return "The replacement cost is 0 or more.";
  }
  if (f.olderThan !== "" && !(Number(f.olderThan) > 0)) return "The age at a shutdown is more than 0.";
  return null;
}

// The restoration the fields say (null: as new).
export function restorationOf(f) {
  if (f.restoreKind === "as_new") return null;
  const out = { kind: f.restoreKind, q: Number((1 - Number(f.restores) / 100).toPrecision(6)) };
  if (f.replaceEvery !== "") out.replace_every = Number(f.replaceEvery);
  if (f.replaceEvery !== "" && f.replacementCost !== "") out.replacement_cost = Number(f.replacementCost);
  return out;
}

const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

// The PATCH body for what changed (task null: a new task, everything set but the defaults).
export function restorationBody(task, f) {
  const body = {};
  const fixed = f.outcome === undefined || f.outcome === "fixed_interval";
  const own = task?.restoration?.own ?? null;
  const want = fixed ? restorationOf(f) : null;
  const ownNorm = own && own.kind !== "as_new" ? own : null;
  const decided = task?.restoration?.source === "decision";
  if (fixed && (!same(ownNorm, want) || (decided && want !== null))) body.restoration = want;
  const calendar = ["days", "weeks", "months", "years"].includes(f.unit);
  const basis = calendar && f.runningHours ? "operating" : null;
  if (calendar && (task?.basis_set ?? null) !== basis) body.basis = basis;
  const older = f.olderThan === "" ? null : { value: Number(f.olderThan), unit: f.olderUnit };
  if (fixed && !same(task?.older_than ?? null, older)) body.older_than = older;
  return body;
}
