import { useEffect, useMemo } from "react";
import { setUnsaved } from "./buildCheck.js";

// Tell the build check this part of the app has changes not yet kept, so an
// update waits behind a bar instead of reloading the page. Clears on unmount.
export function useUnsavedSignal(key, on) {
  useEffect(() => {
    setUnsaved(key, !!on);
    return () => setUnsaved(key, false);
  }, [key, on]);
}

// A ref-like `{ current }` whose writes are also the unsaved signal (for code
// that keeps its dirty flag in a ref).
export function useUnsavedRef(key) {
  const ref = useMemo(() => {
    let v = false;
    return { get current() { return v; }, set current(x) { v = !!x; setUnsaved(key, v); } };
  }, [key]);
  useEffect(() => () => setUnsaved(key, false), [key]);
  return ref;
}
