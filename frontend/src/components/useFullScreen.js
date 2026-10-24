import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { fullscreenApi, hasOpenLayer, isTyping, movePortalHost } from "../fullScreen.js";

// Full screen for the element in ``ref`` (see fullScreen.js): the browser's
// own full screen where it has one, otherwise the element covers the window
// inside the page. Returns { full, mode, enter, exit, toggle }; ``mode`` is
// "native", "page" or null. Nothing is remembered: the page always opens
// normal. ``returnFocus`` (a ref) gets focus whenever focus was lost on the
// way in or out (the button pressed may have been swapped for another).
//
// Leaving by the browser's own means (Escape, its exit control) is picked up
// from ``fullscreenchange``. In the page mode Escape exits too, unless a
// dialog, list or menu is open over it (Escape closes that first).
export default function useFullScreen(ref, { returnFocus } = {}) {
  const [mode, setMode] = useState(null);
  const modeRef = useRef(null);
  modeRef.current = mode;

  // The portal host follows: into the element while full screen, back after.
  // A layout effect, so a dialog opened in the same moment lands in the right place.
  useLayoutEffect(() => {
    if (!mode || !ref.current) return undefined;
    movePortalHost(ref.current);
    return () => movePortalHost(null);
  }, [mode, ref]);

  const refocus = useCallback(() => {
    // Two frames: the browser settles its own focus after leaving full screen.
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
      const now = document.activeElement;
      const lost = !now || now === document.body || !now.isConnected;
      const to = returnFocus?.current;
      if (lost && to && to.isConnected) to.focus({ preventScroll: true });
    }));
  }, [returnFocus]);

  // Focus lost on the way in (the button pressed went): to the Exit button.
  useEffect(() => {
    if (mode) refocus();
  }, [mode, refocus]);

  // The page mode holds the page behind still (no scrolling under the canvas).
  useEffect(() => {
    if (mode !== "page") return undefined;
    const root = document.documentElement;
    root.classList.add("full-screen-lock");
    return () => root.classList.remove("full-screen-lock");
  }, [mode]);

  // The browser left (or entered) full screen: keep the state in step.
  useEffect(() => {
    const api = fullscreenApi();
    if (!api) return undefined;
    const onChange = () => {
      const isOurs = api.element() === ref.current && !!ref.current;
      if (isOurs) setMode("native");
      else if (modeRef.current === "native") {
        setMode(null);
        refocus();
      }
    };
    document.addEventListener(api.event, onChange);
    return () => document.removeEventListener(api.event, onChange);
  }, [ref, refocus]);

  const enter = useCallback(async () => {
    const el = ref.current;
    if (!el || modeRef.current) return;
    const api = fullscreenApi();
    if (api) {
      try {
        await api.request(el);
        // The change event sets "native"; set it here too in case it came first.
        if (api.element() === el) setMode("native");
        return;
      } catch {
        // Refused (an embedded frame without permission, say): the page mode.
      }
    }
    setMode("page");
  }, [ref]);

  const exit = useCallback(async () => {
    const was = modeRef.current;
    if (!was) return;
    if (was === "native") {
      const api = fullscreenApi();
      try {
        if (api?.element()) await api.exit();
      } catch {
        // Already gone: fall through and reset.
      }
    }
    setMode(null);
    refocus();
  }, [refocus]);

  const toggle = useCallback(() => (modeRef.current ? exit() : enter()), [enter, exit]);

  // Escape leaves the page mode (the browser handles its own). Capture phase,
  // so a dialog or list still on screen is seen before its own Escape closes it.
  useEffect(() => {
    if (mode !== "page") return undefined;
    const onKey = (e) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (hasOpenLayer(ref.current)) return;
      // Escape in a block's name box cancels the rename, not full screen.
      if (isTyping(e) && e.target.closest?.(".react-flow__node")) return;
      exit();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [mode, ref, exit]);

  // Leaving the page while full screen: let go of the browser's full screen.
  useEffect(() => () => {
    if (modeRef.current === "native") {
      const api = fullscreenApi();
      if (api?.element()) api.exit().catch?.(() => {});
    }
  }, []);

  return { full: !!mode, mode, enter, exit, toggle };
}
