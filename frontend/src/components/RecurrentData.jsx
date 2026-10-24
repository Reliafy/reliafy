// A repairable model's Data tab: what it was fitted to (the counts, the
// observation windows, each system's failures) and how, with every parameter.
import { Link } from "react-router-dom";
import { ScrollCard, TablePanel } from "./model/ModelLayouts.jsx";
import { DatasetRows } from "./model/DataTab.jsx";
import { formatNumber } from "../format.js";
import { ciText, familyOf, orderedParams, paramLabel, ratioCiText, ratioText } from "../recurrentResults.js";

const sig = (v) => formatNumber(v, { sig: 4 });

// The model and its settings in words.
export function howWords(r) {
  const fam = familyOf(r);
  const out = [];
  if (r.from_params) {
    out.push(`${r.model?.name || "Model"} made from parameters, not fitted to data: the calculator and the planning tools work, but there's nothing to check it against.`);
  } else {
    out.push(`${r.model?.name || "Model"}, fitted by maximum likelihood.`);
  }
  if (fam === "nhpp") out.push("Minimal repair: each repair puts a system back as it was just before the failure (as bad as old).");
  if (fam === "regression") {
    out.push(`Covariates scale one ${r.baseline?.name || "Crow-AMSAA"} failure rate up or down for each system. Rates "now" are for the fleet's average system.`);
  }
  if (fam === "renewal") {
    out.push(`Imperfect repair${r.lifetime ? ` with a ${r.lifetime} time between failures` : ""}: each repair restores a system somewhere between as good as new and as bad as old.`);
    if (r.options?.m) out.push(`Each repair acts on the last ${r.options.m} failure${Number(r.options.m) === 1 ? "" : "s"}.`);
    if (r.options?.baseline) out.push(`Baseline failure rate: ${r.options.baseline}.`);
  }
  if (r.mcf?.fitted?.simulated) out.push("Its curve of expected failures is simulated (a fixed seed), so the calculator reads it within the fitted range.");
  if (r.bounds_method) {
    out.push(r.bounds_method === "crow"
      ? "Rate bounds: Crow's exact bounds (MIL-HDBK-189C), as the test design allows."
      : "Rate bounds: Wald (delta method).");
  }
  if (r.windows) {
    out.push(`Observed in ${r.windows.windows} windows; ${r.windows.systems_with_gaps} system${r.windows.systems_with_gaps === 1 ? " has" : "s have"} gaps (${formatNumber(r.windows.gap_time)}${r.unit ? ` ${String(r.unit).toLowerCase()}` : ""} not observed).`);
  }
  return out;
}

function Counts({ r, datasetId }) {
  const unit = String(r.unit || "").trim().toLowerCase();
  const rows = [
    ["Systems", r.n_systems],
    ["Failures", r.n_events],
    [r.from_params ? "Horizon" : "Observed to", r.end_of_observation ?? r.horizon, unit],
    r.windows && ["Observation windows", r.windows.windows],
  ].filter((row) => row && row[1] != null);
  return (
    <section className="gof-card mf-flex-none" aria-labelledby="rec-data-counts">
      <div className="gofh mf-card-head">
        <h3 className="mf-card-title" id="rec-data-counts">What it was fitted to</h3>
        {datasetId && <Link className="link" to={`/data/${datasetId}`}>Open the dataset ›</Link>}
      </div>
      {rows.map(([k, v, u]) => (
        <div className="gofr" key={k}><span className="gk">{k}</span><span className="gv">{formatNumber(v, { sig: 6 })}{u ? ` ${u}` : ""}</span></div>
      ))}
      {!rows.length && <p className="mf-note">No data: made from parameters.</p>}
      {unit && <div className="gofr"><span className="gk">Time unit</span><span className="gv">{unit}</span></div>}
    </section>
  );
}

