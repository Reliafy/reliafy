import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { StartHere } from "../components/FirstRun.jsx";
import { SAMPLE_MODEL, useFirstRun } from "../firstRun.js";
import { TYPE_LABEL, loadAllModels } from "../allModels.js";
import { relativeTime } from "../instrument.js";
import { trackEvent } from "../telemetry.js";
import PageHeader from "../components/ui/PageHeader.jsx";

const ACTIVATED_KEY = "reliafy_activated";
const RECENT = 5;

// The Modelling home (#312): "Start here", then the user's own most recent
// models. The model types are in the sidebar, so they aren't repeated here.
export default function ModellingDashboard() {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    loadAllModels().then(setRows).catch(() => setRows([]));
  }, []);

  // Your own work only — shared samples are under "Start here".
  const own = (rows || []).filter((r) => !r.is_sample);
  // A workspace with nothing of its own (the first-run rule uses this same
  // filter) gets the first-run starts.
  const firstRun = useFirstRun(rows === null ? undefined : own.length > 0);

  // Activation metric: fire once, the moment a workspace gains its first
  // life-data model of its own. localStorage-guarded so it reports a
  // browser's first activation.
  const ownLife = own.some((r) => r.type === "life");
  useEffect(() => {
    if (ownLife && localStorage.getItem(ACTIVATED_KEY) !== "1") {
      localStorage.setItem(ACTIVATED_KEY, "1");
      trackEvent("activated");
    }
  }, [ownLife]);

  const lifeSamples = (rows || []).filter((r) => r.is_sample && r.type === "life");
  const sampleModelId =
    (lifeSamples.find((r) => r.id === SAMPLE_MODEL) || lifeSamples[0])?.id || null;
  const recent = own.slice(0, RECENT);

  return (
    <div className="app">
      <PageHeader title="Modelling" meta="Fit life data, repairable systems, accelerated tests and degradation." />

      <StartHere info={firstRun} sampleModelId={sampleModelId} />

      {recent.length > 0 && (
        <section className="recent-models" aria-labelledby="recent-models-title">
          <div className="recent-models-head">
            <h2 id="recent-models-title">Your recent models</h2>
            <Link to="/modelling/models">All models →</Link>
          </div>
          <ul className="recent-models-list">
            {recent.map((r) => (
              <li key={r.id}>
                <Link className="recent-model" to={r.to}>
                  <span className="recent-model-name">{r.name}</span>
                  <span className="recent-model-kind">{TYPE_LABEL[r.type]} · {r.detail}</span>
                  <span className="recent-model-when">{relativeTime(r.created_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
