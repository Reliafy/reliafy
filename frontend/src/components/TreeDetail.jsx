import { Suspense, forwardRef, lazy, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { getMaintenancePosition } from "../api.js";
import Tabs from "./ui/Tabs.jsx";
import FailureReportsPanel from "./FailureReportsPanel.jsx";
import SignalsPanel from "./SignalsPanel.jsx";
import OverflowMenu from "./OverflowMenu.jsx";
import RowMenu from "./RowMenu.jsx";
import { ancestorsOf, structuralRow } from "../assetTree.js";
import {
  EXPLORER_GROUPED_TABS, branchOf, classesInBranch, groupLabel, groupedTabsFor, groupedView, hasTabBar, isDesignRow, isPlainGroup, isProductRow, rowKind,
  shownTab, tabsFor, viewTarget,
} from "../explorerTabs.js";
import GroupedTabs from "./ui/GroupedTabs.jsx";
import { useAppConfig } from "../ConfigProvider.jsx";
import TreeSummary from "./TreeSummary.jsx";
import ProductSummary, { ProductPartsList } from "./ProductSummary.jsx";
import "./TreeSummary.css";
import { createRecent } from "../recentCache.js";
import { withFullPage } from "../panelMenu.js";

// The Parts and stock and Classes tabs' bodies (the pages they were, with their
// charts): loaded when one of the tabs is first opened.
const PartsPanel = lazy(() => import("../views/MaintenanceLists.jsx").then((m) => ({ default: m.PartsPanel })));
// The LSA tab's body (what each task needs, and the work packages: tasks done together on one visit).
const LsaPanel = lazy(() => import("./LsaPanel.jsx"));
const ClassFleet = lazy(() => import("./ClassFleet.jsx"));
const PositionRisk = lazy(() => import("./PositionRisk.jsx"));
const ClassesPanel = lazy(() => import("../views/MaintenanceLists.jsx").then((m) => ({ default: m.ClassesPanel })));

// The panel beside the asset tree: what the selected row is, in a glance. A
// position: where it sits, what's fitted, its status in words, its work
// (overdue first), its class and location, and what's directly inside it. An
// item: its serial, class, make and model, and where it is (the position it's
// fitted to, or the place it's kept). "Open the full page" (in the heading's
// "…" menu) goes to the row's own page, where it's edited (an item's history
// and fitments are there).
//
// The panel has tabs (explorerTabs.js): Summary (the above) for every row,
// RCM for a position, and Failure reports (FailureReportsPanel: what has
// failed at the row and below it, and what was done about it; `reports` is
// the page's: the report open, how to open one, file one, and the tree read
// again); Measurements (drawn by the Explorer as a tree-table: every measuring point at the row
// and inside it, ?point= its details); Parts and stock and Classes (the row's branch, or everything with
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
export function rememberChange(id, version, change) {
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
export function usePosition(id, version) {
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

function Summary({ row: picked, display: shownIn, structure, today, onSelect, version, actions }) {
  // By Classes, a position's facts and counts come from its place in the Positions tree.
  const { row, display } = structuralRow(structure, picked, shownIn);
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

// The panel's heading, the same on every tab: two slim rows. The first: the
// way up (and the last thing done) as small text over the row's name, its
// kind, tag and checks, with two controls on the right, the same on every tab:
// the "…" menu (HeaderMenu: the tab's own items, then Open the full page) and
// Full screen. Adding, pinning and the rest of a row's changes are in the
// tree's row menu (right-click, its ⋯, Shift+F10), not here. The second row,
// under the way up and the name: the tabs. On a wide screen the two rows sit
// beside the tree's own two over the tree, on every tab (TreePane's head and
// headTabs); on a phone they head the panel.
//
// With a branch of the tree pinned, the way up still shows the whole path:
// `above(key)` says which crumbs are above the pinned row (a click there moves
// the pin up, `onCrumb` decides). `menu`: the tab's items (panelMenu.js).
// `popover`: something the menu opened that hangs under the controls (the
// RCM's column chooser).
// `heading`: the name's heading level, 1 on the Explorer's own page; 2 where
// the tree sits inside a page with its own h1 (a product's).
export function SlimHeader({
  display, row, onSelect, onCrumb = onSelect, above = null, fullScreenButton, headingRef, meta, menu = [], popover = null, message,
  heading = 1,
}) {
  const crumbs = ancestorsOf(display, row.key).map((k) => ({ key: k, label: display.rows.get(k).ref.name, above: !!above?.(k) }));
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
        <HeaderMenu items={withFullPage(menu, fullPagePath(row))} />
        {fullScreenButton}
        {popover}
      </div>
    </div>
  );
}

// The heading's "…": the tab's items (a link for Open the full page), greyed
// where a row has none (a group), so the heading looks the same on every row.
export function HeaderMenu({ items }) {
  // Grouped items (a submenu: `items`, or a separator) open the tree's row menu, two levels.
  if (items.some((it) => it.items || it.separator)) return <GroupedHeaderMenu items={items} />;
  return (
    <OverflowMenu triggerClass="tp-icon-btn" disabled={!items.length} title={items.length ? "More actions" : "Nothing more for this row"}>
      {items.map((it) => (it.to ? (
        <Link key={it.id} className="ovm-item" to={it.to}>{it.label}</Link>
      ) : (
        <button key={it.id} type="button" className="ovm-item" disabled={!!it.disabled} title={it.title || undefined}
                onClick={it.onSelect}>{it.label}</button>
      )))}
    </OverflowMenu>
  );
}

// The heading's "…" with groups (the Modelling tab's: Life model ›, RBD ›, Prediction ›): the
// row menu's two levels, opened under the button; → opens a group, at 400 px it opens in place.
function GroupedHeaderMenu({ items }) {
  const [at, setAt] = useState(null);
  const btn = useRef(null);
  const navigate = useNavigate();
  const find = (list, id) => {
    for (const it of list) {
      if (it.id === id) return it;
      const got = it.items && find(it.items, id);
      if (got) return got;
    }
    return null;
  };
  // No line at either end (a group with nothing after it on a phone).
  const trim = (list) => list.filter((it, i) => !(it.separator && (i === 0 || i === list.length - 1)));
  const strip = (list) => trim(list).map((it) => (it.separator ? it : {
    id: it.id, label: it.label, disabled: !!it.disabled, reason: it.disabled ? it.title : undefined,
    ...(it.items ? { items: strip(it.items) } : {}),
  }));
  return (
    <div className="ovm">
      <button ref={btn} type="button" className="tp-icon-btn ovm-trigger" aria-label="More actions" aria-haspopup="menu"
              aria-expanded={!!at} title="More actions"
              onClick={() => {
                if (at) { setAt(null); return; }
                const r = btn.current.getBoundingClientRect();
                setAt({ x: Math.max(8, r.right - 260), y: r.bottom + 4 });
              }}>
        <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
          <circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" />
        </svg>
      </button>
      {at && (
        <RowMenu items={strip(items)} at={at} label="More actions"
                 onClose={() => { setAt(null); btn.current?.focus(); }}
                 onChoose={(id) => {
                   const it = find(items, id);
                   if (it?.to) navigate(it.to);
                   else it?.onSelect?.();
                 }} />
      )}
    </div>
  );
}

// The panel's tabs (Summary, RCM), under its heading. A row with Summary alone has none; an item
// class has its one tab, Condition monitoring (a position on an asset has that tab too).
//
// With EXPLORER_GROUPED_TABS (explorerTabs.js), the grouped row instead (GroupedTabs: Summary |
// Analysis ▾ | Operation ▾ | History ▾); `onTab(tab, {view})` then also names the ?mview= of the
// inner view picked (Packages, Forecast), null for none. `idPrefix`: "td" for the panel's own row.
export function HeaderTabs({ row, tab, onTab, label = "What to show for this row", idPrefix = "td", className = "tt-tabs" }) {
  const { menu_preview: preview } = useAppConfig();
  const [params] = useSearchParams();
  if (!hasTabBar(row)) return null;
  if (EXPLORER_GROUPED_TABS) {
    const opts = { preview: !!preview };
    const groups = groupedTabsFor(row, opts);
    const at = groupedView(tab, row, { ...opts, mview: params.get("mview") });
    return (
      <GroupedTabs groups={groups} at={at} label={label} idPrefix={idPrefix} className={className + " tt-gtabs"}
                   labelOf={groupLabel} isPlain={isPlainGroup}
                   onChoose={(entry, view) => {
                     const to = viewTarget(row, entry, view, opts);
                     if (to) onTab(to.tab, { view: to.mview });
                   }} />
    );
  }
  return <Tabs tabs={tabsFor(row)} value={shownTab(tab, row)} onChange={onTab} label={label} idPrefix={idPrefix} className={className} wholeTabs />;
}

// The id of the tab that names the panel (its aria-labelledby): the tab shown, or with grouped
// tabs the group it's in.
function panelLabelId(tab, row, mview, preview) {
  if (!EXPLORER_GROUPED_TABS) return `td-tab-${shownTab(tab, row)}`;
  return `td-tab-${groupedView(tab, row, { mview, preview })?.group || "summary"}`;
}

// `menu`: the "…" items the tab's body gave (through `onMenu`, panelMenu.js),
// for the heading here on a phone; on a wide screen the page draws the heading.
const TreeDetail = forwardRef(function TreeDetail({
  display, row, today, onSelect, onCrumb, above, back, version, empty, tab, onTab, fullScreenButton, headless = false, actions = [],
  reports = null, heading = 1, menu = [], onMenu = null, within = null, structure = null,
}, headingRef) {
  const { menu_preview: preview } = useAppConfig();
  const [params] = useSearchParams();
  if (!row) return <div className="td">{back}{empty}</div>;
  const tabbed = hasTabBar(row);
  const shown = shownTab(tab, row);
  const labelledBy = tabbed ? panelLabelId(tab, row, params.get("mview"), !!preview) : undefined;
  return (
    <div className="td">
      {back}
      {!headless && (
        <div className="td-head">
          <SlimHeader display={display} row={row} onSelect={onSelect} onCrumb={onCrumb || onSelect} above={above}
                      fullScreenButton={fullScreenButton} headingRef={headingRef} heading={heading} menu={menu}
                      meta={rowKind(row) ? <span className="tt-kind">{rowKind(row)}</span> : null} />
          <HeaderTabs row={row} tab={tab} onTab={onTab} />
        </div>
      )}
      <div className="td-body" role={tabbed ? "tabpanel" : undefined} id={tabbed ? "td-panel" : undefined}
           aria-labelledby={labelledBy}>
        {shown === "reports" && reports
          ? <FailureReportsPanel row={row} display={display} today={today} version={version} reports={reports} onMenu={onMenu} />
          // The Measurements tab is the tree-table (AssetExplorer, MeasurementTable.jsx), not a panel.
          // So is the Modelling tab (AssetExplorer, ModelTable.jsx).
          : shown === "measurements" || shown === "models"
          ? null
          : shown === "lsa"
          ? <Suspense fallback={loading}><LsaPanel row={row} today={today} onMenu={onMenu} /></Suspense>
          // The Maintenance tab: the same table of tasks, every task on the row (LsaPanel's "maintenance" variant).
          : shown === "maintenance"
          ? <Suspense fallback={loading}><LsaPanel key="maintenance" row={row} today={today} onMenu={onMenu} variant="maintenance" /></Suspense>
          : shown === "signals"
          ? <SignalsPanel row={row} onMenu={onMenu} />
          : shown === "parts"
          ? <PartsTab row={row} display={display} />
          : shown === "classes"
          ? <ClassesTab row={row} display={display} />
          // The Condition monitoring tab. A position's (any arrangement): its own risk now, in words
          // then its two charts, or why there is none and how to get one (the Modelling tab).
          : shown === "condition" && row.type === "pos"
          ? <Suspense fallback={loading}><PositionRisk positionId={row.key} version={version} detail onModelling={() => onTab("models")} /></Suspense>
          // By Classes, a class's row: the fleet (every position under it, with risk now; `within`:
          // the one asset on show, its top position's id: only the positions inside it).
          : shown === "condition"
          ? <Suspense fallback={loading}><ClassFleet row={row} version={version} onSelect={onSelect} within={within} /></Suspense>
          : <Summary row={row} display={display} structure={structure} today={today} onSelect={onSelect} version={version} actions={actions} />}
      </div>
    </div>
  );
});

export default TreeDetail;
