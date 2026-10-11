// A strip that scrolls sideways and says so (#301): the edge that hides
// content fades out, and with `arrows` a chevron there scrolls it a page.
// Wide tables and tab rows use it, so a phone reader can see there's more.
//
//   className      classes for the scrolling element (keeps a caller's own
//                  wrapper styling, e.g. "fleet-items-scroll")
//   wrapClassName  classes for the outer frame
//   arrows         show a chevron button at each faded edge
//   arrowLabel     what the arrows scroll, for their accessible names
//   reveal         a selector for a child kept in view (e.g. ".tab.active"),
//                  re-checked when `revealKey` changes
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { scrollEdges, scrollStep, scrollToReveal } from "../../scrollCue.js";

function Chevron({ dir }) {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor"
         strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d={dir < 0 ? "M10 3.5 5.5 8l4.5 4.5" : "M6 3.5 10.5 8 6 12.5"} />
    </svg>
  );
}

export default function ScrollCue({
  className,
  wrapClassName,
  arrows = false,
  arrowLabel = "Scroll",
  reveal,
  revealKey,
  children,
  ...rest
}) {
  const ref = useRef(null);
  const [edges, setEdges] = useState({ start: false, end: false });

  const update = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const next = scrollEdges(el);
    setEdges((prev) => (prev.start === next.start && prev.end === next.end ? prev : next));
  }, []);

  // Content can change width without this component re-rendering (a table
  // filling in, a font loading), so watch the strip and what's in it.
  const observer = useRef(null);
  useEffect(() => {
    if (typeof ResizeObserver === "undefined") return undefined;
    observer.current = new ResizeObserver(update);
    return () => observer.current?.disconnect();
  }, [update]);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (observer.current) {
      observer.current.observe(el);
      for (const child of el.children) observer.current.observe(child);
    }
    update();
  });

  // Keep the chosen child (the active tab) in view, clear of the fade.
  const first = useRef(true);
  useLayoutEffect(() => {
    const el = ref.current;
    const target = reveal && el?.querySelector(reveal);
    if (!target) return;
    const box = target.getBoundingClientRect();
    const at = box.left - el.getBoundingClientRect().left + el.scrollLeft;
    const left = scrollToReveal(el, { left: at, width: box.width }, 40);
    if (left !== null) el.scrollTo({ left, behavior: first.current ? "auto" : "smooth" });
    first.current = false;
  }, [reveal, revealKey]);

  const step = (dir) => {
    const el = ref.current;
    if (el) el.scrollTo({ left: scrollStep(el, dir), behavior: "smooth" });
  };

  return (
    <div className={"scroll-cue" + (edges.start ? " cue-start" : "") + (edges.end ? " cue-end" : "")
                    + (wrapClassName ? " " + wrapClassName : "")}>
      <div ref={ref} className={"scroll-cue-body" + (className ? " " + className : "")} onScroll={update} {...rest}>
        {children}
      </div>
      {arrows && edges.start && (
        <button type="button" className="scroll-cue-arrow start" tabIndex={-1} aria-label={`${arrowLabel} left`}
                onClick={() => step(-1)}>
          <Chevron dir={-1} />
        </button>
      )}
      {arrows && edges.end && (
        <button type="button" className="scroll-cue-arrow end" tabIndex={-1} aria-label={`${arrowLabel} right`}
                onClick={() => step(1)}>
          <Chevron dir={1} />
        </button>
      )}
    </div>
  );
}
