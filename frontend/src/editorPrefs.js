// The signed-in user's editor preferences ({ autosave }), read once per page load and shared by
// every editor on screen, so Settings and the builder's ⋯ menu agree at once. Autosave is on
// until the server says otherwise (or while it can't be asked).
import { useEffect, useState } from "react";
import { getEditorPreferences, setEditorPreferences } from "./api.js";

export const DEFAULT_EDITOR_PREFS = { autosave: true };

let prefs = DEFAULT_EDITOR_PREFS;
let loading = null;
const listeners = new Set();
const tell = () => listeners.forEach((fn) => fn(prefs));

export function loadEditorPrefs() {
  if (!loading) {
    loading = getEditorPreferences()
      .then((p) => {
        prefs = { ...DEFAULT_EDITOR_PREFS, autosave: p?.autosave !== false };
        tell();
        return prefs;
      })
      .catch(() => prefs);
  }
  return loading;
}

// Optimistic: the change shows at once and goes back if the server refuses it.
export async function saveEditorPrefs(change) {
  const before = prefs;
  prefs = { ...prefs, ...change };
  tell();
  try {
    const p = await setEditorPreferences(prefs);
    prefs = { ...DEFAULT_EDITOR_PREFS, autosave: p?.autosave !== false };
    tell();
    return prefs;
  } catch (err) {
    prefs = before;
    tell();
    throw err;
  }
}

export function useEditorPrefs() {
  const [p, setP] = useState(prefs);
  useEffect(() => {
    listeners.add(setP);
    setP(prefs);
    loadEditorPrefs();
    return () => listeners.delete(setP);
  }, []);
  return p;
}
