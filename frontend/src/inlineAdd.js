// Adding to a list in place (the RCM details' lists: performance standards,
// functional failures, failure modes, tasks): the dashed "+ Add …" row that
// ends the list turns into a new row of the list, a box where the row's text
// goes. Enter, or leaving the row, saves it (when there's text); Esc, or
// leaving it empty, drops it quietly; a refusal keeps the text with the reason
// under it. Once saved the add row comes back, ready for the next one.
//
// The state, as a reducer (components/ui/InlineAdd.jsx drives it):
//   {open, text, busy, error, onText}  onText: the error is about the text (not another field of the row)

export const CLOSED = Object.freeze({ open: false, text: "", busy: false, error: null, onText: false });

export function inlineAddReducer(state, action) {
  switch (action.type) {
    case "start":
      return state.open ? state : { ...CLOSED, open: true };
    case "type":
      return state.busy ? state : { ...state, text: action.text, error: null, onText: false };
    case "cancel":
      return state.busy ? state : CLOSED;
    case "saving":
      return { ...state, busy: true, error: null, onText: false };
    case "saved":
      return CLOSED;
    case "failed":
      // Kept open, the text as typed, the reason under it. A check's reason
      // (a task's missing interval) is about another field, not the text.
      return { ...state, open: true, busy: false, error: action.error || "It couldn't be added.", onText: !action.check };
    default:
      return state;
  }
}

// What Enter or leaving the row does: "save" (there's text), "cancel" (none),
// "wait" (a save is under way: nothing more is sent), "stay" (not open).
// `check` (optional) says why it can't be saved yet (a task with no interval):
// then it's "invalid" with that reason, the row kept as typed.
export function commitAction(state, { check = null } = {}) {
  if (!state.open) return { act: "stay" };
  if (state.busy) return { act: "wait" };
  const text = String(state.text || "").trim();
  if (!text) return { act: "cancel" };
  const why = check ? check(text) : null;
  if (why) return { act: "invalid", error: why };
  return { act: "save", text };
}

// A save's answer: a promise's value that's a string is a refusal (the
// reason); anything else is done.
export const refusalOf = (value) => (typeof value === "string" && value ? value : null);
