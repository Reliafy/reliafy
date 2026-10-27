import { useLayoutEffect, useRef, useState } from "react";
import Modal from "./Modal.jsx";
import "./ClampText.css";

// Long free text (a description, a position's operating context) kept to two lines, so it
// never takes the view from the work below it; "More" opens the whole of it in
// a dialog. Short text shows as it is, with no button.
export default function ClampText({ text, title = "Description", className = "" }) {
  const box = useRef(null);
  const [long, setLong] = useState(false);
  const [open, setOpen] = useState(false);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    const check = () => setLong(el.scrollHeight > el.clientHeight + 1);
    check();
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(check);
    ro?.observe(el);
    return () => ro?.disconnect();
  }, [text]);
  if (!text) return null;
  return (
    <div className={"clamp" + (className ? " " + className : "")}>
      <p ref={box} className="clamp-text">{text}</p>
      {long && (
        <button type="button" className="link clamp-more" onClick={() => setOpen(true)} aria-haspopup="dialog">
          More<span className="sr-only"> of the {title.toLowerCase()}</span>
        </button>
      )}
      {open && (
        <Modal title={title} onClose={() => setOpen(false)}>
          <p className="clamp-full">{text}</p>
        </Modal>
      )}
    </div>
  );
}