// Each system's failures: against what the model expects over its window, or
// (imperfect repair) with its age and time since its last failure.
function Systems({ r }) {
  const res = r.system_residuals || [];
  const nf = r.next_failure?.units || [];
  const unit = String(r.unit || "").trim().toLowerCase();
  const u = unit ? ` (${unit})` : "";
  if (nf.length) {
    const sorted = [...nf].sort((a, b) => String(a.system).localeCompare(String(b.system), undefined, { numeric: true }));
    return (
      <ScrollCard title="Each system" sub={`${nf.length} · failures and where its history ends`}>
        <table className="mini-table rec-stats-table">
          <thead><tr><th>System</th><th>Failures</th><th>Age now{u}</th><th>Since the last{u}</th></tr></thead>
          <tbody>
            {sorted.map((s) => (
              <tr key={s.system}><td>{s.system}</td><td>{s.failures}</td><td>{formatNumber(s.age)}</td><td>{formatNumber(s.since_failure)}</td></tr>
            ))}
          </tbody>
        </table>
      </ScrollCard>
    );
  }
  if (res.length) {
    const sorted = [...res].sort((a, b) => String(a.system).localeCompare(String(b.system), undefined, { numeric: true }));
    return (
      <ScrollCard title="Each system" sub={`${res.length}${r.n_systems > res.length ? ` of ${r.n_systems}` : ""} · failures and what the model expects`}>
        <table className="mini-table rec-stats-table">
          <thead><tr><th>System</th><th>Failures</th><th>Expected</th></tr></thead>
          <tbody>
            {sorted.map((s) => (
              <tr key={s.system}><td>{s.system}</td><td>{formatNumber(s.failures)}</td><td>{formatNumber(s.expected, { sig: 3 })}</td></tr>
            ))}
          </tbody>
        </table>
      </ScrollCard>
    );
  }
  return null;
}

function Parameters({ r }) {
  const params = orderedParams(r);
  const coefs = r.coefficients || [];
  return (
    <ScrollCard title="Every parameter" sub={params.some((p) => p.ci) ? "with 95% intervals" : null}>
      <table className="mini-table rec-stats-table">
        <thead><tr><th>Parameter</th><th>Estimate</th><th>95% interval</th></tr></thead>
        <tbody>
          {params.map((p) => (
            <tr key={p.name}><td>{paramLabel(r, p.name)}</td><td>{sig(p.value)}</td><td>{ciText(p.ci) || "—"}</td></tr>
          ))}
          {coefs.map((c) => (
            <tr key={c.name}>
              <td>{c.name.replace(": ", " ")} <span className="gof-sub">coefficient</span></td>
              <td>{sig(c.coef)}</td>
              <td>{ciText(c.coef_ci) || "—"}</td>
            </tr>
          ))}
          {coefs.filter((c) => c.ratio != null).map((c) => (
            <tr key={`${c.name}-ratio`}>
              <td>{c.name.replace(": ", " ")} <span className="gof-sub">rate ratio</span></td>
              <td>{ratioText(c.ratio)}</td>
              <td>{ratioCiText(c.ratio_ci) || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {coefs.length > 0 && (
        <p className="mf-note">
          The baseline is a system with every covariate at 0 and each text covariate at its reference level; a
          coefficient is the log of its rate ratio.
        </p>
      )}
    </ScrollCard>
  );
}

export default function RecurrentData({ r, datasetId = null }) {
  const notes = howWords(r);
  const systems = <Systems r={r} />;
  const hasSystems = (r.next_failure?.units || []).length > 0 || (r.system_residuals || []).length > 0;
  return (
    <TablePanel
      main={<>
        <Counts r={r} datasetId={datasetId} />
        {hasSystems ? systems : datasetId ? <DatasetRows datasetId={datasetId} /> : null}
      </>}
      side={
        <>
          <Parameters r={r} />
          <section className="gof-card mf-flex-none" aria-labelledby="rec-data-how">
            <div className="gofh"><h3 className="mf-card-title" id="rec-data-how">How it was fitted</h3></div>
            {notes.map((n, i) => <p className="mf-note" key={i}>{n}</p>)}
          </section>
        </>
      }
    />
  );
}
