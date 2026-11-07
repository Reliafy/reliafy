import { Fragment, useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { portalHost } from "../fullScreen.js";
import { placeMenu, placeSubmenu } from "../menuPlace.js";
import usePhone from "../usePhone.js";
import useMenuDismiss from "./useMenuDismiss.js";

// A row's own menu (a context menu): opened by right-click, a row's ⋯ button,
// or Shift+F10 / the Menu key. Drawn in the shared portal host (so it shows in
// full screen too) at `at` ({x, y}: the pointer, or the corner of what opened
// it), moved in to stay on screen near the edges. The menu pattern: the first
// item takes the focus, ↑ ↓ Home End move, Enter or Space chooses, Esc or Tab
// closes. It closes like every menu (useMenuDismiss), on a resize, and on a
// scroll that moves its row (the element `anchorId` names) away from it.
// `onClose` puts the focus back where it belongs (the row).
//
// items: [{id, label, danger?, disabled?, reason?, items?}]; onChoose(id) runs
// after the menu has closed. A disabled item stays in the menu (so it can be
// found and its reason read: under its label, and to a screen reader as its
// description) but does nothing.
//
// An item with `items` is a submenu ("Isolate ›"). On a wide screen it opens
// beside the menu (pointing at it, or → / Enter / Space; ← or Esc goes back to
// it); on a phone it opens in place, under its item, so nothing goes off the
// narrow screen. A submenu's item with `checked` (true or false) is a radio,
// ticked when true.
// Styled as the app's other menus (.ovm-menu / .ovm-item).

const top = (el) => [...el.querySelectorAll(":scope > [data-path], :scope > [role='group'] > [data-path]")];

export default function RowMenu({ items, at, label, anchorId, onChoose, onClose }) {
  const ref = useRef(null);
  const subRef = useRef(null);
  const uid = useId();
  const phone = usePhone();
  const [pos, setPos] = useState(null);
  // The submenu open: {id, focus} (focus: its first item takes the focus).
  const [sub, setSub] = useState(null);
  const [subPos, setSubPos] = useState(null);
  const close = useCallback(() => onClose(), [onClose]);
  useMenuDismiss(true, close, ref);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    setPos(placeMenu(at, { w: r.width, h: r.height }, { vw: window.innerWidth, vh: window.innerHeight }));
  }, [at, phone && sub?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (pos && !sub) ref.current?.querySelector("[role^='menuitem']")?.focus({ preventScroll: true });
  }, [pos]); // eslint-disable-line react-hooks/exhaustive-deps

  // A submenu beside the menu (a wide screen): placed by its item, then its
  // first item focused when it was opened from the keyboard.
  useLayoutEffect(() => {
    if (!sub || phone) {
      setSubPos(null);
      return;
    }
    const item = ref.current?.querySelector(`[data-sub="${sub.id}"]`);
    const el = subRef.current;
    if (!item || !el) return;
    const s = el.getBoundingClientRect();
    setSubPos(placeSubmenu(item.getBoundingClientRect(), { w: s.width, h: s.height }, { vw: window.innerWidth, vh: window.innerHeight }));
  }, [sub?.id, phone]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!sub?.focus) return;
    const host = phone ? ref.current?.querySelector(`[data-group="${sub.id}"]`) : subRef.current;
    if (phone || subPos) host?.querySelector("[role^='menuitem']")?.focus({ preventScroll: true });
  }, [sub, subPos, phone]);

  // A scroll that moves the row, or a resize, closes it (it would be left
  // floating away from its row). A scroll event that arrives just after the
  // menu opened, from a scroll that ended before it, moves nothing.
  useEffect(() => {
    const topOf = () => document.getElementById(anchorId)?.getBoundingClientRect().top;
    const start = topOf();
    const onScroll = (e) => {
      if (ref.current?.contains(e.target)) return;
      const now = topOf();
      if (start == null || now == null || Math.abs(now - start) > 1) close();
    };
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", close);
    };
  }, [close, anchorId]);

  const itemAt = (path) => {
    const [i, j] = String(path).split(".").map(Number);
    return j == null || Number.isNaN(j) ? items[i] : items[i]?.items?.[j];
  };
  const choose = (it, { keyboard = false } = {}) => {
    if (!it || it.disabled) return;
    if (it.items) {
      setSub((s) => (s?.id === it.id && phone ? null : { id: it.id, focus: keyboard || phone }));
      return;
    }
    onClose();
    onChoose(it.id);
  };
  const backToParent = () => {
    const id = sub?.id;
    setSub(null);
    ref.current?.querySelector(`[data-sub="${id}"]`)?.focus({ preventScroll: true });
  };
  const onKeyDown = (e) => {
    const all = top(ref.current);
    const i = all.indexOf(document.activeElement);
    const to = (n) => all[(n + all.length) % all.length]?.focus();
    const at_ = i >= 0 ? itemAt(all[i].dataset.path) : null;
    if (e.key === "ArrowDown") to(i + 1);
    else if (e.key === "ArrowUp") to(i < 0 ? all.length - 1 : i - 1);
    else if (e.key === "Home") to(0);
    else if (e.key === "End") to(all.length - 1);
    else if (e.key === "ArrowRight" && at_?.items && !at_.disabled) setSub({ id: at_.id, focus: true });
    else if (e.key === "ArrowLeft" && phone && sub) backToParent();
    else if (e.key === "Escape" && phone && sub) backToParent();
    else if (e.key === "Escape" || e.key === "Tab") close();
    else if ((e.key === "Enter" || e.key === " ") && at_) choose(at_, { keyboard: true });
    else return;
    e.preventDefault();
    e.stopPropagation();
  };
  // The submenu beside the menu: its own arrows; ← or Esc back to its item.
  const onSubKey = (e) => {
    const all = [...subRef.current.querySelectorAll("[data-path]")];
    const i = all.indexOf(document.activeElement);
    const to = (n) => all[(n + all.length) % all.length]?.focus();
    if (e.key === "ArrowDown") to(i + 1);
    else if (e.key === "ArrowUp") to(i < 0 ? all.length - 1 : i - 1);
    else if (e.key === "Home") to(0);
    else if (e.key === "End") to(all.length - 1);
    else if (e.key === "ArrowLeft" || e.key === "Escape") backToParent();
    else if (e.key === "Tab") close();
    else if ((e.key === "Enter" || e.key === " ") && i >= 0) choose(itemAt(all[i].dataset.path), { keyboard: true });
    else return;
    e.preventDefault();
    e.stopPropagation();
  };

  const button = (it, path, { hover = null } = {}) => {
    const radio = typeof it.checked === "boolean";
    const why = it.disabled && it.reason ? `${uid}-${path}` : undefined;
    return (
      <button key={it.id} type="button" role={radio ? "menuitemradio" : "menuitem"} tabIndex={-1} data-path={path}
              aria-checked={radio ? String(it.checked) : undefined}
              className={"ovm-item" + (it.danger ? " danger" : "") + (it.disabled ? " off" : "") + (radio ? " row-menu-radio" : "")
                + (radio && it.checked ? " on" : "")}
              aria-disabled={it.disabled ? "true" : undefined}
              aria-describedby={why}
              onPointerEnter={hover}
              onClick={() => choose(it)}>
        {radio && <span className="row-menu-tick" aria-hidden="true">{it.checked ? "✓" : ""}</span>}
        {it.label}
        {why && <span id={why} className="row-menu-why">{it.reason}</span>}
      </button>
    );
  };

  return createPortal(
    <div ref={ref} className="ovm-menu row-menu" role="menu" aria-label={label} tabIndex={-1}
         style={pos ? { left: pos.left, top: pos.top } : { left: at.x, top: at.y, visibility: "hidden" }}
         onKeyDown={onKeyDown} onContextMenu={(e) => e.preventDefault()}>
      {items.map((it, i) => {
        if (!it.items) return button(it, String(i), { hover: phone ? null : () => setSub(null) });
        const open = sub?.id === it.id;
        return (
          <Fragment key={it.id}>
            <button type="button" role="menuitem" tabIndex={-1} data-path={String(i)} data-sub={it.id}
                    className={"ovm-item row-menu-parent" + (open ? " open" : "") + (phone ? " inline" : "")}
                    aria-haspopup="menu" aria-expanded={open}
                    onPointerEnter={phone ? undefined : () => setSub((s) => (s?.id === it.id ? s : { id: it.id, focus: false }))}
                    onClick={() => choose(it)}>
              {it.label}
            </button>
            {open && phone && (
              <div role="group" aria-label={it.label} data-group={it.id} className="row-menu-inline">
                {it.items.map((s, j) => button(s, `${i}.${j}`))}
              </div>
            )}
            {open && !phone && (
              <div ref={subRef} className="ovm-menu row-menu row-submenu" role="menu" aria-label={it.label} tabIndex={-1}
                   style={subPos ? { left: subPos.left, top: subPos.top } : { left: 0, top: 0, visibility: "hidden" }}
                   onKeyDown={onSubKey}>
                {it.items.map((s, j) => button(s, `${i}.${j}`))}
              </div>
            )}
          </Fragment>
        );
      })}
    </div>,
    portalHost(),
  );
}
