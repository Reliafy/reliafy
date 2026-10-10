import { useEffect, useState } from "react";
import Modal from "./Modal.jsx";
import Plot from "./Plot.jsx";
import Chip from "./ui/Chip.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { getModelDiagnostics, getResiduals } from "../api.js";
import { formatNumber } from "../format.js";
import { COLORWAY, referenceShape } from "../plotTheme.js";
import { unitInText } from "./unitText.js";
import "./RegressionChecks.css";

// "Does the model hold?" (#61), beside "How good is this model?" in a
// regression model's Validation tab: a plain verdict on each check first —
// the proportional-hazards test, robust standard errors, ties and strata —
// with the test table, the residual plots and the robust intervals in a
// dialog. Every number is SurPyval's (check_ph, summary(robust=True),
// compute_residuals); ``diagnostics`` is stored with the fit, or fetched for
// a model saved before it (``modelId``).

const TONE = { good: "success", caveat: "warning" };

export const fmtP = (p) => (p == null ? "—" : p < 0.001 ? "< 0.001" : formatNumber(p, { sig: 2 }));

function useDiagnostics(diagnostics, modelId) {
  const [fetched, setFetched] = useState(null);
  const [error, setError] = useState(null);
  const needsFetch = !diagnostics && !!modelId;
  useEffect(() => {
    if (!needsFetch) return undefined;
    let live = true;
    setFetched(null);
    setError(null);
    getModelDiagnostics(modelId)
      .then((d) => live && setFetched(d))
      .catch((err) => live && setError(err.message));
    return () => {
      live = false;
    };
  }, [needsFetch, modelId]);
  return { d: diagnostics || fetched, loading: needsFetch && !fetched && !error, error };
}

function Verdict({ check }) {
  return (
    <div className="checks-verdict">
      <span className="checks-title">
        <Chip tone={TONE[check.tone] || "neutral"}>{check.title}</Chip>
      </span>
      <p className="vread">{check.reading}</p>
    </div>
  );
}

export default function RegressionChecks({ diagnostics, modelId, residualsPath, unit }) {
  const { d, loading, error } = useDiagnostics(diagnostics, modelId);
  const [open, setOpen] = useState(false);

  let body;
  if (loading) {
    body = <div className="vrow"><p className="vread">Running the checks…</p></div>;
  } else if (!d || error) {
    body = (
      <div className="vrow">
        <p className="vread"><b>Not available.</b> {error ? "The checks couldn't be loaded." : "Not run for this model."}</p>
      </div>
    );
  } else {
    const ph = d.ph_test || {};
    const rob = d.robust;
    body = (
      <>
        <div className="vrow">
          <div className="vrow-head">
            <span className="gk">
              Proportional hazards
              <span className="vterm">{!ph.available && rob && rob.reason === ph.reason ? "test and robust errors" : "Grambsch-Therneau test"}</span>
            </span>
            {ph.available && <span className="gv">p {ph.global.p < 0.001 ? "" : "= "}{fmtP(ph.global.p)}</span>}
          </div>
          {ph.available ? (
            <>
              <Verdict check={ph} />
              {ph.source_note && <div className="vsub">{ph.source_note}</div>}
            </>
          ) : (
            <p className="vread">{(ph.reason || "Not available.").replace(/^Not available:\s*/, "")}</p>
          )}
        </div>
        {/* Said once: a stratified fit has neither, for the same reason. */}
        {rob && !(!rob.available && rob.reason === ph.reason) && (
          <div className="vrow">
            <div className="vrow-head">
              <span className="gk">
                Robust standard errors
                <span className="vterm">{rob.cluster ? `clustered by ${rob.cluster}` : "sandwich"}</span>
              </span>
              {rob.available && rob.max_change != null && (
                <span className="gv">{Math.abs(rob.max_change) < 0.005 ? "same" : `up to ${Math.round(Math.abs(rob.max_change) * 100)}% apart`}</span>
              )}
            </div>
            {rob.available ? <Verdict check={rob} /> : <p className="vread">{rob.reason}</p>}
          </div>
        )}
        {d.strata && (
          <div className="vrow">
            <div className="vrow-head">
              <span className="gk">Strata</span>
              <span className="gv">{d.strata.column}</span>
            </div>
            <p className="vread">{d.strata.reading}</p>
          </div>
        )}
        {d.ties && (
          <div className="vrow">
            <div className="vrow-head">
              <span className="gk">Tied failure times</span>
              <span className="gv">{d.ties.label}</span>
            </div>
            <p className="vread">{d.ties.reading}</p>
          </div>
        )}
        {(ph.available || rob?.available) && (
          <div className="checks-actions">
            <button type="button" className="secondary sm" onClick={() => setOpen(true)}>
              Test details and residuals
            </button>
          </div>
        )}
      </>
    );
  }

  return (
    <div className="gof-metrics-card validation-card">
      <div className="gofh">Does the model hold?</div>
      {body}
      {open && d && (
        <ChecksModal d={d} residualsPath={residualsPath} unit={unit} onClose={() => setOpen(false)} />
      )}
    </div>
  );
}

