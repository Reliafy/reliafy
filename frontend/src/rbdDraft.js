// An unsaved diagram opened from a starter or an import keeps its edits in
// this browser tab until it's saved, so a reload doesn't put the starter's own
// figures back. Keyed by the history entry (React Router's location.key, which
// a reload keeps), in sessionStorage: per tab, gone when the tab closes, never
// sent anywhere. Every access is guarded: storage can be missing or refuse.

const PREFIX = "rbd-draft:";

const store = (storage) => {
  try {
    return storage === undefined ? window.sessionStorage : storage;
  } catch {
    return null;
  }
};

export function draftKey(locationKey) {
  return locationKey && locationKey !== "default" ? PREFIX + locationKey : null;
}

export function readDraft(key, storage) {
  if (!key) return null;
  try {
    const raw = store(storage)?.getItem(key);
    const draft = raw ? JSON.parse(raw) : null;
    return draft && Array.isArray(draft.graph?.nodes) ? draft : null;
  } catch {
    return null;
  }
}

export function writeDraft(key, graph, storage) {
  if (!key || !graph) return;
  try {
    store(storage)?.setItem(key, JSON.stringify({ graph }));
  } catch {
    // Full or blocked: the diagram still works, it just isn't kept over a reload.
  }
}

export function clearDraft(key, storage) {
  if (!key) return;
  try {
    store(storage)?.removeItem(key);
  } catch {
    // nothing kept
  }
}
