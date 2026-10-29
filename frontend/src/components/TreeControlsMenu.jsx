import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { portalHost } from "../fullScreen.js";
import { EDGE } from "../menuPlace.js";
import { menuMove } from "../treeControls.js";

// The tree pane's ⋯ menu: how the tree is shown (Arrange by, the levels,
// Close everything), what it shows (the Show only filters, ticked when on),
// and the pane's other actions (Import, Add the sample truck). It stays open
// while several things are changed, and closes on Esc, Tab, a click outside or
// Done; Esc and Done put the focus back on the ⋯ button. The menu pattern:
// the first item takes the focus; ↑ ↓ go from row to row, ← → along a row of
// choices, Home End, and Enter or Space chooses.
//
// When anything isn't as usual (`changed`) the button shows how many, and the
// menu has Reset, so a filter tucked away in here can never hide rows unseen.
// Drawn in the shared portal host (so it shows in full screen, and isn't cut
// off by the pane), under the button, kept on screen at phone width.
//
//   pinned   {name, onUnpin} while a branch is isolated: "Show everything"
//            heads the menu; or null
//   arrange  {value, options: [{value, label, title}], onChange} or null
//   note     a line in place of Arrange by (why it isn't offered here), or null
//   levels   {value (1..4, Infinity, 0, or null), onLevel(n), onCloseAll} or null
//   chips    [{id, label, title, on}]; onChip(id) turns one on or off
//   changed  [{id, label}]: what isn't as usual; onReset puts it back
//   actions  [{id, label, onSelect}]: they close the menu first

const LEVELS = [1, 2, 3, 4];

const Dots = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true">
    <circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" />
  </svg>
);

