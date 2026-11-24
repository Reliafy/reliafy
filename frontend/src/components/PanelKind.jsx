// The compact title line of a panel in the Explorer (the RCM tab's details, the Maintenance tab's
// task): the row's kind icon (a spanner for a task, a bolt for a failure mode, …) and its kind in
// words, with where it is after a "·" when the panel says so ("Task · TR-48 mower"). One component,
// so a task reads the same on the RCM and Maintenance tabs (Derryn, 23 Nov 2026). Guideline:
// docs/design-system/components/PanelKind.md.

const ICONS = {
  fn: <path d="M3 3.5h10v9H3z M6.5 6v4l3.5-2z" strokeWidth="1.4" strokeLinejoin="round" />,
  // A performance standard: a limit on a scale.
  std: <><path d="M2 10.5h12M4 10.5v-3M7 10.5v-4.5M10 10.5v-3M13 10.5v-4.5" strokeWidth="1.4" strokeLinecap="round" /><path d="M2 13h12" strokeWidth="1.4" strokeLinecap="round" /></>,
  fail: <><path d="M8 2.2 14.2 13H1.8z" strokeWidth="1.4" strokeLinejoin="round" /><path d="M8 6.5v3" strokeWidth="1.6" strokeLinecap="round" /><circle cx="8" cy="11.2" r=".9" fill="currentColor" stroke="none" /></>,
  mode: <path d="M9.2 1.8 3.8 9h4l-1 5.2L12.2 7h-4z" strokeWidth="1.4" strokeLinejoin="round" />,
  cause: <path d="M4 2.5v6a2 2 0 0 0 2 2h6M9.5 7.5l3 3-3 3" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />,
  task: <path d="M10.6 2.3a3.2 3.2 0 0 0-3.9 4.1L2.4 10.7a1.4 1.4 0 0 0 2 2l4.3-4.3a3.2 3.2 0 0 0 4.1-3.9l-1.9 1.9-1.8-.4-.4-1.8z" strokeWidth="1.3" strokeLinejoin="round" />,
};

export function LevelIcon({ type, className = "rw-ic" }) {
  return (
    <svg className={type === "std" ? `${className} rw-ic-std` : className} viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" aria-hidden="true">
      {ICONS[type]}
    </svg>
  );
}


export default function PanelKind({ type, children, where = "", title }) {
  return (
    <div className="rw-panel-kind" title={title || (where ? `${children} · ${where}` : undefined)}>
      <LevelIcon type={type} /> {children}{where ? <span className="rw-panel-where"> · {where}</span> : null}
    </div>
  );
}
