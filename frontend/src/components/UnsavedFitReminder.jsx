import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../AuthProvider.jsx";
import { getWorkspace, saveModel } from "../api.js";
import { relativeTime } from "../instrument.js";
import { canSaveAgain, forgetUnsavedFit, loadUnsavedFit } from "../unsavedFit.js";

// Where an unsaved fit is kept: this user's active workspace.
export function useUnsavedFitScope() {
  const { user } = useAuth();
  return `${user?.uid || "local"}:${getWorkspace()}`;
}

// A gentle reminder on the Modelling pages (#434): a fit was left without
// saving. One click saves it (and its data) when the data came along;
// otherwise it offers to fit it again. Dismiss forgets it.
export default function UnsavedFitReminder() {
  const scope = useUnsavedFitScope();
  const navigate = useNavigate();
  const [fit, setFit] = useState(() => loadUnsavedFit(scope));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  if (!fit) return null;

  const dismiss = () => {
    forgetUnsavedFit(scope);
    setFit(null);
  };
  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const file = fit.datasetId ? null : new File([fit.csv], fit.fileName, { type: "text/csv" });
      const model = await saveModel(fit.name, fit.distribution, file, fit.mapping, {
        ...fit.opts, ...(fit.datasetId ? { datasetId: fit.datasetId } : {}),
      });
      forgetUnsavedFit(scope);
      navigate(`/modelling/m/${model.id}`);
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  return (
    <section className="card unsaved-fit" aria-label="Unsaved fit">
      <div className="unsaved-fit-text">
        <b>You left a fit without saving it</b>
        <span>{fit.name} · {relativeTime(fit.at)}</span>
      </div>
      <div className="unsaved-fit-actions">
        {canSaveAgain(fit) ? (
          <button type="button" onClick={save} disabled={saving}>
            {saving ? "Saving…" : fit.datasetId ? "Save it" : "Save it and its data"}
          </button>
        ) : (
          <button type="button" onClick={() => { forgetUnsavedFit(scope); navigate("/modelling/new?mode=data"); }}>
            Fit it again
          </button>
        )}
        <button type="button" className="link" onClick={dismiss} disabled={saving}>Dismiss</button>
      </div>
      {error && <div className="error" style={{ flexBasis: "100%", margin: 0 }}>{error}</div>}
    </section>
  );
}
