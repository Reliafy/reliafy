import Chip from "./ui/Chip.jsx";
import Section from "./ui/Section.jsx";
import OperatingContextCard from "./OperatingContextCard.jsx";
import { CloseIcon, ExpandIcon, ShrinkIcon } from "./icons.jsx";
import { NO_FUNCTIONS } from "./TreePane.jsx";
import "./RcmPositionPanel.css";

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;

// A position picked on the RCM tab: its operating context (edited in place)
// and its functions, each a link to the function's row in the table.
//   functions  explorerRcm.js functionSummary
//   position   the position fetch ({ data, error }) the context card reads
//   expanded   filling the table's room; onExpand / onCollapse switch it (none on a phone)
export default function RcmPositionPanel({
  row, kind, functions, position, phone, headingRef, onClose, onSelect, onAdd, onContextSaved, canAdd = true,
  expanded = false, onExpand = null, onCollapse = null,
}) {
  const canExpand = !phone && onExpand && onCollapse;
  const name = row.ref.name || "(no name)";
  return (
    <aside className={"rw-panel rp-pos" + (phone ? " sheet" : "") + (expanded ? " is-expanded" : "")} aria-label="Details"
           onKeyDown={(e) => {
             if (e.key !== "Escape" || e.defaultPrevented) return;
             e.stopPropagation();
             if (expanded && canExpand) onCollapse();
             else onClose();
           }}>
      <div className="rw-panel-top">
        <div className="rw-panel-head">
          <div className="rw-panel-kind">{kind || "Position"}</div>
          <div className="rw-panel-btns">
            {canExpand && (expanded ? (
              <button type="button" className="ghost sm rw-x" onClick={onCollapse} title="Show the table again, with these details beside it (Esc)"
                      aria-label="Back to table"><ShrinkIcon /></button>
            ) : (
              <button type="button" className="ghost sm rw-x" onClick={onExpand} title="Show these details across the table, the tree kept beside them"
                      aria-label="Expand the details"><ExpandIcon /></button>
            ))}
            <button type="button" className="ghost sm rw-x" onClick={onClose} aria-label="Close the details" title="Close (Esc)"><CloseIcon /></button>
          </div>
        </div>
        <h2 className="rw-panel-title" tabIndex={-1} ref={headingRef}>{name}</h2>
      </div>
      <div className="rw-pbody">
        <OperatingContextCard positionId={row.key} state={position} onSaved={onContextSaved} />
        <Section title="Functions" label="Functions">
          {functions.length ? (
            <ul className="rp-fns">
              {functions.map((f) => (
                <li key={f.key}>
                  <button type="button" className="rp-fn" onClick={() => onSelect(f.key)}>
                    <span className="rp-fn-text">{f.text}</span>
                    <span className="rp-fn-meta">
                      {plural(f.standards, "performance standard")}
                      {" · "}{plural(f.failures, "functional failure")}
                      {" · "}{f.modes ? `${plural(f.modes, "failure mode")}, ${f.decided} decided` : "no failure modes yet"}
                    </span>
                    {f.standardTexts.length > 0 && <span className="rp-fn-std">{f.standardTexts.join("; ")}</span>}
                  </button>
                  {f.hasBasis && <Chip tone="neutral" title="This function has a working">Working</Chip>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="rw-inside">{NO_FUNCTIONS}</p>
          )}
          {canAdd && <button type="button" className="sm" onClick={onAdd}>Add function</button>}
        </Section>
      </div>
    </aside>
  );
}
