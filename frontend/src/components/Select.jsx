import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

// Fully-styled dropdown replacing native <select> (whose popup list can't be
// themed). A trigger button opens a portal-rendered listbox positioned under
// it (flipping up near the viewport edge), with keyboard support and
// click-outside close.
//
//   <Select value={v} onChange={setV} options=[{value, label, hint?, disabled?}]
//           placeholder? disabled? className? title? />
//
// `options` entries may also be plain strings. `className` variants:
//   sel-embedded — borderless, for selects fused inside a bordered parent
//                  (column mapper); inherits the parent's look.
const Chevron = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="m6 9 6 6 6-6" />
  </svg>
);
const Check = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 12.5l5 5L20 6.5" />
  </svg>
);

// An option is a value row, or a non-selectable group header ({ heading }).
const norm = (o) =>
  typeof o === "object" && o !== null
    ? (o.heading != null ? { ...o, _header: true } : o)
    : { value: o, label: String(o) };

export default function Select({
  value,
  onChange,
  options = [],
  placeholder = "Select…",
  disabled = false,
  className = "",
  title,
}) {
  const items = options.map(norm);
  const selected = items.find((o) => !o._header && o.value === value);

  // Move focus to the next selectable (non-header) row in a direction.
  const step = (from, dir) => {
    let i = from;
    for (let n = 0; n < items.length; n++) {
      i += dir;
      if (i < 0 || i >= items.length) return from;
      if (!items[i]._header) return i;
    }
    return from;
  };
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [pos, setPos] = useState(null); // { left, top, bottom, minWidth, up }
  const triggerRef = useRef(null);
  const menuRef = useRef(null);

  const place = useCallback(() => {
    const r = triggerRef.current?.getBoundingClientRect();
    if (!r) return;
    const spaceBelow = window.innerHeight - r.bottom;
    const up = spaceBelow < 240 && r.top > spaceBelow;
    setPos({
      left: r.left,
      top: up ? undefined : r.bottom + 4,
      bottom: up ? window.innerHeight - r.top + 4 : undefined,
      minWidth: r.width,
      up,
    });
  }, []);

  const openMenu = () => {
    if (disabled) return;
    place();
    setActive(items.findIndex((o) => o.value === value));
    setOpen(true);
  };

  const choose = (o) => {
    if (o._header || o.disabled) return;
    setOpen(false);
    if (o.value !== value) onChange(o.value);
  };

  // Close on outside interaction / scroll / resize while open.
  useEffect(() => {
    if (!open) return;
    const onDown = (e) => {
      if (!menuRef.current?.contains(e.target) && !triggerRef.current?.contains(e.target)) {
        setOpen(false);
      }
    };
    const onScroll = (e) => {
      if (menuRef.current?.contains(e.target)) return; // scrolling the list is fine
      setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [open]);

  // Keep the active row in view as keyboard focus moves.
  useLayoutEffect(() => {
    if (!open || active < 0) return;
    menuRef.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  const onKeyDown = (e) => {
    if (disabled) return;
    if (!open) {
      if (["Enter", " ", "ArrowDown", "ArrowUp"].includes(e.key)) {
        e.preventDefault();
        openMenu();
      }
      return;
    }
    if (e.key === "Escape") { e.preventDefault(); setOpen(false); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => step(i, 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => step(i, -1)); }
    else if (e.key === "Home") { e.preventDefault(); setActive(step(-1, 1)); }
    else if (e.key === "End") { e.preventDefault(); setActive(step(items.length, -1)); }
    else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      if (items[active]) choose(items[active]);
      else setOpen(false);
    }
  };

  return (
    <>
      <button
        type="button"
        ref={triggerRef}
        className={"sel-trigger" + (open ? " open" : "") + (className ? " " + className : "")}
        onClick={() => (open ? setOpen(false) : openMenu())}
        onKeyDown={onKeyDown}
        disabled={disabled}
        title={title}
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <span className={"sel-label" + (selected ? "" : " placeholder")}>
          {selected ? selected.label : placeholder}
        </span>
        <span className="sel-chevron"><Chevron /></span>
      </button>
      {open && pos && createPortal(
        <div
          ref={menuRef}
          className="sel-menu"
          role="listbox"
          style={{
            left: pos.left,
            top: pos.top,
            bottom: pos.bottom,
            minWidth: pos.minWidth,
          }}
        >
          {items.map((o, i) =>
            o._header ? (
              <div key={"h" + i} data-i={i} className="sel-group" role="presentation">
                {o.heading}
              </div>
            ) : (
              <button
                type="button"
                key={String(o.value) + i}
                data-i={i}
                role="option"
                aria-selected={o.value === value}
                className={
                  "sel-option" +
                  (o.value === value ? " selected" : "") +
                  (i === active ? " active" : "") +
                  (o.disabled ? " disabled" : "")
                }
                onMouseEnter={() => setActive(i)}
                onClick={() => choose(o)}
                disabled={o.disabled}
              >
                <span className="sel-option-main">
                  <span className="sel-option-label">{o.label}</span>
                  {o.hint && <span className="sel-option-hint">{o.hint}</span>}
                </span>
                {o.value === value && <span className="sel-check"><Check /></span>}
              </button>
            )
          )}
        </div>,
        document.body
      )}
    </>
  );
}
