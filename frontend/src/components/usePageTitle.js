import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { titleFor } from "../pageTitle.js";

// The record a detail page shows, so its tab title can lead with its name.
// One at a time: the page on screen.
let named = null; // { path, name }

// Set the tab title for ``pathname`` (AppShell calls this on every
// navigation; a detail page's name wins while it's on screen).
export function applyPageTitle(pathname) {
  if (typeof document === "undefined") return;
  document.title = titleFor(pathname, named && named.path === pathname ? named.name : null);
}

// A detail page: lead its tab title with the record's name once loaded
// ("Feed pump train · RBDs · Reliafy").
export default function usePageTitle(name) {
  const { pathname } = useLocation();
  useEffect(() => {
    if (!name) return undefined;
    const mine = { path: pathname, name: String(name) };
    named = mine;
    applyPageTitle(pathname);
    return () => {
      if (named === mine) named = null;
    };
  }, [name, pathname]);
}

// The same, as an element to drop beside a page's header (no hook-order
// worries on pages that return early while loading).
export function PageTitle({ name }) {
  usePageTitle(name);
  return null;
}
