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
