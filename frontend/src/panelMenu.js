import { useEffect, useRef } from "react";

// The Explorer panel heading's "…" menu (More actions). The heading has two
// controls on every tab, this menu and Full screen; what a tab offers beyond
// its rows' own menus goes in here (the RCM's Import worksheet…, Export CSV,
// Columns…; the Measurements tab's Add a measuring point…), and "Open the
// full page" last, for every row that has one.
//
// An item: {id, label, onSelect?, to?, disabled?, title?}. `to` makes it a
// link (Open the full page); `title` says why it's greyed.
//
// A tab's body (the failure reports, the measurements, the signals) gives its
// items to the page through `onMenu` (usePanelMenu); the RCM and FME(C)A
// tabs' items are the page's own.

// What a menu says (not what it does): its items change only when this does,
// so a body's fresh closures each render don't hand the page a new menu.
export function menuKey(items) {
  return (items || []).filter(Boolean)
    .map((i) => [i.id, i.label, i.to || "", i.disabled ? 1 : 0, i.title || ""].join("\u0001"))
    .join("\u0002");
}

// The tab's items with "Open the full page" last (where the row has a page).
export function withFullPage(items, to) {
  const out = (items || []).filter(Boolean);
  return to ? [...out, { id: "open-full", label: "Open the full page", to }] : out;
}

// A tab's body gives the page its items (null when it goes). Each item's
// onSelect runs the body's latest one, so the page re-renders only when what
// the menu says changes (menuKey). `onMenu` must be stable (a state setter).
export function usePanelMenu(onMenu, items) {
  const latest = useRef(items);
  latest.current = items;
  const key = menuKey(items);
  useEffect(() => {
    if (!onMenu) return undefined;
    onMenu((latest.current || []).filter(Boolean).map((it) => ({
      ...it,
      onSelect: it.onSelect ? () => latest.current?.find((x) => x?.id === it.id)?.onSelect?.() : undefined,
    })));
    return () => onMenu(null);
  }, [onMenu, key]);
}
