import "./Loading.css";

// The one loading state: what sits where something will be while it loads.
// Guideline: docs/design-system/components/Loading.md.
//
// Two forms:
//
//   block (the default): quiet grey rows in the shape of what's coming, for a
//   whole list, card, panel or page. Never "Loading…" in a card, and never the
//   list's empty sentence, which says something untrue until the answer is in.
//     shape   "list" (a kind, a name, a line of detail; the default) or
//             "fields" (a form: a short label bar over a control-high box)
//     rows    how many rows (3)
//     card    true: drawn in its own card, in place of a card that will load
//     label   what a screen reader hears ("Loading…"); null when a parent
//             already says the page is loading
//
//   inline: a quiet "Loading…" (or `label`) for a spot inside text, a field,
//   a button or a small card.
//     as      the element ("span"; "p" where it stands as a line of its own)
//
// Both carry `view-loading`, the mark the smoke suite waits on, so a page
// counts as settled only once its loading states are gone. Never put either
// under a LoadFailed card: LoadFailed takes the loader's place.
export default function Loading({
  inline = false, as: Tag = "span", label = "Loading…",
  shape = "list", rows = 3, card = false, className = "",
}) {
  if (inline) {
    return (
      <Tag className={"loading-inline view-loading" + (className ? ` ${className}` : "")} role="status">
        {label}
      </Tag>
    );
  }
  const fields = shape === "fields";
  const body = (
    <div className={"wait-rows view-loading" + (fields ? " wait-fields" : "") + (className && !card ? ` ${className}` : "")}
         role={label ? "status" : undefined}>
      {label && <span className="sr-only">{label}</span>}
      {Array.from({ length: rows }, (_, i) => fields ? (
        <div className="wait-field" key={i} aria-hidden="true">
          <span className="wait-bar wait-label" />
          <span className="wait-bar wait-box" />
        </div>
      ) : (
        <div className="wait-row" key={i} aria-hidden="true">
          <span className="wait-bar wait-kind" />
          <span className="wait-body">
            <span className="wait-bar wait-name" />
            <span className="wait-bar wait-detail" />
          </span>
        </div>
      ))}
    </div>
  );
  return card ? <div className={"card loading-card" + (className ? ` ${className}` : "")}>{body}</div> : body;
}
