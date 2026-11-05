// Percentage fields: every probability, availability, reliability and
// confidence the app asks for is typed as a percentage (95, not 0.95) and
// converted to a fraction here, before it reaches the API.
//
// A value of 1 or less in such a field is usually a fraction typed by habit
// (0.99 meaning 99%), and taking it at face value gives a wrong answer that
// looks right ("test every 1,130 days to keep availability at 0.99%"). So
// checkPercent asks instead: "Did you mean 99%?". Typing the % sign
// ("0.99%") says the small value is meant, and PercentField's "Keep" button
// does exactly that.
//
// Pure logic, tested in percent.test.js; PercentField.jsx shows it.

const trimNum = (n) => String(Number(n.toPrecision(6)));

export const RANGE_MESSAGE = "Enter a percentage between 0 and 100, e.g. 95.";

// The state of one percentage field's text:
//   { state: "ok", fraction, percent }       usable
//   { state: "empty" }                        blank and optional
//   { state: "error", message }               can't be used; message says why
//   { state: "confirm", message, suggestion } ≤ 1: probably a fraction; the
//                                             suggestion is the text to use
// Options:
//   optional       blank is allowed (otherwise blank is an error)
//   fractionCheck  ask about values ≤ 1 (default true; off for fields where a
//                  small percentage is normal, like a B-life's "% failed")
//   allowMax       100 itself is allowed (a share that can be all of them)
//   example        the example in messages (default 95)
export function checkPercent(text, { optional = false, fractionCheck = true, allowMax = false, example = 95 } = {}) {
  const raw = String(text ?? "").trim();
  const explicit = raw.endsWith("%");
  const body = (explicit ? raw.slice(0, -1) : raw).trim().replace(/,/g, "");
  const range = example === 95 ? RANGE_MESSAGE : `Enter a percentage between 0 and 100, e.g. ${example}.`;
  if (body === "") {
    return optional ? { state: "empty" } : { state: "error", message: `Enter a percentage, e.g. ${example}.` };
  }
  const v = Number(body);
  if (!Number.isFinite(v)) return { state: "error", message: `Enter a number, e.g. ${example}.` };
  if (v <= 0 || v > 100 || (v === 100 && !allowMax)) return { state: "error", message: range };
  if (fractionCheck && !explicit && v <= 1) {
    const meant = v * 100;
    if (meant < 100 || (allowMax && meant === 100)) {
      const s = trimNum(meant);
      return { state: "confirm", message: `Did you mean ${s}%?`, suggestion: s };
    }
    return { state: "confirm", message: `Is ${trimNum(v)}% right? This field is a percentage.`, suggestion: null };
  }
  return { state: "ok", fraction: Number((v / 100).toPrecision(12)), percent: v };
}

// The fraction for a field's text, or null when it isn't usable yet (blank,
// out of range, or waiting for "Did you mean…?").
export function percentFraction(text, opts) {
  const c = checkPercent(text, opts);
  return c.state === "ok" ? c.fraction : null;
}

// Whether a form can run: every check is ok (or blank-and-optional).
export const percentsReady = (...checks) => checks.every((c) => c && (c.state === "ok" || c.state === "empty"));

// The text that keeps a small value as typed: "0.99" → "0.99%".
export const keepAsTyped = (text) => {
  const s = String(text ?? "").trim();
  return s.endsWith("%") ? s : `${s}%`;
};

// A backend message about a fraction ("must be strictly between 0 and 1
// (e.g. 0.95); got 1.5"), reworded for a form that takes percentages. Other
// messages pass through unchanged.
export function percentApiMessage(message) {
  const m = String(message ?? "");
  if (/between 0 and 1\b/i.test(m) || /\(e\.g\. 0\.\d+\)/.test(m)) return RANGE_MESSAGE;
  return m;
}
