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
import { useRef } from "react";
import ScrollCue from "./ScrollCue.jsx";
import { nextTabIndex } from "../../modelFrame.js";

export const tabId = (prefix, id) => `${prefix}-tab-${id}`;
export const panelId = (prefix) => `${prefix}-panel`;

export default function Tabs({ tabs, value, onChange, label, className, idPrefix }) {
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
