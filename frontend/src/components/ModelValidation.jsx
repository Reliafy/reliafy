import { useEffect, useState } from "react";
import { getModelValidation } from "../api.js";

// "How good is this model?" for regression models (#176): Harrell's C, the
// integrated Brier score against one Kaplan-Meier curve for every unit, and
// the time-dependent AUC. The scores (and their plain readings) come from
// the backend: stored with the fit, or — for a model saved before them —
// computed on request when ``modelId`` is given.
const num = (v, digits = 3) => Number(v).toFixed(digits);
const time = (t) => Number(t).toLocaleString(undefined, { maximumSignificantDigits: 3 });

export default function ModelValidation({ validation, modelId, unit }) {
  const [fetched, setFetched] = useState(null);
  const [error, setError] = useState(null);
  const needsFetch = !validation && !!modelId;

  useEffect(() => {
    if (!needsFetch) return undefined;
    let live = true;
    setFetched(null);
    setError(null);
    getModelValidation(modelId)
      .then((v) => live && setFetched(v))
      .catch((err) => live && setError(err.message));
    return () => {
      live = false;
    };
  }, [needsFetch, modelId]);

  const v = validation || fetched;
  const u = unit ? ` ${unit}` : "";

  let body;
  if (!v && needsFetch && !error) {
    body = <div className="vrow"><p className="vread">Scoring the model against its data…</p></div>;
  } else if (!v || error || !v.available) {
    const reason = error ? "The scores couldn't be loaded." : v?.reason || "Not computed for this model.";
    body = (
      <div className="vrow">
        <p className="vread"><b>Not available.</b> {reason.replace(/^Not available:\s*/, "")}</p>
      </div>
    );
  } else {
    const c = v.concordance;
    const b = v.brier;
    body = (
      <>
        <div className="vrow">
          <div className="vrow-head">
            <span className="gk">Ranking <span className="vterm">Harrell's C</span></span>
            <span className="gv">{num(c.value, 2)}</span>
          </div>
          <p className="vread">{c.reading}</p>
        </div>
        <div className="vrow">
          <div className="vrow-head">
            <span className="gk">Prediction error <span className="vterm">integrated Brier score</span></span>
            <span className="gv">{b ? num(b.model) : "–"}</span>
          </div>
          {b ? (
            <>
              <div className="vsub">
                {num(b.baseline)} with one survival curve for every unit (no covariates) · lower is
                better · from {time(b.from)} to {time(b.to)}{u}
              </div>
              <p className="vread">{b.reading}</p>
            </>
          ) : (
            <p className="vread">Not available: too few distinct failure times to score over.</p>
          )}
        </div>
        {v.auc?.length > 0 && (
          <div className="vrow">
            <div className="vrow-head">
              <span className="gk">Telling failed from running <span className="vterm">time-dependent AUC</span></span>
            </div>
            <div className="vauc">
              {v.auc.map((a) => (
                <span key={a.time}>
                  by {time(a.time)}{u} <b>{num(a.value, 2)}</b>
                </span>
              ))}
            </div>
            <p className="vread">
              How well the model separates units that have failed by then from those still running
              (0.5 is a coin toss, 1 is perfect).
            </p>
          </div>
        )}
        <div className="vfoot">
          {v.note}
          {v.sample_note && <> {v.sample_note}</>}
        </div>
      </>
    );
  }

  return (
    <div className="gof-metrics-card validation-card">
      <div className="gofh">How good is this model?</div>
      {body}
    </div>
  );
}
