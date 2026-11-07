// Notes and rationale on an RCM row: every function, performance standard,
// functional failure and failure mode has its title and its notes, the long
// description where the reason for it is written (why the standard is set
// where it is, what a failure mode rests on). Plain text with its line
// breaks, at most 4,000 characters, as the server checks it. Pure functions,
// so node --test covers them: the details panel's section (RcmNotes.jsx) and
// the small note mark on a table row use them.

import { charCount } from "./maintenanceText.js";

export const NOTES_LIMIT = 4000;

// The rows that carry notes. A function's one old standard text (a "legacy"
// row) isn't a standard of its own yet, so it has none.
const KIND = { fn: "function", std: "performance standard", fail: "functional failure", mode: "failure mode" };
export const hasNotesField = (r) => !!r && !!KIND[r.type] && !(r.type === "std" && r.ref?.legacy);

// The empty section's words.
export function notesPrompt(r) {
  const what = r?.type === "fail" ? "failure" : r?.type === "std" ? "standard" : KIND[r?.type] || "row";
  return `Why this ${what} is here, what it rests on.`;
}

// The row's notes as saved ("" for none).
export const notesOf = (r) => (hasNotesField(r) ? String(r.ref?.notes ?? "").trim() : "");
export const hasNotes = (r) => notesOf(r) !== "";

// The mark's tooltip: the notes' first line with words in it, cut short.
export function notesTip(r, max = 120) {
  const line = notesOf(r).split(/\r?\n/).map((x) => x.trim()).find(Boolean) || "";
  return line.length > max ? `${line.slice(0, max - 1).trimEnd()}…` : line;
}

// What would be saved from the text typed: { value } or { error }. Line
// endings become \n; the ends are trimmed ("" clears the notes).
export function checkNotes(raw) {
  const value = String(raw ?? "").replace(/\r\n?/g, "\n").trim();
  const c = charCount(value, { max: NOTES_LIMIT });
  if (c.over) return { error: `Notes are at most ${NOTES_LIMIT.toLocaleString("en-AU")} characters; these are ${c.n.toLocaleString("en-AU")}. Shorten them.` };
  return { value };
}

export const notesChanged = (saved, draft) => String(saved ?? "").trim() !== checkNotes(draft).value;

// The count under the box: "120 / 4,000", with its tone near and over the limit.
export const notesCount = (draft) => charCount(draft, { max: NOTES_LIMIT });
