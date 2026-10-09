// A row of mutually exclusive options (#310): sans, sentence case, the chosen
// option tinted in the accent. Renders the shared .seg / .seg-btn markup, so a
// caller can still scope layout with className.
//
//   options   [{ value, label, title?, disabled? }]
//   value     the chosen option's value
//   onChange  (value) => void
//   label     accessible name of the group (shown above it with showLabel)
//   size      "sm" for the compact size used inside cards and toolbars
export default function SegmentedControl({
  options,
  value,
  onChange,
  label,
  showLabel = false,
  size,
  className,
  style,
}) {
  const group = (
    <div
      className={"seg" + (size === "sm" ? " seg-sm" : "") + (className ? " " + className : "")}
      role="radiogroup"
      aria-label={label}
      style={style}
    >
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          className={"seg-btn" + (o.value === value ? " active" : "")}
          title={o.title}
          disabled={o.disabled}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
  if (!showLabel || !label) return group;
  return (
    <div className="seg-field">
      <span className="seg-label">{label}</span>
      {group}
    </div>
  );
}
