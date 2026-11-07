import { Suspense, forwardRef, lazy, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { getMaintenancePosition } from "../api.js";
import Tabs from "./ui/Tabs.jsx";
import FailureReportsPanel from "./FailureReportsPanel.jsx";
import SignalsPanel from "./SignalsPanel.jsx";
import { PinIcon } from "./OutlineBits.jsx";
import { ancestorsOf } from "../assetTree.js";
import { branchOf, classesInBranch, isDesignRow, isProductRow, rowKind, shownTab, tabsFor } from "../explorerTabs.js";
import TreeSummary from "./TreeSummary.jsx";
import ProductSummary, { ProductPartsList } from "./ProductSummary.jsx";
import "./TreeSummary.css";
import { createRecent } from "../recentCache.js";

// The Parts and stock and Classes tabs' bodies (the pages they were, with their
// charts): loaded when one of the tabs is first opened.
const PartsPanel = lazy(() => import("../views/MaintenanceLists.jsx").then((m) => ({ default: m.PartsPanel })));
const ClassesPanel = lazy(() => import("../views/MaintenanceLists.jsx").then((m) => ({ default: m.ClassesPanel })));

// The panel beside the asset tree: what the selected row is, in a glance. A
// position: where it sits, what's fitted, its status in words, its work
// (overdue first), its class and location, and what's directly inside it. An
// item: its serial, class, make and model, and where it is (the position it's
// fitted to, or the place it's kept). "Open the full page" goes to the row's
// own page, where it's edited (an item's history and fitments are there).
//
// The panel has tabs (explorerTabs.js): Summary (the above) for every row,
// RCM for a position, and Failure reports (FailureReportsPanel: what has
// failed at the row and below it, and what was done about it; `reports` is
// the page's: the report open, how to open one, file one, and the tree read
// again); Parts and stock and Classes (the row's branch, or everything with
// ?scope=all; ?class= opens a class, ?show=structure the parts as structures).
// A product's design has no maintenance: its positions' Summary leaves out
// what's fitted, located, due and measured, and the product's own row shows
// the product (ProductSummary). On a wide screen the heading and the tabs (SlimHeader and
// HeaderTabs) sit in the two slim rows over the tree on both tabs, so they stay
// put when the tab changes; the panel itself is then `headless`. On the RCM tab
// the tree and the RCM are one table (TreePane with its columns).

export function fullPagePath(r) {
  if (r.type === "pos") return `/asset-register/positions/${r.key}`;
  if (r.type === "loc") return `/asset-register/locations/${r.key}`;
  if (r.type === "item") return `/asset-register/items/${r.key}`;
  return null;
}

// What a position page fetch gives the panel (tasks, work orders, since when
// fitted): fetched a moment after the selection settles, so arrowing down the
// tree doesn't fetch every row on the way. The last few are kept (until the
// tree is read again), so coming back to a row, or to the Summary tab, shows
// them at once instead of "Loading…" while they're fetched again.
const SEEN = createRecent(30);
const seenKey = (id, version) => `${version}:${id}`;
// Each time the tree is read again (a change, or the page opened afresh).
export function forgetPositions() {
  SEEN.clear();
}
function fetchPosition(id, version) {
  return getMaintenancePosition(id).then((data) => {
    const got = { id, data, error: null };
    SEEN.set(seenKey(id, version), got);
    return got;
  });
}
// A change saved from the panel, kept in its copy too (so switching tabs and
// back shows it, not the text from before).
function rememberChange(id, version, change) {
  const key = seenKey(id, version);
  const seen = SEEN.get(key);
  if (seen?.data) SEEN.set(key, { ...seen, data: { ...seen.data, ...change } });
}
// Read ahead (the RCM tab, for the position picked), so switching to Summary
// shows its work at once.
export function prefetchPosition(id, version) {
  if (!id || SEEN.has(seenKey(id, version))) return;
  fetchPosition(id, version).catch(() => {});
}
function usePosition(id, version) {
  const [state, setState] = useState(() => SEEN.get(seenKey(id, version)) || { id: null, data: null, error: null });
  useEffect(() => {
    if (!id) return undefined;
    const key = seenKey(id, version);
    const seen = SEEN.get(key);
    if (seen) {
      setState(seen);
      return undefined;
    }
    let live = true;
    const t = setTimeout(() => {
      fetchPosition(id, version)
        .then((got) => live && setState(got))
        .catch((e) => live && setState({ id, data: null, error: e.message }));
    }, 180);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [id, version]);
  if (state.id === id) return state;
  return SEEN.get(seenKey(id, version)) || { id, data: null, error: null };
}

function Summary({ row, display, today, onSelect, version, actions }) {
  const position = usePosition(row.type === "pos" ? row.key : null, version);
  const props = {
    row, display, today, onSelect, position, fullPage: fullPagePath(row), actions,
    onContextSaved: (text) => rememberChange(row.key, version, { operating_context: text }),
  };
  if (isProductRow(row)) return <ProductSummary {...props} version={version} />;
  return <TreeSummary {...props} design={isDesignRow(row)} />;
}

// ?scope=all (Show all …), ?show= and ?class=: the Parts and stock and
// Classes tabs' own, kept in the address so a link (and the old pages'
// addresses, redirects.js) opens them as they were.
// The address changes in place, keeping its state (on a phone, the panel open
// as its own screen).
function useTabQuery() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const set = (key, value) => {
    const next = new URLSearchParams(location.search);
    if (value) next.set(key, value);
    else next.delete(key);
    navigate(`${location.pathname}?${next}${location.hash}`, { replace: true, state: location.state });
  };
  return {
    all: params.get("scope") === "all", setAll: (on) => set("scope", on ? "all" : null),
    show: params.get("show") || "list", setShow: (v) => set("show", v === "list" ? null : v),
    open: params.get("class") || null, setOpen: (name) => set("class", name),
  };
}

const loading = <div className="card empty">Loading…</div>;

function PartsTab({ row, display }) {
  const q = useTabQuery();
  const branch = useMemo(() => branchOf(display, row.key), [display, row.key]);
  const design = isDesignRow(row);
  return (
    <Suspense fallback={loading}>
      {isProductRow(row) && <ProductPartsList productId={row.key} />}
      <PartsPanel branch={branch} scopeName={row.ref.name} design={design} all={q.all} onAll={q.setAll}
                  show={q.show} onShow={q.setShow} />
    </Suspense>
  );
}

function ClassesTab({ row, display }) {
  const q = useTabQuery();
  const here = useMemo(() => classesInBranch(display, branchOf(display, row.key)), [display, row.key]);
  return (
    <Suspense fallback={loading}>
      <ClassesPanel here={here} scopeName={row.ref.name} all={q.all} onAll={q.setAll} open={q.open} onOpen={q.setOpen} />
    </Suspense>
  );
}

// The panel's heading, the same on both tabs: two slim rows. The first: the
// way up (and the last thing done) as small text over the row's name, its
// kind, tag and checks, with the actions on the right; the second, under the
// way up and the name: the tabs. On a wide screen the two rows sit beside the
// tree's own two over the tree, on both tabs (TreePane's head and headTabs);
// on a phone they head the panel.
//
// With a branch of the tree pinned, the way up still shows the whole path:
// `above(key)` says which crumbs are above the pinned row (a click there moves
// the pin up, `onCrumb` decides). `pin` ({on, onClick}): the pin button for
// the row (pinned now when `on`), or null where it can't be pinned.
// `heading`: the name's heading level, 1 on the Explorer's own page; 2 where
// the tree sits inside a page with its own h1 (a product's).
export function SlimHeader({
  display, row, onSelect, onCrumb = onSelect, above = null, pin = null, fullScreenButton, headingRef, meta, actions, message,
  primaryOpen = false, heading = 1,
}) {
  const crumbs = ancestorsOf(display, row.key).map((k) => ({ key: k, label: display.rows.get(k).ref.name, above: !!above?.(k) }));
  const full = fullPagePath(row);
  const p = row.ref;
  const H = heading === 2 ? "h2" : "h1";
  return (
    <div className="tt-bar-head">
      <div className="tt-name">
        {(crumbs.length > 0 || message) && (
          <div className="tt-sub">
            {crumbs.length > 0 && (
              <nav className="crumb tt-crumb" aria-label="Breadcrumb">
                {crumbs.map((c, i) => (
                  <span key={c.key}>
                    {i > 0 && <span className="crumb-sep" aria-hidden="true"> / </span>}
                    <button type="button" className={"crumb-link" + (c.above ? " crumb-above" : "")}
                            title={c.above ? `${c.label}: pin this branch instead` : c.label} onClick={() => onCrumb(c.key)}>{c.label}</button>
                  </span>
                ))}
              </nav>
            )}
            {message}
          </div>
        )}
        <div className="tt-name-row">
          <H className="tt-h1"><span ref={headingRef} tabIndex={-1} className="td-title">{p.name || "(no name)"}</span></H>
          {p.tag && <code className="tt-tag">{p.tag}</code>}
          {meta}
        </div>
      </div>
      <div className="tt-actions">
        {actions}
        {pin && (
          <button type="button" className={"secondary sm tt-pin" + (pin.on ? " on" : "")} aria-pressed={pin.on}
                  aria-label="Pin this branch"
                  title={pin.on ? "Pinned: show the whole tree again" : "Pin this branch: show only it and what's inside it"}
                  onClick={pin.onClick}>
            <PinIcon size={16} />
          </button>
        )}
        {fullScreenButton}
        {full && <Link className={"td-open" + (primaryOpen ? " primary" : "")} to={full}>Open the full page</Link>}
      </div>
    </div>
  );
}

// The panel's tabs (Summary, RCM), under its heading.
export function HeaderTabs({ row, tab, onTab }) {
  const tabs = tabsFor(row);
  if (tabs.length < 2) return null;
  return <Tabs tabs={tabs} value={shownTab(tab, row)} onChange={onTab} label="What to show for this row" idPrefix="td" className="tt-tabs" wholeTabs />;
}

const TreeDetail = forwardRef(function TreeDetail({
  display, row, today, onSelect, onCrumb, above, pin, back, version, empty, tab, onTab, fullScreenButton, headless = false, actions = [],
  reports = null, heading = 1,
}, headingRef) {
  if (!row) return <div className="td">{back}{empty}</div>;
  const tabs = tabsFor(row);
  const shown = shownTab(tab, row);
  return (
    <div className="td">
      {back}
      {!headless && (
        <div className="td-head">
          <SlimHeader display={display} row={row} onSelect={onSelect} onCrumb={onCrumb || onSelect} above={above} pin={pin}
                      fullScreenButton={fullScreenButton} headingRef={headingRef} heading={heading}
                      meta={rowKind(row) ? <span className="tt-kind">{rowKind(row)}</span> : null} primaryOpen />
          <HeaderTabs row={row} tab={tab} onTab={onTab} />
        </div>
      )}
      <div className="td-body" role={tabs.length > 1 ? "tabpanel" : undefined} id={tabs.length > 1 ? "td-panel" : undefined}
           aria-labelledby={tabs.length > 1 ? `td-tab-${shown}` : undefined}>
        {shown === "reports" && reports
          ? (reports?.rollup ? reports.rollup(row) : <FailureReportsPanel row={row} display={display} today={today} version={version} reports={reports} />)
          : shown === "signals"
          ? <SignalsPanel row={row} />
          : shown === "parts"
          ? <PartsTab row={row} display={display} />
          : shown === "classes"
          ? <ClassesTab row={row} display={display} />
          : <Summary row={row} display={display} today={today} onSelect={onSelect} version={version} actions={actions} />}
      </div>
    </div>
  );
});

export default TreeDetail;
