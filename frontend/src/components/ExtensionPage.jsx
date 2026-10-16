import * as React from "react";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import * as ReactDOM from "react-dom";
import * as ReactDOMClient from "react-dom/client";
import { useLocation, useNavigate } from "react-router-dom";
import { apiRequest, authedFetch } from "../api.js";
import { useAuth } from "../AuthProvider.jsx";
import { asHandle, CONTEXT_VERSION, importResponse, readTokens } from "../extensions.js";
import { formatNumber, formatPercent } from "../format.js";
import { relativeTime } from "../instrument.js";
import { renderMarkdown } from "../markdown.js";
import * as plotTheme from "../plotTheme.js";
import { getWalkthrough, stepFunnel } from "../walkthroughs.js";
import Select from "./Select.jsx";
import Button from "./ui/Button.jsx";
import Card, { CardHeader } from "./ui/Card.jsx";
import Chip from "./ui/Chip.jsx";
import PageHeader from "./ui/PageHeader.jsx";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import ScrollCue from "./ui/ScrollCue.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import Switch from "./ui/Switch.jsx";
import Tabs from "./ui/Tabs.jsx";

// A page added by an optional extension (extensions.js): fetch its module with
// the user's credentials, import it, and hand it an element and a context.

const LazyPlot = lazy(() => import("./Plot.jsx"));
function Plot(props) {
  return (
    <Suspense fallback={<div className="muted-line">Loading chart…</div>}>
      <LazyPlot {...props} />
    </Suspense>
  );
}

// The shared building blocks an extension page draws with (the host's own
// components, so the page looks like the rest of the app).
const UI = {
  Button, Card, CardHeader, Chip, PageHeader, Plot, ResultDetails, ResultSummary, ScrollCue,
  SegmentedControl, Select, Switch, Tabs,
};
const LIB = { formatNumber, formatPercent, getWalkthrough, relativeTime, renderMarkdown, stepFunnel };
const REACT_DOM = { ...ReactDOM, createRoot: ReactDOMClient.createRoot, hydrateRoot: ReactDOMClient.hydrateRoot };

// Modules already imported this session, per user and URL.
const modules = new Map();

function loadModule(url, uid) {
  const key = `${uid}|${url}`;
  if (!modules.has(key)) {
    const p = authedFetch(url).then(importResponse);
    p.catch(() => modules.delete(key));
    modules.set(key, p);
  }
  return modules.get(key);
}

function buildContext(mount, { navigate, location, uid }) {
  const assetUrl = (name) =>
    `/api/extensions/${encodeURIComponent(mount.extension)}/${encodeURIComponent(mount.id)}/assets/${encodeURIComponent(name)}`;
  return {
    version: CONTEXT_VERSION,
    React,
    ReactDOM: REACT_DOM,
    api: { request: apiRequest, fetch: authedFetch },
    navigate: (to, opts) => navigate(to, opts),
    location: { pathname: location.pathname, search: location.search, hash: location.hash },
    mount: { extension: mount.extension, id: mount.id, path: mount.path, label: mount.label, title: mount.title },
    basePath: mount.path,
    theme: {
      tokens: () => readTokens(typeof window !== "undefined" ? window.getComputedStyle(document.documentElement) : null),
      plot: plotTheme,
    },
    ui: UI,
    lib: LIB,
    // A further module the page ships (served under the same access rule).
    loadAsset: (name) => loadModule(assetUrl(name), uid),
    // Any other file it ships, as a Response (authenticated).
    fetchAsset: (name) => authedFetch(assetUrl(name)),
  };
}

export default function ExtensionPage({ mount }) {
  const ref = useRef(null);
  const handle = useRef(null);
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();
  const uid = user?.uid || "";
  const [error, setError] = useState(null);
  const [ready, setReady] = useState(false);
  const latest = useRef(null);
  latest.current = { navigate, location, uid };

  useEffect(() => {
    let alive = true;
    setError(null);
    setReady(false);
    loadModule(mount.bundle, uid)
      .then((mod) => {
        if (!alive || !ref.current) return;
        if (typeof mod.mount !== "function") throw new Error("This page can't be shown.");
        handle.current = asHandle(mod.mount(ref.current, buildContext(mount, latest.current)));
        setReady(true);
      })
      .catch((e) => alive && setError(e.message || "This page didn't load."));
    return () => {
      alive = false;
      const h = handle.current;
      handle.current = null;
      try {
        h?.unmount?.();
      } catch {
        // A page that fails to clean up mustn't break navigation.
      }
    };
    // Mount once per page and user; URL changes go to update() below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mount.bundle, uid]);

  useEffect(() => {
    if (ready) handle.current?.update?.(buildContext(mount, latest.current));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname, location.search, location.hash, ready]);

  useEffect(() => {
    const before = document.title;
    document.title = `${mount.title || mount.label} — Reliafy`;
    return () => {
      document.title = before;
    };
  }, [mount.title, mount.label]);

  return (
    <>
      {error && <div className="card empty">{error}</div>}
      {!ready && !error && <div className="card empty view-loading">Loading…</div>}
      <div ref={ref} className="extension-page" data-extension={`${mount.extension}/${mount.id}`} />
    </>
  );
}
