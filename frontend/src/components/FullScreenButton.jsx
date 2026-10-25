import { forwardRef } from "react";

const EnterIcon = () => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M14 4h6v6M10 20H4v-6M20 4l-6.5 6.5M4 20l6.5-6.5" />
  </svg>
);

const ExitIcon = () => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 14h6v6M20 10h-6V4M14 10l6.5-6.5M10 14l-6.5 6.5" />
  </svg>
);

// The "Full screen" / "Exit full screen" toggle. Its words say which it does
// (not colour or the icon alone); ``shortcut`` is shown in the tooltip, with
// ``shortcutNote`` after it (where the key works, say).
// ``compact`` keeps only the icon on the way in on a phone (the shared page's
// corner button), never on the way out: "Exit full screen" is always spelt out.
const FullScreenButton = forwardRef(function FullScreenButton(
  { full, onClick, shortcut = "F", shortcutNote = "", className = "", compact = false },
  ref
) {
  const label = full ? "Exit full screen" : "Full screen";
  return (
    <button
      ref={ref}
      type="button"
      className={"secondary sm full-screen-btn" + (full ? " is-full" : "") + (className ? " " + className : "")}
      onClick={onClick}
      title={shortcut ? `${label} (${shortcut}${shortcutNote ? `, ${shortcutNote}` : ""})` : label}
      aria-label={label}
      aria-keyshortcuts={shortcut || undefined}
      data-full={full ? "true" : "false"}
    >
      {full ? <ExitIcon /> : <EnterIcon />}
      <span className={"full-screen-word" + (compact && !full ? " is-compact" : "")}>{label}</span>
    </button>
  );
});

export default FullScreenButton;
