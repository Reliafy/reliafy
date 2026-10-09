// An on/off switch: a button with role="switch", a track and knob, and its
// label beside it. For a setting that applies at once (an alert on or off),
// not for a form field that waits for Save.
//   checked   boolean
//   onChange  (next: boolean) => void
//   label     node — the visible label ("On"); pass ariaLabel when it's terse
//   ariaLabel string — the accessible name, when the label alone is unclear
export default function Switch({ checked, onChange, label, ariaLabel, disabled, className, title }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={!!checked}
      aria-label={ariaLabel}
      title={title}
      disabled={disabled}
      className={"switch" + (className ? " " + className : "")}
      onClick={() => onChange(!checked)}
    >
      <span className="switch-track" aria-hidden="true"><span className="switch-knob" /></span>
      {label != null && <span className="switch-label">{label}</span>}
    </button>
  );
}
