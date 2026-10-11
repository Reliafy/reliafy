// The shared tab row (#301). On a narrow screen the row scrolls sideways: the
// hidden side fades out with a chevron that scrolls it, and the active tab is
// kept in view. Renders the .tabs / .tab markup the app already styles.
//
//   tabs      [{ id, label, title?, wt? }] (wt: a guided walkthrough's anchor)
//   value     the active tab's id
//   onChange  (id) => void
//   label     accessible name of the row
//   className classes for the row's frame (e.g. "rbd-tabs")
import ScrollCue from "./ScrollCue.jsx";

export default function Tabs({ tabs, value, onChange, label, className }) {
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
      {tabs.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={value === t.id}
          className={"tab" + (value === t.id ? " active" : "")}
          title={t.title}
          data-wt={t.wt}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </ScrollCue>
  );
}
