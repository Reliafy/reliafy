// New dataset's "Type it in": the live reading of text typed in SurPyval's
// notation ("120, 310, [400, 450], 1000+"). The server reads it with SurPyval
// (POST /api/datasets/notation/read) and says what it understood, or where it
// stopped and what to write; this keeps the latest answer only, a short pause
// after typing, so a slow answer to old text never replaces a newer one.

// The hint under the box and the examples in "What can I type?".
export const NOTATION_HINT = "Lives separated by commas: 120 failed at 120, 1000+ still running at 1000.";
export const NOTATION_PLACEHOLDER = "120, 310, [400, 450], 1000+";
export const NOTATION_RULES = [
  { write: "120", means: "failed at 120" },
  { write: "1000+", means: "still running at 1000 (hasn't failed yet)" },
  { write: "[400, 450]", means: "failed some time between 400 and 450, found at an inspection" },
  { write: "<50  or  50-", means: "failed some time before 50, found failed at the first look" },
  { write: "3*200", means: "three units that failed at 200" },
  { write: "300 | (50, inf]", means: "observed only after 50 (it entered service before records began)" },
  { write: "P1: 120, 310, 1000+", means: "one unit's repeated failures, one unit per line (repairable data)" },
];

// What to show for a reading: { state: "empty" | "reading" | "ok" | "error", summary, error, where, rows,
// columns, nRows }.
export function readingView(text, answer) {
  if (!String(text || "").trim()) return { state: "empty" };
  if (!answer || answer.text !== text) return { state: "reading" };
  if (answer.error) {
    return { state: "error", error: answer.error, where: answer.where || null };
  }
  const r = answer.result;
  return { state: "ok", summary: r.summary, columns: r.columns, rows: r.rows, nRows: r.n_rows, kind: r.kind,
           lifetimes: r.lifetimes || null };
}

// A reader: read(text) after ``delay`` ms of no typing, then onAnswer({ text, result } | { text, error,
// where }). Only the newest text's answer is passed on. ``readFn(text, { signal })`` answers the result or
// throws (err.data.where from a 422).
export function createNotationReader(readFn, onAnswer, { delay = 300, setTimer = setTimeout, clearTimer = clearTimeout } = {}) {
  let timer = null;
  let latest = null;
  let controller = null;
  const run = async (text) => {
    if (controller) controller.abort();
    controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    try {
      const result = await readFn(text, { signal: controller?.signal });
      if (text !== latest) return;
      // Text that can't be read (yet) is an answer, not a failure: where it stopped and what to write.
      onAnswer(result?.error ? { text, error: result.error, where: result.where || null } : { text, result });
    } catch (err) {
      if (err?.name === "AbortError" || text !== latest) return;
      onAnswer({ text, error: err?.message || "The text couldn't be read.", where: err?.data?.where || null });
    }
  };
  return {
    read(text) {
      latest = text;
      if (timer) clearTimer(timer);
      timer = null;
      if (!String(text || "").trim()) return;
      timer = setTimer(() => { timer = null; run(text); }, delay);
    },
    stop() {
      if (timer) clearTimer(timer);
      if (controller) controller.abort();
      latest = null;
    },
  };
}
