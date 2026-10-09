// A small label (#310): 12px sans, sentence case, 6px radius. Colour only when
// it means something (#304):
//   neutral  the default: a kind, a source, a flag ("Sample", "Shared")
//   accent   the current or chosen thing ("Current plan", "Suggested")
//   success  a good verdict ("Supported", "Healthy")
//   warning  a caveat ("Simulated", "Unsaved", "Plan replacement")
//   danger   a bad verdict ("Contradicted", "Replace now")
// dot puts a small coloured dot before the text (a distribution's colour).
// With onClick it renders as a button (an editable value, e.g. a decision).
const TONES = new Set(["neutral", "accent", "success", "warning", "danger"]);

export default function Chip({ tone = "neutral", dot, className, children, onClick, ...rest }) {
  const cls = "chip chip-" + (TONES.has(tone) ? tone : "neutral") + (onClick ? " chip-btn" : "") + (className ? " " + className : "");
  const body = (
    <>
      {dot && <span className="chip-dot" style={{ background: dot }} aria-hidden="true" />}
      {children}
    </>
  );
  if (onClick) {
    return (
      <button type="button" className={cls} onClick={onClick} {...rest}>
        {body}
      </button>
    );
  }
  return (
    <span className={cls} {...rest}>
      {body}
    </span>
  );
}
