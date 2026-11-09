import { CloseIcon } from "./icons.jsx";
import "./RcmWorksheet.css";
import "./TablePane.css";

// Work that fills the Explorer's table area on the Modelling tab, the tree kept beside it (Fit a
// life model…, Add a prediction…): a heading saying what it does and the position it's for
// ("Add a prediction · Controller"), × to go back to the table (Esc does the same, in
// AssetExplorer), and the work under it. On a phone it takes the screen, with ‹ Back.
//
//   title    what it does          subject  the position's name
//   busy     saving: it can't be closed      headingRef  focused when it opens
//   actions  more in the heading, before × ("Open full page")
//   closeLabel  ×'s name, when "Close <title>" doesn't read ("Close the RBD")
export default function TablePane({ title, subject, phone = false, busy = false, headingRef = null, onClose, className = "", actions = null,
  closeLabel = null, children }) {
  return (
    <section className={"rw-panel table-pane is-expanded" + (className ? ` ${className}` : "") + (phone ? " table-pane-phone" : "")}
             aria-label={title}>
      <div className="rw-panel-head table-pane-head">
        {phone && (
          <button type="button" className="ghost sm table-pane-back" onClick={onClose} disabled={busy}
                  aria-label="Back to the table">‹ Back</button>
        )}
        <h2 className="table-pane-title" tabIndex={-1} ref={headingRef}>
          {title} <span className="table-pane-pos">· {subject}</span>
        </h2>
        {(actions || !phone) && (
          <div className="rw-panel-btns">
            {actions}
            {!phone && (
              <button type="button" className="ghost sm rw-x" onClick={onClose} disabled={busy}
                      aria-label={closeLabel || `Close ${title.toLowerCase()}`} title="Back to the table (Esc)"><CloseIcon /></button>
            )}
          </div>
        )}
      </div>
      {children}
    </section>
  );
}
