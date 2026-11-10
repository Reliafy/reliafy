// A work package's work order: its lines (one per task), each answered Done,
// Done with a problem or Not done, saved at once (PUT …/lines/:task_id), and
// what closing it sends. Pure functions, tested in packageLines.test.js.

export const LINE_CHOICES = [
  { value: "done", label: "Done" },
  { value: "problem", label: "Done with a problem" },
  { value: "not_done", label: "Not done" },
];

// What a choice asks for before it's saved: a reason (not done) or a note (a problem).
export const choiceAsks = (choice) =>
  choice === "not_done" ? "Why not?" : choice === "problem" ? "What was wrong?" : null;

// The lines grouped by where they are (a position or a location), in the order they come.
export function groupLines(lines) {
  const groups = [];
  const at = new Map();
  for (const line of lines || []) {
    const s = line.subject;
    const key = s ? `${s.kind}:${s.id}` : "";
    if (!at.has(key)) {
      at.set(key, { key, subject: s || null, lines: [] });
      groups.push(at.get(key));
    }
    at.get(key).lines.push(line);
  }
  return groups;
}

// A line's saved answer as a choice ("" for not answered yet).
export const lineChoice = (line) => (["done", "problem", "not_done"].includes(line?.state) ? line.state : "");

// The words saved with a line's answer: the reason, or the problem's note.
export const lineText = (line) =>
  line?.state === "not_done" ? line.reason || "" : line?.state === "problem" ? line.finding?.notes || "" : "";

// The body that marks a line: a reason for not done; for a problem, the note as
// a finding of other work at the line's position (recorded when it closes).
export function markBody(choice, text = "") {
  const t = String(text || "").trim();
  if (choice === "done") return { state: "done" };
  if (choice === "not_done") return { state: "not_done", reason: t };
  if (choice === "problem") return { state: "problem", finding: { kind: "other", notes: t } };
  return { state: "todo" };
}

// Lines with no answer yet: their names, in order.
export const unanswered = (lines) => (lines || []).filter((l) => !lineChoice(l)).map((l) => l.name);

// What the Close button says while lines are unanswered (null once all are).
export function closeBlocker(lines) {
  const left = unanswered(lines);
  if (left.length === 0) return null;
  return left.length === 1 ? "Answer 1 more line to close" : `Answer ${left.length} more lines to close`;
}

// The close body: what was done, and on a package's work order, each line not done with its reason.
export function closePayload({ actions = [], on, notes = "", readings = [], lines = null }) {
  const body = { actions, on, notes, readings };
  if (lines) {
    body.not_done = lines.filter((l) => l.state === "not_done")
      .map((l) => ({ task_id: l.task_id, reason: l.reason || "" }));
  }
  return body;
}
