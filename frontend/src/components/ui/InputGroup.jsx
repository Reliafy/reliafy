// Controls joined into one (#UI): a comparator, a value and its unit, or an
// interval and its unit. The unit sits inside the box (an addon, or a select
// at the end), so it's always read with its value. Children are .ctl controls
// and <Addon>s; the group draws one border and one focus ring round them.
export default function InputGroup({ children, className = "", label }) {
  return (
    <div className={"ctl-group" + (className ? ` ${className}` : "")} role="group" aria-label={label}>
      {children}
    </div>
  );
}

// Fixed words inside the group ("ppm", "weeks").
export function Addon({ children }) {
  return <span className="ctl-addon">{children}</span>;
}

// What a value will read as, under its controls: "Reads as: total alkalinity
// between 80 and 120 ppm". Nothing when there's nothing to read yet.
export function ReadsAs({ children }) {
  if (!children) return null;
  return <p className="reads-as" aria-live="polite"><span>Reads as:</span> <b>{children}</b></p>;
}
