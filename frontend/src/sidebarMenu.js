// How the sidebar opens and closes (pure: no React, so the tests can hold it).
//
// An entry with sub-pages (a group such as Modelling, or an entry with
// children such as Models) is a toggle: clicking it opens or closes its list
// in place, without navigating, on desktop and phone alike. Its sub-pages are
// links: exactly what navigation.js lists (an entry's own landing page, such
// as /models, isn't added: it's reached from breadcrumbs and links; the one
// exception is an entry with a `landingLabel`, see subItems). Entries
// with nothing under them for this user stay plain links to their landing.
// On the collapsed rail every entry is a link to where it opens.
//
// The entry the current page belongs to, and its ancestors, start open;
// others start closed; opening one never closes another. What's open is kept
// for the session (sessionStorage, by the Sidebar).
import { activeTrail } from "./navigation.js";

export const OPEN_STORAGE_KEY = "reliafy.sidebar.open";

// The key an entry's open state is kept under.
export const menuKey = (entry) => entry.id || entry.to;

// What an entry shows beneath it when open: a group's entries, or an entry's
// children. Nothing: the entry is a plain link. An entry with a `landingLabel`
// (Maintenance) lists its own landing page first, under that word: the entry
// itself only opens the list, and the page must stay in the menu.
export function subItems(entry) {
  if (entry.entries) return entry.entries;
  const children = entry.children || [];
  if (!entry.landingLabel || !children.length) return children;
  return [{ to: entry.to, label: entry.landingLabel, landing: true }, ...children];
}

// Whether an entry opens a list in place (a button) rather than navigating.
export const toggles = (entry) => subItems(entry).length > 0;

// The keys open on arriving at `pathname`: the top-level entry the page
// belongs to and, inside a group, its entry, each only where it toggles.
export function startOpen(entries, pathname) {
  const { top, entry } = activeTrail(entries, pathname);
  const out = [];
  if (top && toggles(top)) out.push(menuKey(top));
  if (entry && entry !== top && toggles(entry)) out.push(menuKey(entry));
  return out;
}

// `open` with `key` flipped (a new array).
export const toggleKey = (open, key) => (open.includes(key) ? open.filter((k) => k !== key) : [...open, key]);

// `open` with every one of `keys` added (the same array when nothing's new).
export function withOpen(open, keys) {
  const add = keys.filter((k) => !open.includes(k));
  return add.length ? [...open, ...add] : open;
}

// What sessionStorage held, read defensively: a list of strings, or none.
export function parseStored(raw) {
  try {
    const v = JSON.parse(raw);
    return Array.isArray(v) ? v.filter((k) => typeof k === "string") : [];
  } catch {
    return [];
  }
}

// Whether a sub-item is lit for the page (`trail`: activeTrail's answer).
// A child is lit on its own pages. A group's entry is lit on its pages that no
// child of it names (its landing page, a saved analysis's page), and, while
// it's a toggle whose list is closed, on all its pages (so the page's place
// still shows).
export function subItemLit(item, trail, isOpen = false) {
  // An entry's own landing page, listed under it: lit on the entry's pages that no child names.
  if (item.landing) return !trail.child && trail.entry?.to === item.to;
  if (item.id) return trail.entry === item && (!toggles(item) || !isOpen || !trail.child);
  return trail.child === item;
}
