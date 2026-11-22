// The RBD builder's Undo and Redo: a per-session stack of the diagram as it was (blocks,
// connections and the diagram's own settings). Autosave keeps every change, so Undo is the way
// back from one; nothing here is stored or sent (a reload starts a new stack).
//
// Pure functions on a plain object, so `node --test` covers them:
//   h = emptyHistory()
//   h = recordHistory(h, state, key)   key: what the state is, as a string (rbdSaveSnapshot);
//                                      the same key again is no change
//   { history, state } = undoHistory(h) / redoHistory(h)   (null when there's nothing to do)

export const HISTORY_LIMIT = 100;

export function emptyHistory() {
  return { past: [], present: null, future: [] };
}

// A new state. The first one is where Undo stops (the diagram as opened); each one after it
// pushes the one before onto the past and clears what Redo had.
export function recordHistory(h, state, key, limit = HISTORY_LIMIT) {
  if (!h.present) return { past: [], present: { state, key }, future: [] };
  if (h.present.key === key) return h;
  const past = [...h.past, h.present];
  return { past: past.length > limit ? past.slice(past.length - limit) : past, present: { state, key }, future: [] };
}

// Back to the diagram as opened (or loaded): what's on the canvas becomes where Undo stops.
export function resetHistory(state, key) {
  return { past: [], present: { state, key }, future: [] };
}

export function undoHistory(h) {
  if (!h.past.length || !h.present) return null;
  const prev = h.past[h.past.length - 1];
  return {
    history: { past: h.past.slice(0, -1), present: prev, future: [h.present, ...h.future] },
    state: prev.state,
  };
}

export function redoHistory(h) {
  if (!h.future.length || !h.present) return null;
  const [next, ...rest] = h.future;
  return {
    history: { past: [...h.past, h.present], present: next, future: rest },
    state: next.state,
  };
}

export const canUndo = (h) => h.past.length > 0;
export const canRedo = (h) => h.future.length > 0;

// Ctrl/⌘-Z is Undo; Ctrl/⌘-Shift-Z and Ctrl-Y are Redo. Null for any other key.
export function historyKey(e) {
  if (!(e.metaKey || e.ctrlKey) || e.altKey) return null;
  const k = String(e.key || "").toLowerCase();
  if (k === "z") return e.shiftKey ? "redo" : "undo";
  if (k === "y" && e.ctrlKey && !e.metaKey && !e.shiftKey) return "redo";
  return null;
}
