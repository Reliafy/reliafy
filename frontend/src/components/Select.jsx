import { forwardRef, useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { portalHost } from "../fullScreen.js";
import { bestMatchIndex, filterOptions } from "../selectSearch.js";
import { longList, nativeSelected, optionsFromChildren } from "../selectOptions.js";
import { useField } from "./ui/Field.jsx";

// Fully-styled dropdown replacing native <select> (whose popup list can't be
// themed). A trigger button opens a portal-rendered listbox positioned under
// it (flipping up near the viewport edge), with keyboard support and
// click-outside close.
//
//   <Select value={v} onChange={setV} options=[{value, label, hint?, disabled?}]
//           placeholder? disabled? className? title? ariaLabel? searchable? />
//
// `searchable` puts a "Find…" box at the top of the open list (a long list of
// saved models, a tree of positions): typing narrows it to the rows holding every
// word typed (in the label or the hint). Typing on the closed trigger opens it
// with that letter already in the box.
//
// Instead of `options`, the rows may be written as <option>/<optgroup> children,
// as for a native <select>: values are then strings, and with no match the
// first row that isn't disabled shows (what a browser does). More than about
// 15 rows and the list is searchable unless `searchable={false}`.
// Inside a <Field> the trigger takes the field's id, help and error wiring.
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

const Select = forwardRef(function Select({
  value,
  onChange,
  options,
  children,
  placeholder = "Select…",
  disabled = false,
  className = "",
  title,
  ariaLabel,
  "aria-label": ariaLabelAttr,
  searchable: searchableProp,
  id,
  autoFocus,
  onKeyDown: ownKeyDown,
  onBlur,
  "aria-describedby": describedBy,
  "aria-invalid": invalid,
  "aria-labelledby": labelledBy,
}, ref) {
  const field = useField();
  const listId = useId();
  // Written as <option> children: string values, matched the way a browser does.
  const fromChildren = options == null;
  const all = (fromChildren ? optionsFromChildren(children) : options).map(norm);
  const selected = fromChildren ? nativeSelected(all, value) : all.find((o) => !o._header && o.value === value);
  // Shown but not chosen (value matches no row): picking it still calls onChange.
  const matched = !!selected && (!fromChildren || selected.value === String(value ?? ""));
  const isChosen = (o) => matched && o === selected;
  const searchable = searchableProp ?? longList(all);
  const [query, setQuery] = useState("");
  const items = searchable ? filterOptions(all, query) : all;
  const searchRef = useRef(null);

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
  const setTrigger = useCallback((el) => {
    triggerRef.current = el;
    if (typeof ref === "function") ref(el);
    else if (ref) ref.current = el;
  }, [ref]);
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

  // seed: a letter typed on the closed trigger of a searchable list starts the search.
  const openMenu = (seed = "") => {
    if (disabled) return;
    place();
    setQuery(seed);
    setActive(all.findIndex((o) => !o._header && isChosen(o)));
    setOpen(true);
  };

  const choose = (o) => {
    if (o._header || o.disabled) return;
    setOpen(false);
    // Focus back on the trigger, as a native list leaves it.
    triggerRef.current?.focus({ preventScroll: true });
    if (!isChosen(o)) onChange?.(o.value);
  };
  // The caller's onBlur fires when focus leaves the control, not when it moves into its own list.
  const blurOut = (e) => {
    const to = e.relatedTarget;
    if (to && (menuRef.current?.contains(to) || triggerRef.current === to)) return;
    onBlur?.(e);
  };

  // Close on a click outside. A scroll or resize elsewhere moves the list with its
  // trigger (a dialog scrolling, the page settling as it opens); it closes only
  // once the trigger has gone out of sight.
  useEffect(() => {
    if (!open) return;
    const onDown = (e) => {
      if (!menuRef.current?.contains(e.target) && !triggerRef.current?.contains(e.target)) {
        setOpen(false);
      }
    };
    const onScroll = (e) => {
      if (menuRef.current?.contains(e.target)) return; // scrolling the list is fine
      const r = triggerRef.current?.getBoundingClientRect();
      if (!r || r.bottom < 0 || r.top > window.innerHeight) setOpen(false);
      else place();
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [open, place]);

  // A searchable list takes the typing as soon as it opens.
  useLayoutEffect(() => {
    if (open && searchable) searchRef.current?.focus({ preventScroll: true });
  }, [open, searchable]);

  // Keep the active row in view as keyboard focus moves.
  useLayoutEffect(() => {
    if (!open || active < 0) return;
    // Scroll the list only: scrollIntoView would move the page or dialog under it too.
    const menu = menuRef.current;
    const row = menu?.querySelector(`[data-i="${active}"]`);
    if (!row) return;
    if (row.offsetTop < menu.scrollTop) menu.scrollTop = row.offsetTop;
    else if (row.offsetTop + row.offsetHeight > menu.scrollTop + menu.clientHeight) {
      menu.scrollTop = row.offsetTop + row.offsetHeight - menu.clientHeight;
    }
  }, [open, active]);

  const onKeyDown = (e) => {
    if (disabled) return;
    if (!open) {
      // The caller's keys (an in-cell editor's Escape) come first while the list is shut.
      ownKeyDown?.(e);
      if (e.defaultPrevented) return;
      if (["Enter", " ", "ArrowDown", "ArrowUp"].includes(e.key)) {
        e.preventDefault();
        openMenu();
      } else if (searchable && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        // Type-ahead: typing on the closed list opens it with what was typed in its search box.
        e.preventDefault();
        openMenu(e.key);
      }
      return;
    }
    // Escape shuts the list only, not the form or dialog around it (as a native list's does).
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setOpen(false); triggerRef.current?.focus(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => step(i, 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => step(i, -1)); }
    else if (e.key === "Home") { e.preventDefault(); setActive(step(-1, 1)); }
    else if (e.key === "End") { e.preventDefault(); setActive(step(items.length, -1)); }
    else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      // Typed into the search and pressed Enter: the first match.
      const pick = items[active] && !items[active]._header ? items[active]
        : searchable && query ? items[bestMatchIndex(items, query)] : null;
      if (pick) choose(pick);
      else setOpen(false);
    }
  };

  return (
    <>
      <button
        type="button"
        ref={setTrigger}
        id={id || field?.id}
        className={"sel-trigger" + (open ? " open" : "") + (className ? " " + className : "")}
        onClick={() => (open ? setOpen(false) : openMenu())}
        onKeyDown={onKeyDown}
        onBlur={onBlur && blurOut}
        disabled={disabled}
        autoFocus={autoFocus}
        title={title}
        aria-label={ariaLabel ?? ariaLabelAttr}
        aria-labelledby={labelledBy}
        aria-describedby={describedBy || field?.describedBy}
        aria-invalid={invalid ?? (field?.invalid ? "true" : undefined)}
        data-value={selected ? String(selected.value) : ""}
        role="combobox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
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
          id={listId}
          className="sel-menu"
          role="listbox"
          style={{
            left: pos.left,
            top: pos.top,
            bottom: pos.bottom,
            minWidth: pos.minWidth,
          }}
        >
          {searchable && (
            <input
              ref={searchRef}
              type="search"
              className="sel-search"
              value={query}
              placeholder="Find…"
              aria-label="Find in the list"
              aria-controls={listId}
              aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
              onChange={(e) => {
                // Highlight the row Enter will take: the closest match.
                const q = e.target.value;
                setQuery(q);
                setActive(q.trim() ? bestMatchIndex(filterOptions(all, q), q) : -1);
              }}
              onBlur={onBlur && blurOut}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown" && active < 0) { e.preventDefault(); setActive(step(-1, 1)); return; }
                onKeyDown(e);
              }}
            />
          )}
          {searchable && items.length === 0 && <p className="sel-none">Nothing matches.</p>}
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
                id={`${listId}-${i}`}
                role="option"
                tabIndex={-1}
                aria-selected={isChosen(o)}
                data-value={String(o.value)}
                className={
                  "sel-option" +
                  (isChosen(o) ? " selected" : "") +
                  (i === active ? " active" : "") +
                  (o.disabled ? " disabled" : "")
                }
                onMouseEnter={() => setActive(i)}
                // Keep focus where it is (the trigger or the search box) while a row is clicked.
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(o)}
                disabled={o.disabled}
              >
                <span className="sel-option-main">
                  <span className="sel-option-label">{o.label}</span>
                  {o.hint && <span className="sel-option-hint">{o.hint}</span>}
                </span>
                {isChosen(o) && <span className="sel-check"><Check /></span>}
              </button>
            )
          )}
        </div>,
        portalHost()
      )}
    </>
  );
});

export default Select;
