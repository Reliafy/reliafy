import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import FitFlow from "../components/FitFlow.jsx";
import ParamsPanel from "../components/ParamsPanel.jsx";
import PerDemandPanel from "../components/PerDemandPanel.jsx";
import { listDatasets } from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";

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
// model come from — data (a saved dataset, values pasted in or a file: one
// choice, the fit flow's source step), known parameters, or one of the
// built-in sample datasets. Per-demand (Binomial) is reachable from the
// parameters panel and from the fit-to-data source step.
//
// ?mode=: saved (the fit flow on the saved-data list), paste, upload (also
// "data", the older name for it), params, perdemand.
const FIT_SOURCE = { saved: "saved", paste: "paste", upload: "upload", data: "upload" };
export default function NewModelPage() {
  const navigate = useNavigate();
  const query = new URLSearchParams(useLocation().search);
  const initialMode = query.get("mode");
  // Guided first-run deep link: ?dataset=<id>&auto=1 jumps straight into the
  // fit flow pre-loaded with a dataset (used by the activation panel).
  const queryDatasetId = query.get("dataset") || null;
  const autoFit = query.get("auto") === "1";
  const [mode, setMode] = useState(
    queryDatasetId ? "saved"
    : (FIT_SOURCE[initialMode] || ["params", "perdemand"].includes(initialMode)) ? initialMode : null
  ); // null | "saved" | "paste" | "upload" | "data" | "params" | "perdemand"
  // Dataset the fit flow should open on (a sample picked here, or the deep link).
  const [datasetId, setDatasetId] = useState(queryDatasetId);
  const [samples, setSamples] = useState([]);
  // A later link to this page with another ?dataset= (a walkthrough's start)
  // doesn't remount it: open the fit flow on that dataset.
  useEffect(() => {
    if (queryDatasetId) {
      setDatasetId(queryDatasetId);
      setMode("saved");
    }
  }, [queryDatasetId]);

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

  const openModel = (model) => navigate(`/models/m/${model.id}`);

  const start = (next, dsId = null) => {
    setDatasetId(dsId);
    setMode(next);
  };

  const fitting = !!FIT_SOURCE[mode];
  const heading =
    mode === "params" ? "From parameters"
    : mode === "perdemand" ? "Per-demand"
    : fitting ? "Fit to data"
    : "New model";
  const sub =
    mode === "params" ? "Enter known parameters to build the model."
    : mode === "perdemand" ? "Reliability per demand, from a demands/failures count."
    : fitting ? "Pick the data, choose a model and fit, then review and save."
    : "Where does the model come from?";

  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Models", to: "/models" }, { label: "Non-repairable", to: "/models/life" }]}
        title={heading}
        meta={sub}
      />

      {/* First question: choose how to build the model. Three equal entry
          points — none of them needs a file. */}
      {mode === null && (
        <div className="card">
          <div className="ds-choose new-model-choose">
            <button className="ds-choice" onClick={() => start("saved")}>
              <span className="ds-choice-h">Fit to data</span>
              <span className="ds-choice-b">
                Use one of your saved datasets, paste times to failure, or upload
                a CSV or Excel file. Then map the columns, fit a distribution or
                regression, and check the fit.
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
                      onClick={() => start("saved", d.id)}
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
          initialSource={FIT_SOURCE[mode]}
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
