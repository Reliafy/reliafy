// Has the server been updated under this open tab? The server sends its build id
// on every /api response (X-Reliafy-Build); the bundle carries its own
// (VITE_BUILD_ID, set by the image build). On a mismatch the page reloads to pick
// up the new code, but never mid-request or mid-typing: automatically at the next
// route change when nothing is unsaved, otherwise a slim bar offers Reload.
// With no id on either side (local dev, tst) the check is off.

export const BUILD_HEADER = "X-Reliafy-Build";
const GUARD_KEY = "reliafy:build-reloaded";

export const clientBuild = () => import.meta.env?.VITE_BUILD_ID || "";

// What to do: "none", "reload" (at the next route change) or "bar" (offer it).
// `reloadedFor`: the server build we already reloaded for; if the page still
// mismatches after that (a stale cache), leave it alone rather than loop.
export function decideBuildAction({ client, server, unsaved = false, reloadedFor = "" }) {
  if (!client || !server || client === server) return "none";
  if (reloadedFor === server) return "none";
  return unsaved ? "bar" : "reload";
}

// Unsaved-work signals: any part of the app with changes not yet kept registers
// here (setUnsaved(key, true)) and clears it on save or close.
const unsavedKeys = new Set();
export function setUnsaved(key, on) {
  if (on) unsavedKeys.add(key);
  else unsavedKeys.delete(key);
  emit();
}
export const anyUnsaved = () => unsavedKeys.size > 0;

let pendingServer = "";
const listeners = new Set();
const emit = () => listeners.forEach((f) => f());
export function subscribeBuild(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

// Called with each API response's header value.
export function noteServerBuild(server, client = clientBuild()) {
  if (!server || !client || server === client || server === pendingServer) return;
  pendingServer = server;
  emit();
}

export const pendingBuild = () => pendingServer;

function guard() {
  try {
    return window.sessionStorage.getItem(GUARD_KEY) || "";
  } catch {
    return "";
  }
}

export function currentBuildAction() {
  return decideBuildAction({
    client: clientBuild(), server: pendingServer, unsaved: anyUnsaved(), reloadedFor: guard(),
  });
}

export function reloadForBuild() {
  try {
    window.sessionStorage.setItem(GUARD_KEY, pendingServer);
  } catch {
    /* storage blocked: the reload is still one-off, the page then matches */
  }
  window.location.reload();
}

// For tests.
export function _reset() {
  pendingServer = "";
  unsavedKeys.clear();
}
