import Fold from "./ui/Fold.jsx";

// A task's optional extras, Cost, Labour and Parts, each a fold-out with a line saying what's set
// (Derryn, 23 Nov 2026): one component for the Maintenance tab's task panel (where they're edited,
// MaintenanceTask) and the RCM tab's (where they're read, with the way to change them). The words
// come from taskExtras.js, as the tree's rows under the task do.
//
//   items   [{key: "cost" | "labour" | "parts" | …, title, summary, body, id?, ref?}] in order
//   open    {key: true}; onToggle(key, open)
export default function TaskExtras({ items, open = {}, onToggle, className = "" }) {
  return (
    <div className={"mt-extras" + (className ? ` ${className}` : "")}>
      {items.filter(Boolean).map((x) => (
        <Fold key={x.key} ref={x.ref} id={x.id} title={x.title} summary={x.summary} open={!!open[x.key]}
              onToggle={(o) => onToggle(x.key, o)}>
          {x.body}
        </Fold>
      ))}
    </div>
  );
}
