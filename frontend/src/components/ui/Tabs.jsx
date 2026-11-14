// The shared tab row (#301). On a narrow screen the row scrolls sideways: the
// hidden side fades out with a chevron that scrolls it, and the active tab is
// kept in view. Renders the .tabs / .tab markup the app already styles.
//
// It follows the ARIA tab pattern: only the active tab is in the Tab order
// (a roving tabindex), and the arrow keys (Home, End) move to and open the
// next tab. With ``idPrefix`` each tab gets an id and names the panel it
// controls (``${idPrefix}-panel``), so the caller's panel can point back.
//
//   tabs      [{ id, label, title?, wt? }] (wt: a guided walkthrough's anchor)
//   value     the active tab's id
//   onChange  (id) => void
//   label     accessible name of the row
//   className classes for the row's frame (e.g. "rbd-tabs")
//   idPrefix  ids for the tabs and their panel (optional)
//   wholeTabs on a row that scrolls, the active tab's reveal starts on a whole
//            tab (no tail of one cut by the chevron); off unless asked for
//   overflow  instead of scrolling, the tabs that don't fit fold from the right
//            into a last "⋯ N" tab that lists them (priority+; OverflowTabs below)
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import ScrollCue from "./ScrollCue.jsx";
import RowMenu from "../RowMenu.jsx";
import { nextTabIndex } from "../../modelFrame.js";
import { fitTabs, nextStop } from "./tabsFit.js";

export const tabId = (prefix, id) => `${prefix}-tab-${id}`;
export const panelId = (prefix) => `${prefix}-panel`;

export default function Tabs({ tabs, value, onChange, label, className, idPrefix, wholeTabs = false, overflow = false }) {
  if (overflow) return <OverflowTabs tabs={tabs} value={value} onChange={onChange} label={label} className={className} idPrefix={idPrefix} />;
  return <ScrollTabs tabs={tabs} value={value} onChange={onChange} label={label} className={className} idPrefix={idPrefix} wholeTabs={wholeTabs} />;
}

function ScrollTabs({ tabs, value, onChange, label, className, idPrefix, wholeTabs }) {
  const refs = useRef({});
  // The tab in the Tab order: the active one, or the first when none is.
  const focusable = tabs.some((t) => t.id === value) ? value : tabs[0]?.id;
  const onKeyDown = (e, i) => {
    const next = nextTabIndex(e.key, i, tabs.length);
    if (next == null) return;
    e.preventDefault();
    const t = tabs[next];
    onChange(t.id);
    refs.current[t.id]?.focus();
  };
  return (
    <ScrollCue
      wrapClassName={"tabs-strip" + (className ? " " + className : "")}
      className="tabs"
      role="tablist"
      aria-label={label}
      arrows
      arrowLabel="Scroll tabs"
      reveal=".tab.active"
      revealKey={value}
      wholeItems={wholeTabs ? ".tab" : undefined}
    >
      {tabs.map((t, i) => (
        <button
          key={t.id}
          ref={(el) => { refs.current[t.id] = el; }}
          type="button"
          role="tab"
          id={idPrefix ? tabId(idPrefix, t.id) : undefined}
          aria-controls={idPrefix ? panelId(idPrefix) : undefined}
          aria-selected={value === t.id}
          tabIndex={focusable === t.id ? 0 : -1}
          className={"tab" + (value === t.id ? " active" : "")}
          title={t.title}
          data-wt={t.wt}
          onClick={() => onChange(t.id)}
          onKeyDown={(e) => onKeyDown(e, i)}
        >
          {t.label}
        </button>
      ))}
    </ScrollCue>
  );
}

// Tabs with overflow (priority+). One flat row; the tabs that don't fit the row's width fold,
// from the right, into a last "⋯ N" tab (N: how many) that opens a menu of them (RowMenu, the
// ContextMenu look). The selected tab never folds: picked from "⋯", it takes the last slot that
// shows and the tab it displaces goes into "⋯". Recomputed when the row or the tabs' widths
// change (a ResizeObserver; fonts loading change the widths too). Nothing scrolls sideways.
//
// The widths come from a copy of the row drawn out of sight (aria-hidden, nothing focusable), each tab drawn
// as the active one (600 weight, the widest), so the fit never depends on which tab is picked.
//
// ARIA: the row is a tablist. The tabs shown are its tabs (roving tabindex on the selected one);
// "⋯ N" is a tab too (aria-selected false, aria-haspopup="menu", aria-expanded, named "N more
// tabs: …"), so ← → reach it with the others. The folded tabs aren't in the tablist: the menu's
// items stand in for them (role menuitem, each named as its tab); choosing one selects that tab,
// which then shows in the row and takes the focus. The panel's aria-labelledby always names a
// tab that's shown, since the selected tab never folds.
//
// Keyboard: ← → Home End move along the row, "⋯" included; on a tab they also select it (as the
// scrolling row), on "⋯" they only focus it. Enter, Space or ↓ on "⋯" opens its menu; ↑ ↓ Home
// End move in it, Enter chooses, Esc closes it with the focus back on "⋯".
const MORE = "more";