function PhTable({ ph }) {
  return (
    <div className="rs-table-wrap">
      <table className="mini-table checks-table">
        <thead>
          <tr><th>Covariate</th><th>χ²</th><th>df</th><th>p</th></tr>
        </thead>
        <tbody>
          {ph.rows.map((r) => (
            <tr key={r.covariate}>
              <td>{r.covariate}</td>
              <td>{formatNumber(r.statistic, { sig: 3 })}</td>
              <td>{r.df}</td>
              <td className={r.p != null && r.p < ph.alpha ? "flag" : ""}>{fmtP(r.p)}</td>
            </tr>
          ))}
          <tr className="global">
            <td>GLOBAL</td>
            <td>{formatNumber(ph.global.statistic, { sig: 3 })}</td>
            <td>{ph.global.df}</td>
            <td className={ph.global.p < ph.alpha ? "flag" : ""}>{fmtP(ph.global.p)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function RobustTable({ rob }) {
  return (
    <div className="rs-table-wrap">
      <table className="mini-table checks-table">
        <thead>
          <tr><th>Covariate</th><th>Hazard ratio</th><th>Std error</th><th>Robust</th><th>Robust 95% interval</th><th>p (robust)</th></tr>
        </thead>
        <tbody>
          {rob.rows.map((r) => (
            <tr key={r.covariate}>
              <td>{r.covariate}</td>
              <td>{formatNumber(r.ratio, { sig: 4 })}</td>
              <td>{formatNumber(r.se, { sig: 3 })}</td>
              <td>{formatNumber(r.robust_se, { sig: 3 })}</td>
              <td>{formatNumber(r.ratio_lower, { sig: 3 })}–{formatNumber(r.ratio_upper, { sig: 3 })}</td>
              <td>{fmtP(r.p)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const KINDS = [
  { value: "schoenfeld", label: "Schoenfeld" },
  { value: "martingale", label: "Martingale" },
  { value: "deviance", label: "Deviance" },
];

const KIND_TEXT = {
  schoenfeld: "One panel per covariate: its effect over time, read from the scaled Schoenfeld residuals, with "
    + "the mean of each tenth as a line and the fitted coefficient dotted. A line that stays level with the "
    + "coefficient is what proportional hazards looks like; a trend means the covariate's effect changes over time.",
  martingale: "Martingale residuals against the model's linear predictor: observed minus expected failures "
    + "for each unit. A curve here suggests a covariate needs another form (a log, say); a unit far below "
    + "the rest outlived the model's expectation.",
  deviance: "Deviance residuals against the linear predictor: martingale residuals made symmetric. Units "
    + "beyond about ±2.5 are poorly predicted by the model: worth checking in the data.",
};

function ResidualPlots({ path, ph, unit }) {
  const [kind, setKind] = useState("schoenfeld");
  const [res, setRes] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    if (!path) return undefined;
    let live = true;
    getResiduals(path)
      .then((r) => live && setRes(r))
      .catch((err) => live && setError(err.message));
    return () => {
      live = false;
    };
  }, [path]);
  if (!path) return null;
  if (error) return <p className="hint">Couldn't load the residuals: {error}</p>;
  if (!res) return <p className="muted-line">Computing the residuals…</p>;
  if (!res.available) return <p className="muted-line">{res.reason}</p>;

  const u = unit ? ` (${unitInText(unit)})` : "";
  const pOf = Object.fromEntries((ph?.rows || []).map((r) => [r.covariate, r.p]));
  const dots = (color) => ({ type: "scatter", mode: "markers", marker: { size: 4, color, opacity: 0.55 },
                            hoverinfo: "x+y" });
  const zero = [referenceShape({ y: 0, line: { dash: "dot" } })];
  return (
    <>
      <SegmentedControl label="Residuals" size="sm" className="resid-tabs" value={kind} onChange={setKind}
                        options={KINDS} />
      <p className="muted-line" style={{ margin: "0 0 10px" }}>{KIND_TEXT[kind]}</p>
      {kind === "schoenfeld" ? (
        <div className="resid-grid">
          {res.schoenfeld.map((s, i) => {
            const color = COLORWAY[i % COLORWAY.length];
            const p = pOf[s.covariate];
            return (
              <div className="resid-panel" key={s.covariate}>
                <p className="resid-name">{s.covariate}</p>
                <p className="resid-p">
                  Coefficient {formatNumber(s.coef, { sig: 3 })}
                  {p != null && <> · test p {p < 0.001 ? "" : "= "}{fmtP(p)}</>}
                </p>
                <Plot
                  data={[
                    { ...dots(color), x: s.x, y: s.y, name: s.covariate },
                    { type: "scatter", mode: "lines", x: s.trend.x, y: s.trend.y, line: { color, width: 2 },
                      name: "Trend", hoverinfo: "skip" },
                  ]}
                  layout={{ height: 220, showlegend: false, margin: { t: 6, r: 8 },
                            shapes: [referenceShape({ y: s.coef, line: { dash: "dot" } })],
                            xaxis: { title: { text: `Failure time${u}` } },
                            yaxis: { title: { text: "Effect, β(t)" } } }}
                  download={`Scaled Schoenfeld residuals — ${s.covariate}`}
                />
              </div>
            );
          })}
        </div>
      ) : (
        <Plot
          data={[{ ...dots(COLORWAY[0]), x: res[kind].x, y: res[kind].y, name: kind }]}
          layout={{ height: 300, showlegend: false, margin: { t: 6, r: 8 }, shapes: zero,
                    xaxis: { title: { text: "Linear predictor (log relative risk)" } },
                    yaxis: { title: { text: `${kind === "martingale" ? "Martingale" : "Deviance"} residual` } } }}
          download={`${kind === "martingale" ? "Martingale" : "Deviance"} residuals`}
        />
      )}
      {res.source_note && <p className="muted-line">{res.source_note}</p>}
      {res.n > res.martingale.x.length && kind !== "schoenfeld" && (
        <p className="muted-line">{res.martingale.x.length.toLocaleString()} of {res.n.toLocaleString()} units shown, spread evenly.</p>
      )}
    </>
  );
}

function ChecksModal({ d, residualsPath, unit, onClose }) {
  const ph = d.ph_test || {};
  const rob = d.robust;
  return (
    <Modal
      title="Model checks"
      className="modal-xl"
      onClose={onClose}
      footer={<div className="row" style={{ margin: 0, marginLeft: "auto" }}><button onClick={onClose}>Done</button></div>}
    >
      {ph.available && (
        <section className="checks-section">
          <h3>Proportional-hazards test</h3>
          <Verdict check={ph} />
          <PhTable ph={ph} />
          <p className="muted-line">
            Grambsch-Therneau test on the scaled Schoenfeld residuals, against the Kaplan-Meier time scale. A p
            below {ph.alpha} says that covariate's effect changes over time; the GLOBAL row tests them all
            together. {ph.source_note || ""}
          </p>
        </section>
      )}
      {ph.available && residualsPath && (
        <section className="checks-section">
          <h3>Residuals</h3>
          <ResidualPlots path={residualsPath} ph={ph.available ? ph : null} unit={unit} />
        </section>
      )}
      {rob?.available && (
        <section className="checks-section">
          <h3>Robust standard errors</h3>
          <Verdict check={rob} />
          <RobustTable rob={rob} />
          <p className="muted-line">
            Sandwich (Lin-Wei) standard errors{rob.cluster ? `, clustered by ${rob.cluster} (${rob.n_clusters} groups)` : ""}:
            they stay valid when rows aren't independent (several rows from one unit, units grouped by site).
          </p>
        </section>
      )}
    </Modal>
  );
}
