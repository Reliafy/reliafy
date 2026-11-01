import { useCallback, useLayoutEffect, useRef } from "react";

// A textarea that starts at one line and grows with its text (no resize
// handle). Where the browser sizes it from its content (`field-sizing:
// content` in the CSS) this does nothing; elsewhere it sets the height to fit
// after each change. Returns a ref for the textarea; `value` is its text.
const native = typeof CSS !== "undefined" && typeof CSS.supports === "function" && CSS.supports("field-sizing", "content");

export function fitHeight(el) {
  if (!el || native) return;
  el.style.height = "auto";
  const cs = getComputedStyle(el);
  const edge = parseFloat(cs.borderTopWidth) + parseFloat(cs.borderBottomWidth);
  el.style.height = `${el.scrollHeight + edge}px`;
}

export default function useAutoGrow(value, outer = null) {
  const node = useRef(null);
  const ref = useCallback((el) => {
    node.current = el;
    if (typeof outer === "function") outer(el);
    else if (outer) outer.current = el;
  }, [outer]);
  useLayoutEffect(() => { fitHeight(node.current); }, [value]);
  return ref;
}
