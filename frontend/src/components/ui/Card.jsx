// A white card (#310): the page's unit of content. Forms and results sit
// directly on it; don't nest grey panels inside.
export default function Card({ className, children, ...rest }) {
  return (
    <div className={"card" + (className ? " " + className : "")} {...rest}>
      {children}
    </div>
  );
}

// A card's heading row: a 16px semibold title, an optional muted 13px
// subtitle under it, and actions (buttons, a select, a figure) on the right.
//   title     node
//   subtitle  node (optional)
//   actions   node (optional)
//   level     heading level, 2 by default (3 inside a section)
export function CardHeader({ title, subtitle, actions, level = 2, className }) {
  const H = `h${level}`;
  return (
    <div className={"card-head" + (className ? " " + className : "")}>
      <div className="card-head-text">
        <H className="card-title">{title}</H>
        {subtitle && <p className="card-sub">{subtitle}</p>}
      </div>
      {actions && <div className="card-head-actions">{actions}</div>}
    </div>
  );
}
