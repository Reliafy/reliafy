// Reliafy Maintenance: names and titles are short labels (at most 200
// characters, as the server checks them); longer detail has a field of its own.

export const SHORT_TEXT = 200;

// Characters as the server counts them: trimmed, by code point (an emoji is one).
export function textLength(value) {
  return Array.from(String(value ?? "").trim()).length;
}

export function tooLong(value, max = SHORT_TEXT) {
  return textLength(value) > max;
}

// The note under an input nearing or past its limit, or null while it's well
// within it: {text, over}. `hint` says where longer detail goes.
export function lengthNote(value, max = SHORT_TEXT, hint = "") {
  const n = textLength(value);
  if (n <= max * 0.8) return null;
  if (n <= max) return { text: `${n} / ${max} characters`, over: false };
  return { text: `${n} / ${max} characters: shorten it${hint ? ` and ${hint}` : ""}.`, over: true };
}

// Where the detail goes instead, for the length note.
export const TASK_HINT = "put the detail in the instructions";
export const DESCRIPTION_HINT = "put the detail in the description";

// A live character counter for a box with a soft limit (a function's text):
// {n, max, text, tone, over, blocked, message}. `tone`: "" well within it,
// "near" (amber) in its last tenth, "over" (red) past it. A text saved before
// the limit (`before`) that's longer stays as it is and can still be edited,
// but a change to it can't be saved until it's within the limit (`blocked`);
// a new text (no `before`) can't be saved past it either.
export function charCount(value, { max = SHORT_TEXT, before = null } = {}) {
  const n = textLength(value);
  const over = n > max;
  const near = !over && n >= Math.ceil(max * 0.9);
  const changed = before == null || String(value ?? "").trim() !== String(before ?? "").trim();
  const fmt = (x) => x.toLocaleString("en-AU");
  return {
    n,
    max,
    text: `${fmt(n)} / ${fmt(max)}`,
    tone: over ? "over" : near ? "near" : "",
    over,
    blocked: over && changed,
    message: over ? `Shorten it to ${fmt(max)} characters or fewer${changed ? " to save the change" : ""} (it's ${fmt(n)}).` : "",
  };
}