const Tick = ({ on }) => (
  <span className={"tm-tick" + (on ? " on" : "")} aria-hidden="true">
    {on && <svg viewBox="0 0 16 16" width="12" height="12"><path d="m3.5 8.5 3 3 6-7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>}
  </span>
);

export default function TreeControlsMenu({
  pinned = null, arrange = null, note = null, levels = null, chips = [], onChip, changed = [], onReset, actions = [],
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);
  const btn = useRef(null);
  const menu = useRef(null);
  const last = useRef(null); // the item that had the focus, kept when the items change
  const id = useId().replace(/:/g, "");

  const close = useCallback((focusBack) => {
    last.current = null;
    setOpen(false);
    setPos(null);
    if (focusBack) btn.current?.focus({ preventScroll: true });
  }, []);

  // Under the button, moved in from the edges; as tall as the window allows
  // (it scrolls inside when it's taller).
  const place = useCallback(() => {
    const b = btn.current?.getBoundingClientRect();
    const el = menu.current;
    if (!b || !el) return;
    const w = el.offsetWidth;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const left = Math.round(Math.max(EDGE, Math.min(b.left, vw - w - EDGE)));
    const top = Math.round(b.bottom + 4);
    const maxHeight = Math.max(160, vh - top - EDGE);
    setPos((p) => (p && p.left === left && p.top === top && p.maxHeight === maxHeight ? p : { left, top, maxHeight }));
  }, []);
  useLayoutEffect(() => {
    if (open) place();
  });

  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => {
      if (menu.current?.contains(e.target) || btn.current?.contains(e.target)) return;
      close(false);
    };
    const esc = (e) => {
      if (e.key === "Escape") close(true);
    };
    const move = () => place();
    document.addEventListener("mousedown", away);
    document.addEventListener("touchstart", away);
    document.addEventListener("keydown", esc);
    window.addEventListener("resize", move);
    window.addEventListener("scroll", move, true);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("touchstart", away);
      document.removeEventListener("keydown", esc);
      window.removeEventListener("resize", move);
      window.removeEventListener("scroll", move, true);
    };
  }, [open, close, place]);

  const items = () => [...(menu.current?.querySelectorAll("[data-id]") || [])];
  const focusId = (key) => {
    const el = items().find((x) => x.dataset.id === key);
    el?.focus({ preventScroll: false });
    return !!el;
  };
  // Opened: the first item takes the focus. After a change that removes the
  // item with the focus (Reset, or an arrangement with no levels), the focus
  // goes back into the menu rather than being lost.
  useEffect(() => {
    if (!open || !pos) return;
    const a = document.activeElement;
    if (menu.current?.contains(a)) return;
    if (a && a !== document.body && a !== btn.current) return;
    if (!(last.current && focusId(last.current))) items()[0]?.focus({ preventScroll: true });
  });

  const onKeyDown = (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close(true);
      return;
    }
    if (e.key === "Tab") {
      e.preventDefault();
      close(true);
      return;
    }
    const all = items();
    const rows = [];
    for (const el of all) {
      const row = el.dataset.row;
      if (row && rows.length && rows[rows.length - 1].row === row) rows[rows.length - 1].ids.push(el.dataset.id);
      else rows.push({ row, ids: [el.dataset.id] });
    }
    const at = document.activeElement?.dataset?.id ?? null;
    const checked = (x) => all.find((el) => el.dataset.id === x)?.getAttribute("aria-checked") === "true";
    const to = menuMove(rows.map((r) => r.ids), at, e.key, checked);
    if (to == null) return;
    e.preventDefault();
    e.stopPropagation();
    focusId(to);
  };

  const levelOn = (n) => levels && levels.value === n;
  const menuEl = open && createPortal(
    <div ref={menu} id={`${id}-menu`} className="ovm-menu tm-menu" role="menu" aria-label="Tree options" tabIndex={-1}
         style={pos ? { left: pos.left, top: pos.top, maxHeight: pos.maxHeight } : { left: 0, top: 0, visibility: "hidden" }}
         onKeyDown={onKeyDown} onFocus={(e) => { if (e.target.dataset?.id) last.current = e.target.dataset.id; }}
         onContextMenu={(e) => e.preventDefault()}>
      {pinned && (
        <>
          <button type="button" role="menuitem" tabIndex={-1} data-id="unpin" className="ovm-item tm-item tm-plain"
                  title={`Showing only ${pinned.name}: show the whole tree again`}
                  onClick={() => { close(true); pinned.onUnpin(); }}>Show everything</button>
          <div className="tm-sep" role="separator" />
        </>
      )}
      {arrange && (
        <div className="tm-sec" role="group" aria-labelledby={`${id}-arr`}>
          <div className="tm-label" id={`${id}-arr`}>Arrange by</div>
          <div className="tm-seg">
            {arrange.options.map((a) => (
              <button key={a.value} type="button" role="menuitemradio" aria-checked={a.value === arrange.value} tabIndex={-1}
                      data-id={`arr:${a.value}`} data-row="arr" title={a.title}
                      className={"tm-seg-btn" + (a.value === arrange.value ? " on" : "")}
                      onClick={() => arrange.onChange(a.value)}>{a.label}</button>
            ))}
          </div>
        </div>
      )}
      {note && <p className="tm-note">{note}</p>}
      {levels && (
        <div className="tm-sec" role="group" aria-labelledby={`${id}-lvl`}>
          <div className="tm-label" id={`${id}-lvl`}>Open to level</div>
          <div className="tm-seg">
            {LEVELS.map((n) => (
              <button key={n} type="button" role="menuitemradio" aria-checked={levelOn(n)} tabIndex={-1}
                      data-id={`lvl:${n}`} data-row="lvl" aria-label={`Open to level ${n}`} title={`Open to level ${n}`}
                      className={"tm-seg-btn" + (levelOn(n) ? " on" : "")} onClick={() => levels.onLevel(n)}>{n}</button>
            ))}
            <button type="button" role="menuitemradio" aria-checked={levelOn(Infinity)} tabIndex={-1}
                    data-id="lvl:all" data-row="lvl" aria-label="Open everything" title="Open everything"
                    className={"tm-seg-btn" + (levelOn(Infinity) ? " on" : "")} onClick={() => levels.onLevel(Infinity)}>All</button>
          </div>
          <button type="button" role="menuitemradio" aria-checked={levelOn(0)} tabIndex={-1} data-id="lvl:0"
                  className="ovm-item tm-item" onClick={levels.onCloseAll}>
            <Tick on={levelOn(0)} />Close everything
          </button>
        </div>
      )}
      {chips.length > 0 && (
        <div className="tm-sec" role="group" aria-labelledby={`${id}-only`}>
          <div className="tm-label" id={`${id}-only`}>Show only</div>
          {chips.map((c) => (
            <button key={c.id} type="button" role="menuitemcheckbox" aria-checked={!!c.on} tabIndex={-1} data-id={`chip:${c.id}`}
                    title={c.title} className={"ovm-item tm-item" + (c.on ? " on" : "")} onClick={() => onChip(c.id)}>
              <Tick on={c.on} />{c.label}
            </button>
          ))}
        </div>
      )}
      {actions.length > 0 && (
        <>
          <div className="tm-sep" role="separator" />
          {actions.map((a) => (
            <button key={a.id} type="button" role="menuitem" tabIndex={-1} data-id={`act:${a.id}`} className="ovm-item tm-item tm-plain"
                    onClick={() => { close(false); a.onSelect(); }}>{a.label}</button>
          ))}
        </>
      )}
      <div className="tm-sep" role="separator" />
      <div className="tm-foot">
        {changed.length > 0 && (
          <button type="button" role="menuitem" tabIndex={-1} data-id="reset" data-row="foot" className="ovm-item tm-item tm-reset"
                  title={`Back to the whole tree, Positions, level 2 and no filters (now: ${changed.map((c) => c.label).join(", ")})`} onClick={onReset}>
            Reset to the usual view
          </button>
        )}
        <button type="button" role="menuitem" tabIndex={-1} data-id="done" data-row="foot" className="ovm-item tm-item tm-done"
                onClick={() => close(true)}>Done</button>
      </div>
    </div>,
    portalHost(),
  );

  return (
    <>
      <button ref={btn} type="button" className={"secondary ovm-trigger tm-trigger" + (changed.length ? " changed" : "")}
              aria-haspopup="menu" aria-expanded={open} aria-controls={open ? `${id}-menu` : undefined}
              aria-label={changed.length ? `Tree options: ${changed.length} changed` : "Tree options"}
              title={changed.length ? `Arrange, levels and filters (${changed.map((c) => c.label).join(", ")})` : "Arrange, levels and filters"}
              onClick={() => (open ? close(false) : setOpen(true))}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown" && !open) {
                  e.preventDefault();
                  setOpen(true);
                }
              }}>
        <Dots />
        {changed.length > 0 && <span className="tm-count" aria-hidden="true">{changed.length}</span>}
      </button>
      {menuEl}
    </>
  );
}
