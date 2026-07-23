import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { trackEvent } from "../telemetry.js";
import { WaveIcon, PlusIcon } from "./icons.jsx";

// Guided first-run / activation. Two jobs:
//   1. When the workspace has no models of its own, show a focused "fit your
//      first model" hero — one click fits a Weibull on our sample data and
//      lands on a finished result; or upload your own CSV.
//   2. Once there's a first model, become a slim checklist that nudges toward
//      real activation: fit YOUR own data, then put a model to work.
// It disappears for good once the three steps are done (or dismissed).

const SAMPLE_BEARINGS = "sample-ds-bearings";
const DISMISS_KEY = "reliafy_gs_dismissed";
const STRATEGY_KEY = "reliafy_gs_strategy";
const ACTIVATED_KEY = "reliafy_activated";

const isSampleModel = (m) => String(m.dataset_id || "").startsWith("sample-");
const isOwnData = (m) => m.dataset_id && !isSampleModel(m);

export default function GettingStarted({ own, loading }) {
  const navigate = useNavigate();
  const [dismissed, setDismissed] = useState(
    () => localStorage.getItem(DISMISS_KEY) === "1"
  );
  const [strategyDone, setStrategyDone] = useState(
    () => localStorage.getItem(STRATEGY_KEY) === "1"
  );

  const firstModel = own.find(isOwnData) || own[0];
  const steps = [
    { key: "fit", label: "Fit your first model", done: own.length > 0 },
    { key: "own", label: "Fit a model from your own data", done: own.some(isOwnData) },
    { key: "work", label: "Put a model to work — find an optimal replacement interval", done: strategyDone },
  ];
  const allDone = steps.every((s) => s.done);

  // Activation metric: fire once, the moment the workspace gains its first
  // model. localStorage-guarded so it reports a browser's first activation only.
  useEffect(() => {
    if (own.length > 0 && localStorage.getItem(ACTIVATED_KEY) !== "1") {
      localStorage.setItem(ACTIVATED_KEY, "1");
      trackEvent("activated");
    }
  }, [own.length]);

  if (loading || allDone || dismissed) return null;

  // ---- First run: no models yet -> the fit-your-first-model hero. ----
  if (own.length === 0) {
    return (
      <div className="gs-hero">
        <div className="gs-hero-head">
          <h2>Fit your first model — about 30 seconds</h2>
          <p>Turn failure times into a reliability model with confidence bounds,
             a randomness verdict, and a calculator. Start with our data or yours.</p>
        </div>
        <div className="ds-choose gs-choose">
          <button
            className="ds-choice gs-choice"
            onClick={() => navigate(`/modelling/new?dataset=${SAMPLE_BEARINGS}&auto=1`)}
          >
            <span className="gs-choice-ic"><WaveIcon /></span>
            <span className="ds-choice-h">Use our sample data <span className="gs-rec">Recommended</span></span>
            <span className="ds-choice-b">
              30 bearing fatigue lives. We fit a Weibull and drop you straight on
              the result — β verdict, survival curve, calculator. Save it to keep it.
            </span>
          </button>
          <button
            className="ds-choice gs-choice"
            onClick={() => navigate("/modelling/new?mode=data")}
          >
            <span className="gs-choice-ic"><PlusIcon /></span>
            <span className="ds-choice-h">Upload my own CSV</span>
            <span className="ds-choice-b">
              Failure (and censored) times, optionally with covariates. Drop a
              CSV, map the columns, fit, and save.
            </span>
          </button>
        </div>
      </div>
    );
  }

  // ---- Bridge: first model exists -> slim checklist to real activation. ----
  const nextOwn = !own.some(isOwnData);
  return (
    <div className="gs-check">
      <div className="gs-check-head">
        <h3>Getting started</h3>
        <button className="modal-close" onClick={() => { localStorage.setItem(DISMISS_KEY, "1"); setDismissed(true); }} aria-label="Dismiss">×</button>
      </div>
      <ul className="gs-steps">
        {steps.map((s) => (
          <li key={s.key} className={s.done ? "done" : ""}>
            <span className="gs-tick" aria-hidden>{s.done ? "✓" : ""}</span>
            <span className="gs-step-label">{s.label}</span>
          </li>
        ))}
      </ul>
      <div className="gs-check-cta">
        {nextOwn ? (
          <button onClick={() => navigate("/modelling/new?mode=data")}>Fit your own data</button>
        ) : (
          <Link
            className="btn-like"
            to="/strategy/replacement"
            onClick={() => { localStorage.setItem(STRATEGY_KEY, "1"); setStrategyDone(true); }}
          >
            Find an optimal replacement interval
          </Link>
        )}
        {firstModel && (
          <Link className="gs-secondary" to={`/modelling/m/${firstModel.id}`}>
            Open {firstModel.name}
          </Link>
        )}
      </div>
    </div>
  );
}