function OverflowTabs({ tabs, value, onChange, label, className, idPrefix }) {
  const refs = useRef({});
  const stripRef = useRef(null);
  const measureRef = useRef(null);
  const [size, setSize] = useState(null); // {avail, widths, more, gap}
  const [open, setOpen] = useState(null); // {x, y}: the menu's corner
  const [focusId, setFocusId] = useState(null);
  const focusNext = useRef(null);
  const key = tabs.map((t) => `${t.id}:${t.label}`).join("|");

  useLayoutEffect(() => {
    const strip = stripRef.current;
    const meas = measureRef.current;
    if (!strip || !meas) return undefined;
    const measure = () => {
      const kids = [...meas.children];
      const w = (el) => el.getBoundingClientRect().width;
      const gap = parseFloat(getComputedStyle(meas).columnGap) || 0;
      const next = { avail: strip.clientWidth, widths: kids.slice(0, -1).map(w), more: w(kids.at(-1)), gap };
      setSize((s) => (s && s.avail === next.avail && s.more === next.more && s.gap === next.gap
        && s.widths.length === next.widths.length && s.widths.every((x, i) => x === next.widths[i]) ? s : next));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(strip);
    ro.observe(meas);
    return () => ro.disconnect();
  }, [key]);

  const sel = tabs.findIndex((t) => t.id === value);
  const fit = size && size.widths.length === tabs.length
    ? fitTabs(size.widths, size.avail, size.more, sel, size.gap)
    : { shown: tabs.map((_, i) => i), hidden: [] };
  const shown = fit.shown.map((i) => tabs[i]);
  const hidden = fit.hidden.map((i) => tabs[i]);
  const stops = [...shown.map((t) => t.id), ...(hidden.length ? [MORE] : [])];
  const tabStop = stops.includes(focusId) ? focusId : (shown.some((t) => t.id === value) ? value : shown[0]?.id);

  // A tab chosen from "⋯" takes the focus once it shows in the row.
  useEffect(() => {
    if (focusNext.current && focusNext.current === value) {
      refs.current[value]?.focus({ preventScroll: true });
      focusNext.current = null;
    }
  });

  const moreId = idPrefix ? tabId(idPrefix, MORE) : undefined;
  const openMenu = () => {
    const r = refs.current[MORE]?.getBoundingClientRect();
    if (r) setOpen({ x: r.left, y: r.bottom + 2 });
  };
  const onKeyDown = (e, i) => {
    const id = stops[i];
    if (id === MORE && (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      openMenu();
      return;
    }
    const next = nextStop(e.key, i, stops.length);
    if (next == null) return;
    e.preventDefault();
    const to = stops[next];
    setFocusId(to);
    if (to !== MORE) onChange(to);
    refs.current[to]?.focus();
  };
  const tabButton = (t, i) => (
    <button
      key={t.id}
      ref={(el) => { refs.current[t.id] = el; }}
      type="button"
      role="tab"
      id={idPrefix ? tabId(idPrefix, t.id) : undefined}
      aria-controls={idPrefix ? panelId(idPrefix) : undefined}
      aria-selected={value === t.id}
      tabIndex={tabStop === t.id ? 0 : -1}
      className={"tab" + (value === t.id ? " active" : "")}
      title={t.title}
      data-wt={t.wt}
      onFocus={() => setFocusId(t.id)}
      onClick={() => onChange(t.id)}
      onKeyDown={(e) => onKeyDown(e, i)}
    >
      {t.label}
    </button>
  );
  return (
    <div ref={stripRef} className={"tabs-strip tabs-fit" + (className ? " " + className : "")}>
      <div className="tabs" role="tablist" aria-label={label}>
        {shown.map(tabButton)}
        {hidden.length > 0 && (
          <button
            ref={(el) => { refs.current[MORE] = el; }}
            type="button"
            role="tab"
            id={moreId}
            aria-selected={false}
            aria-haspopup="menu"
            aria-expanded={!!open}
            aria-label={`${hidden.length} more tab${hidden.length === 1 ? "" : "s"}: ${hidden.map((t) => t.label).join(", ")}`}
            tabIndex={tabStop === MORE ? 0 : -1}
            className={"tab tab-more" + (open ? " open" : "")}
            title={hidden.map((t) => t.label).join(", ")}
            onFocus={() => setFocusId(MORE)}
            onClick={() => (open ? setOpen(null) : openMenu())}
            onKeyDown={(e) => onKeyDown(e, stops.length - 1)}
          >
            <span aria-hidden="true">⋯</span> {hidden.length}
          </button>
        )}
      </div>
      {/* Out of sight: every tab at its widest, and "⋯ 9", to measure the fit. */}
      <div ref={measureRef} className="tabs-measure" aria-hidden="true">
        {tabs.map((t) => <span key={t.id} className="tab active">{t.label}</span>)}
        <span className="tab tab-more">⋯ 9</span>
      </div>
      {open && (
        <RowMenu
          items={hidden.map((t) => ({ id: t.id, label: t.label }))}
          at={open}
          label="More tabs"
          anchorId={moreId}
          onClose={() => { setOpen(null); refs.current[MORE]?.focus({ preventScroll: true }); }}
          onChoose={(id) => { focusNext.current = id; setFocusId(id); onChange(id); }}
        />
      )}
    </div>
  );
}
