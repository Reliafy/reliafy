import { useEffect } from "react";

// Tab and Shift+Tab inside a dialog go round its own controls, never out to
// the page behind it. Plain JS (no JSX) so it can be tested without a browser.
const FOCUSABLE = "a[href], button:not([disabled]), input:not([disabled]):not([type='hidden']), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";

export function trapTab(e, node) {
  // A control that used the Tab itself (a dropdown picking its highlighted
  // option, whose list is portalled outside the dialog) keeps it.
  if (e.key !== "Tab" || !node || e.defaultPrevented) return;
  const all = [...node.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === document.activeElement);
  if (!all.length) {
    e.preventDefault();
    return;
  }
  const first = all[0];
  const last = all[all.length - 1];
  const at = document.activeElement;
  if (e.shiftKey && (at === first || at === node || !node.contains(at))) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && (at === last || !node.contains(at))) {
    e.preventDefault();
    first.focus();
  }
}

// Focus into `ref`'s node when it mounts (unless something inside already has
// it) and back to the element that had it before when it unmounts: the one
// rule for every shared dialog (Modal, the help drawer). `active`: false
// while a dialog that stays mounted is shut (the help drawer).
export function useDialogFocus(ref, active = true) {
  useEffect(() => {
    if (!active) return undefined;
    const before = document.activeElement;
    const node = ref.current;
    if (node && !node.contains(document.activeElement)) node.focus({ preventScroll: true });
    return () => {
      // Only when focus is still in this dialog (or dropped to the page):
      // a page it navigated to keeps its own focus.
      const now = document.activeElement;
      const lost = !now || now === document.body || (node && node.contains(now));
      if (lost && before && typeof before.focus === "function" && document.contains(before)) {
        before.focus({ preventScroll: true });
      }
    };
  }, [ref, active]);
}
