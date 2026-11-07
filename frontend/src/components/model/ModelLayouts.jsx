// The six layouts a model page's tab body uses (the frame is ModelFrame.jsx).
// Each fills the body's height on a desktop screen and stacks on a phone:
//
//   PlotPanel     L1  a chart that fills the height, a panel beside it
//   TwoPlots      L2  two charts side by side (one under the other on a phone)
//   ChecksGrid    L3  Diagnostics: small checks (CheckCard), a side column
//   (Calculator)  L4  the calculator keeps its own layout (Calculator.jsx)
//   TablePanel    L5  a table that scrolls inside its card, a panel beside it
//   NumbersSheet  L6  cards of figures
//
// and the pieces inside them: PlotCard (a bordered chart box), ScrollCard (a
// card whose body scrolls inside it) and CheckCard (one check: its question,
// the technical name in brackets, a verdict and a chart or a short table).
import Chip from "../ui/Chip.jsx";
import { VERDICT } from "../../modelFrame.js";

const cx = (...names) => names.filter(Boolean).join(" ");

export function PlotPanel({ plot, below, side, className, sideClassName }) {
  return (
    <div className={cx("detail-panel life-panel mf-l1", className)}>
      <div className="mf-main">
        {plot}
        {below}
      </div>
      {side && <div className={cx("aside mf-side", sideClassName)}>{side}</div>}
    </div>
  );
}

export function TwoPlots({ first, second, side, className }) {
  return (
    <div className={cx("detail-panel mf-l2", className)}>
      <div className="mf-l2-plots">
        <div className="mf-main">{first}</div>
        <div className="mf-main">{second}</div>
      </div>
      {side && <div className="aside mf-side">{side}</div>}
    </div>
  );
}

// A chart in a bordered box that fills its share of the height. ``title``
// (optional) sits above it; ``controls`` (a switch) under it.
export function PlotCard({ title, children, controls, className }) {
  return (
    <div className={cx("mf-plot-card", className)}>
      {title && <h3 className="mf-plot-title">{title}</h3>}
      {children}
      {controls && <div className="mf-plot-controls">{controls}</div>}
    </div>
  );
}

// The checks grid of the Diagnostics tab: the checks (CheckCard) in a grid
// that shares the height, and a side column (fit statistics, verdicts) that
// scrolls inside itself.
export function ChecksGrid({ children, side, toolbar, className }) {
  return (
    <div className={cx("detail-panel mf-l3", className)}>
      <div className="mf-l3-main">
        {toolbar && <div className="mf-l3-toolbar">{toolbar}</div>}
        <div className="mf-checks">{children}</div>
      </div>
      {side && <div className="mf-l3-side">{side}</div>}
    </div>
  );
}

// One check. ``question`` is its title ("Does the curve follow the data?"),
// ``term`` the technical name shown in brackets after it, ``tone`` its
// verdict (good / caveat / bad, or none for a check to read rather than a
// test) and ``verdict`` the one line that says what it found. ``chart``:
// the children are a filling chart; otherwise they scroll inside the card.
export function CheckCard({ question, term, tone, verdict, children, chart = false, className, footer }) {
  const v = VERDICT[tone];
  return (
    <section className={cx("mf-check", chart && "mf-check-chart", className)} aria-label={question}>
      <div className="mf-check-head">
        <h3 className="mf-check-q">
          {question}
          {term && <span className="mf-check-term"> ({term})</span>}
        </h3>
        {v && (
          <Chip tone={tone === "good" ? "success" : tone === "bad" ? "danger" : "warning"} className="mf-verdict">
            <span aria-hidden="true">{v.icon}</span> {v.label}
          </Chip>
        )}
      </div>
      {verdict && <p className="mf-check-verdict">{verdict}</p>}
      <div className={chart ? "mf-check-plot" : "mf-check-body"}>{children}</div>
      {footer && <div className="mf-check-foot">{footer}</div>}
    </section>
  );
}

export function TablePanel({ main, side, className }) {
  return (
    <div className={cx("detail-panel mf-l5", className)}>
      <div className="mf-l5-main">{main}</div>
      {side && <div className="mf-l5-side">{side}</div>}
    </div>
  );
}

export function NumbersSheet({ children, className }) {
  return <div className={cx("detail-panel mf-l6", className)}>{children}</div>;
}

// A card whose body scrolls inside it: a heading row, then the content.
export function ScrollCard({ title, sub, actions, children, className, id }) {
  return (
    <section className={cx("gof-card mf-scroll-card", className)} aria-labelledby={id}>
      {(title || actions) && (
        <div className="gofh mf-card-head">
          <span>
            <h3 className="mf-card-title" id={id}>{title}</h3>
            {sub && <span className="gof-sub">{sub}</span>}
          </span>
          {actions}
        </div>
      )}
      <div className="mf-scroll" tabIndex={0} role="region" aria-label={typeof title === "string" ? title : undefined}>
        {children}
      </div>
    </section>
  );
}
