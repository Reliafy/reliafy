// Full screen for one part of a page (the RBD builder's canvas and toolbar).
//
// Two ways to get there. Where the browser has the Fullscreen API, the part
// itself goes full screen ("native"). Where it doesn't (an iPhone's Safari), or
// the browser refuses, the part covers the window inside the page instead
// ("page"): fixed over everything, with the page behind it held still.
//
// Dialogs, dropdowns and confirm boxes render in a portal, and while another
// element is full screen the browser shows only that element: anything left on
// <body> is hidden. So every portal renders into one shared host element
// (portalHost), and the host moves into the full-screen part while it is full
// screen and back to <body> after. Moving the host never remounts what is in
// it, so a dialog open at the time keeps what was typed.

// The browser's Fullscreen API, standard or webkit-prefixed (older Safari,
// iPad), or null where neither exists (iPhone Safari has no element
// full screen).
export function fullscreenApi(doc = typeof document === "undefined" ? null : document) {
  if (!doc) return null;
  const el = doc.documentElement || {};
  if (typeof el.requestFullscreen === "function" && typeof doc.exitFullscreen === "function") {
    return {
      request: (node) => node.requestFullscreen(),
      exit: () => doc.exitFullscreen(),
      element: () => doc.fullscreenElement || null,
      event: "fullscreenchange",
    };
  }
  if (typeof el.webkitRequestFullscreen === "function" && typeof doc.webkitExitFullscreen === "function") {
    return {
      request: (node) => node.webkitRequestFullscreen(),
      exit: () => doc.webkitExitFullscreen(),
      element: () => doc.webkitFullscreenElement || null,
      event: "webkitfullscreenchange",
    };
  }
  return null;
}

// The one element every portal renders into. It sits at the end of <body>
// with display: contents, so it takes no room of its own.
let host = null;
export function portalHost(doc = typeof document === "undefined" ? null : document) {
  if (!doc) return null;
  if (!host || host.ownerDocument !== doc) {
    host = doc.createElement("div");
    host.className = "portal-host";
    host.style.display = "contents";
    doc.body.appendChild(host);
  }
  return host;
}

// Move the portal host into ``el`` (or back to <body> with null). Focus inside
// the host survives the move (moving a node drops it otherwise).
export function movePortalHost(el, doc = typeof document === "undefined" ? null : document) {
  if (!doc) return;
  const h = portalHost(doc);
  const target = el || doc.body;
  if (h.parentNode === target) return;
  const focused = doc.activeElement;
  const refocus = focused && focused !== doc.body && h.contains(focused) ? focused : null;
  target.appendChild(h);
  if (refocus && typeof refocus.focus === "function") refocus.focus({ preventScroll: true });
}

// Something open above the full-screen part that Escape should close first:
// a dialog, a dropdown's list, a menu. The toolbar's validation check is left
// out (it doesn't close on Escape, so it would otherwise keep full screen on).
export const OPEN_LAYERS = [
  ".overlay",
  ".sel-menu",
  ".help-drawer",
  ".rbd-menu",
  ".ovm-menu:not([hidden]):not(.rbd-valid-pop)",
].join(", ");

export function hasOpenLayer(root) {
  return !!root?.querySelector?.(OPEN_LAYERS);
}

const TYPING = ["INPUT", "TEXTAREA", "SELECT"];

// Is the key event someone typing (a field, an editable block name)?
export function isTyping(e) {
  const el = e?.target;
  return !!el && (el.isContentEditable || TYPING.includes(el.tagName));
}

// Does this key press toggle full screen? F (either case), no modifier, not
// held down, and not while typing.
export function isFullScreenKey(e) {
  if (!e || (e.key !== "f" && e.key !== "F")) return false;
  if (e.metaKey || e.ctrlKey || e.altKey || e.repeat) return false;
  return !isTyping(e);
}
