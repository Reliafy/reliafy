import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import FitFlow from "../components/FitFlow.jsx";
import ParamsPanel from "../components/ParamsPanel.jsx";
import PerDemandPanel from "../components/PerDemandPanel.jsx";
import { listDatasets } from "../api.js";

// Built-in sample datasets worth putting in front of a first-time visitor,
// in display order, with a one-line hook each. Anything else flagged
// ``is_sample`` fills in if one of these is missing.
const FEATURED_SAMPLES = [
  { id: "sample-ds-bearings", blurb: "30 bench-test failure times — the textbook Weibull case" },
  { id: "sample-ds-pumps", blurb: "Field returns with units still running (right-censored)" },
  { id: "sample-ds-insulating-fluid", blurb: "Breakdown times at four voltages — a covariate" },
];
const N_SAMPLES = 3;

// Dedicated page for building a new model. First question: where does the
// model come from — a CSV, values pasted in, known parameters, or one of the
// built-in sample datasets. All four are equals: most visitors arrive with no
// file to hand. Per-demand (Binomial) is reachable from the parameters panel
// and from the fit-to-data source step.
export default function NewModelPage() {
  const navigate = useNavigate();
  const query = new URLSearchParams(useLocation().search);
  const initialMode = query.get("mode");
  // Guided first-run deep link: ?dataset=<id>&auto=1 jumps straight into the
  // fit flow pre-loaded with a dataset (used by the activation panel).
  const queryDatasetId = query.get("dataset") || null;
  const autoFit = query.get("auto") === "1";
  const [mode, setMode] = useState(
    queryDatasetId ? "data"
    : ["data", "paste", "params", "perdemand"].includes(initialMode) ? initialMode : null
  ); // null | "data" | "paste" | "params" | "perdemand"
  // Dataset the fit flow should open on (a sample picked here, or the deep link).
  const [datasetId, setDatasetId] = useState(queryDatasetId);
  const [samples, setSamples] = useState([]);

  useEffect(() => {
    listDatasets()
      .then(({ datasets }) => {
        const all = datasets.filter((d) => d.is_sample);
        const featured = FEATURED_SAMPLES
          .map((f) => {
            const d = all.find((x) => x.id === f.id);
            return d ? { ...d, blurb: f.blurb } : null;
          })
          .filter(Boolean);
        const rest = all.filter((d) => !featured.some((f) => f.id === d.id));
        setSamples([...featured, ...rest].slice(0, N_SAMPLES));
      })
      .catch(() => setSamples([]));
  }, []);

  const openModel = (model) => navigate(`/modelling/m/${model.id}`);

  const start = (next, dsId = null) => {
    setDatasetId(dsId);
    setMode(next);
  };

  const fitting = mode === "data" || mode === "paste";
  const heading =
    mode === "params" ? "From parameters"
    : mode === "perdemand" ? "Per-demand"
    : fitting ? "Fit to data"
    : "New model";
  const sub =
    mode === "params" ? "Enter known parameters to build the model."
    : mode === "perdemand" ? "Reliability per demand, from a demands/failures count."
    : fitting ? "Pick data, map columns, fit, then review and save."
    : "Where does the model come from?";

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/modelling/life")}>Life data models</button> /{" "}
            <b>New model</b>
          </div>
          <h1>{heading}</h1>
          <p>{sub}</p>
        </div>
      </header>

      {/* First question: choose how to build the model. Four equal entry
          points — no file needed for three of them. */}
      {mode === null && (
        <div className="card">
          <div className="ds-choose new-model-choose">
            <button className="ds-choice" onClick={() => start("data")}>
              <span className="ds-choice-h">Upload a CSV</span>
              <span className="ds-choice-b">
                Drop in a file with a time column (and optionally censoring and
                covariates) — fit a distribution or PH model with a probability
                plot and goodness of fit.
              </span>
            </button>
            <button className="ds-choice" onClick={() => start("paste")}>
              <span className="ds-choice-h">Paste values</span>
              <span className="ds-choice-b">
                No file? Paste times to failure straight from a spreadsheet or
                notebook — one per line, with an optional 0/1 censoring flag.
              </span>
            </button>
            <button className="ds-choice" onClick={() => start("params")}>
              <span className="ds-choice-h">Enter parameters</span>
              <span className="ds-choice-b">
                Already know the shape and scale — a handbook or report value, or
                a fit done elsewhere? Enter them for the reliability functions
                and life metrics.
              </span>
            </button>
            <div className="ds-choice ds-choice-static">
              <span className="ds-choice-h">Try a sample dataset</span>
              <span className="ds-choice-b">
                Just looking? Fit one of the built-in datasets to see what a
                finished model looks like.
              </span>
              <div className="sample-picks">
                {samples.length === 0 ? (
                  <span className="muted-line" style={{ margin: 0 }}>Loading samples…</span>
                ) : (
                  samples.map((d) => (
                    <button
                      key={d.id}
                      type="button"
                      className="recent-row"
                      onClick={() => start("data", d.id)}
                    >
                      <span className="recent-ic">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M14 3v5h5M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" />
                        </svg>
                      </span>
                      <span className="sample-pick-text">
                        <span className="recent-name">{d.name.replace(/\s*\(sample\)\s*$/i, "")}</span>
                        {d.blurb && <span className="sample-pick-blurb">{d.blurb}</span>}
                      </span>
                      <span className="recent-meta">{d.n_rows.toLocaleString()} rows</span>
                    </button>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {fitting && (
        <FitFlow
          key={`${mode}-${datasetId || ""}`}
          onSaved={openModel}
          onCancel={() => start(null)}
          onPerDemand={() => start("perdemand")}
          initialDatasetId={datasetId}
          autoFit={autoFit}
          initialSource={mode === "paste" ? "paste" : "upload"}
        />
      )}

      {mode === "params" && (
        <ParamsPanel
          onCreated={openModel}
          onCancel={() => start(null)}
          onPerDemand={() => start("perdemand")}
        />
      )}

      {mode === "perdemand" && (
        <PerDemandPanel onCreated={openModel} onBack={() => start(null)} />
      )}
    </div>
  );
}
