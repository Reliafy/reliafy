import { useLayoutEffect, useRef, useState } from "react";
import "./ClampLines.css";

// Long free text kept to a few lines (#UI), with "Show all" under it when
// there's more; "Show less" folds it again. The text keeps its line breaks.
// Short text shows as it is, with no button.
//
//   text       the words
//   lines      how many lines show folded (2 by default)
//   what       what it is, for the button's name ("the description")
//   className  on the wrapper; the text itself is .clampl-text
export default function ClampLines({ text, lines = 2, what = "", className = "", textClassName = "" }) {
  const box = useRef(null);
  const [long, setLong] = useState(false);
  const [open, setOpen] = useState(false);
  useLayoutEffect(() => {
    setOpen(false);
  }, [text]);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el || open) return undefined;
    const check = () => setLong(el.scrollHeight > el.clientHeight + 1);
    check();
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(check);
    ro?.observe(el);
    return () => ro?.disconnect();
  }, [text, open]);
  if (!text) return null;
  return (
    <div className={"clampl" + (className ? ` ${className}` : "")}>
      <p ref={box} className={"clampl-text" + (open ? " open" : "") + (textClassName ? ` ${textClassName}` : "")}
         style={{ "--clamp-lines": lines }}>
        {text}
      </p>
      {(long || open) && (
        <button type="button" className="link clampl-more" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? "Show less" : "Show all"}{what && <span className="sr-only"> of {what}</span>}
        </button>
      )}
    </div>
  );
}
