import { formatNumber } from "../format.js";

// Fit quality tab: the information criteria in the shared card format. Lower
// AIC/AICc/BIC means a better fit (a higher log-likelihood does too); the
// numbers only mean something next to another fit to the same data, which is
// what Best fit does.
const fmt = (v) => formatNumber(v, { sig: 5 });

// ``note`` qualifies the numbers, e.g. a Cox model's AIC is on its partial
// likelihood and compares only with other Cox models (SurPyval 0.23, #604).
// ``bestFit`` (the fit chose among distributions) drops the pointer to it.
export default function GoodnessOfFit({ gof, n, note, bestFit = false }) {
  if (!gof || gof.length === 0) {
    return <p className="muted-line">No goodness-of-fit metrics available.</p>;
  }
  return (
    <>
      <div className="gof-metrics-card">
        <div className="gofh">
          Goodness of fit <span className="gof-sub">Lower is better</span>
        </div>
        {gof.map((g) => (
          <div className="gofr" key={g.id}>
            <span className="gk">
              {g.label}
              {g.id === "log_likelihood" && <span className="gof-sub"> · higher is better</span>}
            </span>
            <span className="gv">{fmt(g.value)}</span>
          </div>
        ))}
        {n != null && (
          <div className="gofr">
            <span className="gk">Observations</span>
            <span className="gv">{n.toLocaleString()}</span>
          </div>
        )}
      </div>
      {note && <p className="muted-line" style={{ margin: "8px 0 0" }}>{note}</p>}
      {!bestFit && (
        <p className="muted-line" style={{ margin: "8px 0 0" }}>
          These compare fits to the same data. To let the distributions compete, fit with{" "}
          <b>Best fit</b>.
        </p>
      )}
    </>
  );
}
