// The model pages' shared frame: the header (breadcrumb, name, the answer
// line, the actions top right), one row of tabs and the tab's body filling
// the height left, so no tab scrolls the page on a desktop screen. Long
// things (tables, lists) scroll inside their own card. On a phone the page
// scrolls as usual, with the answer and the chart on the first screen.
//
// A model page uses it in two parts, so the tabs can stay with the result
// they belong to:
//
//   <ModelFrame crumbs title badges answer actions share menu id>   the page
//     <ModelTabs tabs value onChange>{the tab's body}</ModelTabs>   the result
//   </ModelFrame>
//
// and each tab's body is one of the layouts in ModelLayouts.jsx (plot and
// panel, checks grid, calculator, table and panel, numbers sheet).
//
// ``embedded``: a frame inside another page (the fit wizard's result): a
// height of its own instead of the screen's.
import { useLayoutEffect, useRef } from "react";
import PageHeader from "../ui/PageHeader.jsx";
import Tabs, { panelId, tabId } from "../ui/Tabs.jsx";
import "./ModelFrame.css";

const PHONE = "(max-width: 720px)";

// Size the frame to the window below its own top (the app bar, a banner,
// a share page's bar), so the tab body knows its height.
function useFillHeight(ref, enabled) {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!enabled || !el || typeof window === "undefined") return undefined;
    let last = "";
    const set = () => {
      if (window.matchMedia?.(PHONE).matches) {
        if (last) { el.style.removeProperty("--mf-h"); last = ""; }
        return;
      }
      const top = el.getBoundingClientRect().top + window.scrollY;
      let px = Math.max(480, Math.floor(window.innerHeight - top));
      let h = `${px}px`;
      if (h !== last) { el.style.setProperty("--mf-h", h); last = h; }
      // Padding below the frame (a share page's column) would still scroll
      // the page: take it off too.
      const over = document.documentElement.scrollHeight - window.innerHeight;
      if (over > 0 && px - over >= 480) {
        px -= over;
        h = `${px}px`;
        el.style.setProperty("--mf-h", h);
        last = h;
      }
    };
    set();
    window.addEventListener("resize", set);
    // A banner or bar above that appears later moves the frame down.
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(set) : null;
    ro?.observe(document.body);
    return () => { window.removeEventListener("resize", set); ro?.disconnect(); };
  }, [ref, enabled]);
}

// The answer line: short phrases (modelFrame.js answerParts), one line where
// it fits.
export function AnswerLine({ parts, children }) {
  const list = (parts || []).filter(Boolean);
  if (!list.length && !children) return null;
  return (
    <p className="mf-answer" aria-label="The answer">
      {list.map((p, i) => (
        <span key={i} className="mf-answer-part">
          {i > 0 && <span className="mf-sep" aria-hidden="true"> · </span>}
          {p}
        </span>
      ))}
      {children}
    </p>
  );
}

export default function ModelFrame({
  crumbs, title, badges, answer, primary, actions, menu, id, embedded = false, className, children, notice,
}) {
  const ref = useRef(null);
  useFillHeight(ref, !embedded);
  return (
    <div ref={ref} className={"app model-frame" + (embedded ? " mf-embedded" : "") + (className ? " " + className : "")}>
      {(title || crumbs) && (
        <PageHeader
          className="mf-header"
          crumbs={crumbs}
          title={title}
          badges={badges}
          primary={primary}
          actions={actions}
          menu={menu}
          id={id}
        >
          {Array.isArray(answer) ? <AnswerLine parts={answer} /> : answer}
        </PageHeader>
      )}
      {notice}
      <div className="card mf-card">{children}</div>
    </div>
  );
}

// The tab row and the active tab's body. ``before`` sits between them (a
// notice that belongs to every tab). With no tabs (a one-view model) the
// body alone.
export function ModelTabs({ tabs, value, onChange, idPrefix = "mf", label = "Model views", before, children }) {
  if (!tabs?.length) return <div className="mf-result"><div className="mf-body mf-single">{children}</div></div>;
  return (
    <div className="mf-result">
      <Tabs tabs={tabs} value={value} onChange={onChange} label={label} idPrefix={idPrefix} className="mf-tabs" />
      {before}
      <div
        className={`mf-body mf-body-${value}`}
        role="tabpanel"
        id={panelId(idPrefix)}
        aria-labelledby={tabId(idPrefix, value)}
      >
        {children}
      </div>
    </div>
  );
}
