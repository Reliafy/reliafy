// A repairable model's Data tab: what it was fitted to (the counts, the
// observation windows, each system's failures) and how, with every parameter.
import { Link } from "react-router-dom";
import { ScrollCard, TablePanel } from "./model/ModelLayouts.jsx";
import { DatasetRows } from "./model/DataTab.jsx";
import { formatNumber } from "../format.js";
import {
  ciText, familyOf, fitSystemsHref, orderedParams, pct, ratioCiText, ratioText, scaledParam, terminationText,
} from "../recurrentResults.js";
import { ciPct } from "../levels.js";

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
    out.push(`Covariates scale one ${r.baseline?.name || "Crow-AMSAA"} failure rate up or down for each system. Rates "now" are for each level of the first category, and for a system at the fleet's average covariates (no real system).`);
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
    ["Systems", r.subset?.systems?.length ? `${r.subset.systems.join(", ")} (${r.subset.systems.length} of ${r.subset.of})` : r.n_systems],
    ["Failures", r.n_events],
    [r.from_params ? "Horizon" : "Observed to", r.end_of_observation ?? r.horizon, unit],
    r.windows && ["Observation windows", r.windows.windows],
  ].filter((row) => row && row[1] != null);
  const ends = terminationText(r);
  return (
    <section className="gof-card mf-flex-none" aria-labelledby="rec-data-counts">
      <div className="gofh mf-card-head">
        <h3 className="mf-card-title" id="rec-data-counts">What it was fitted to</h3>
        {datasetId && <Link className="link" to={`/data/${datasetId}`}>Open the dataset ›</Link>}
      </div>
      {rows.map(([k, v, u]) => (
        <div className="gofr" key={k}><span className="gk">{k}</span><span className="gv">{formatNumber(v, { sig: 6 })}{u ? ` ${u}` : ""}</span></div>
      ))}
      {ends && <div className="gofr"><span className="gk">Record ends</span><span className="gv">{ends.charAt(0).toUpperCase() + ends.slice(1)}</span></div>}
      {!rows.length && <p className="mf-note">No data: made from parameters.</p>}
      {unit && <div className="gofr"><span className="gk">Time unit</span><span className="gv">{unit}</span></div>}
    </section>
  );
}

// Each system's failures: against what the model expects over its window, or
// (imperfect repair) with its age and time since its last failure; with its
// downtime and cost when the data has a column for each (``system_costs``).
// A saved model's rows link to fitting that system by itself.
const money = (v) => (v == null ? "—" : `$${Math.round(v).toLocaleString("en-US")}`);
const hours = (v) => (v == null ? "—" : formatNumber(v, { sig: 4 }));

function FitAlone({ modelId, system }) {
  if (!modelId) return null;
  return <Link className="link" to={fitSystemsHref(modelId, [system])} title={`Fit ${system}'s failures by itself`}>Fit alone</Link>;
}

// Under the table: the fleet's totals and the columns they came from, or
// what the data needs for downtime and cost to show.
function CostNote({ r }) {
  const sc = r.system_costs;
  if (!sc) {
    return (
      <p className="mf-note">
        Downtime and cost per failure aren't in this data. To see each system's hours stopped and cost here, give
        the data a column for each (one number per failure) and pick them under Downtime and cost when you fit.
      </p>
    );
  }
  const miss = Object.entries(sc.missing || {}).filter(([, n]) => n > 0)
    .map(([k, n]) => `${n} failure${n === 1 ? " has" : "s have"} no ${k}`);
  const t = sc.total || {};
  const parts = [
    sc.columns.downtime && `${hours(t.downtime)} h stopped`,
    sc.columns.cost && `${money(t.cost)} in all (${money(t.cost_per_failure)} a failure)`,
  ].filter(Boolean);
  const from = [sc.columns.downtime && `“${sc.columns.downtime}” (hours)`, sc.columns.cost && `“${sc.columns.cost}”`]
    .filter(Boolean).join(" and ");
  return (
    <p className="mf-note">
      {`All these systems: ${formatNumber(t.failures)} failures, ${parts.join(", ")}. From the column${sc.columns.downtime && sc.columns.cost ? "s" : ""} ${from}`}
      {miss.length ? `; ${miss.join(", ")} (left out of the totals).` : "."}
    </p>
  );
}

function Systems({ r, modelId }) {
  const res = r.system_residuals || [];
  const nf = r.next_failure?.units || [];
  const sc = r.system_costs;
  const costBy = new Map((sc?.systems || []).map((s) => [s.system, s]));
  const dt = !!sc?.columns?.downtime;
  const ct = !!sc?.columns?.cost;
  const unit = String(r.unit || "").trim().toLowerCase();
  const u = unit ? ` (${unit})` : "";
  const fitLinks = !!modelId && (r.n_systems || 0) > 1;
  const costHeads = (
    <>
      {dt && <th>Downtime (h)</th>}
      {ct && <th>Cost</th>}
      {ct && <th>Cost a failure</th>}
      {ct && <th>Share of cost</th>}
    </>
  );
  const costCells = (system) => {
    const c = costBy.get(system) || {};
    return (
      <>
        {dt && <td>{hours(c.downtime)}</td>}
        {ct && <td>{money(c.cost)}</td>}
        {ct && <td>{money(c.cost_per_failure)}</td>}
        {ct && <td>{c.cost_share == null ? "—" : pct(c.cost_share)}</td>}
      </>
    );
  };
  const fitHead = fitLinks && <th><span className="sr-only">Fit</span></th>;
  const fitCell = (system) => fitLinks && <td style={{ whiteSpace: "nowrap" }}><FitAlone modelId={modelId} system={system} /></td>;
  // Most cost first when the data has it, else by name.
  const order = (rows) => {
    const byName = [...rows].sort((a, b) => String(a.system).localeCompare(String(b.system), undefined, { numeric: true }));
    if (!sc) return byName;
    const rank = new Map(sc.systems.map((s, k) => [s.system, k]));
    return byName.sort((a, b) => (rank.get(a.system) ?? 1e9) - (rank.get(b.system) ?? 1e9));
  };
  const pick = fitLinks && <Link className="link" to={fitSystemsHref(modelId)}>Fit some systems by themselves ›</Link>;
  if (nf.length) {
    return (
      <ScrollCard title="Each system" sub={`${nf.length} · failures and where its history ends`} actions={pick}>
        <table className="mini-table rec-stats-table">
          <thead><tr><th>System</th><th>Failures</th><th>Age now{u}</th><th>Since the last{u}</th>{costHeads}{fitHead}</tr></thead>
          <tbody>
            {order(nf).map((s) => (
              <tr key={s.system}>
                <td>{s.system}</td><td>{s.failures}</td><td>{formatNumber(s.age)}</td><td>{formatNumber(s.since_failure)}</td>
                {costCells(s.system)}{fitCell(s.system)}
              </tr>
            ))}
          </tbody>
        </table>
        <CostNote r={r} />
      </ScrollCard>
    );
  }
  if (res.length || sc) {
    const rows = res.length ? res : sc.systems.map((s) => ({ system: s.system, failures: s.failures }));
    return (
      <ScrollCard title="Each system" actions={pick}
                  sub={`${rows.length}${r.n_systems > rows.length ? ` of ${r.n_systems}` : ""} · failures${res.length ? " and what the model expects" : ""}`}>
        <table className="mini-table rec-stats-table">
          <thead><tr><th>System</th><th>Failures</th>{res.length > 0 && <th>Expected</th>}{costHeads}{fitHead}</tr></thead>
          <tbody>
            {order(rows).map((s) => (
              <tr key={s.system}>
                <td>{s.system}</td><td>{formatNumber(s.failures)}</td>
                {res.length > 0 && <td>{formatNumber(s.expected, { sig: 3 })}</td>}
                {costCells(s.system)}{fitCell(s.system)}
              </tr>
            ))}
          </tbody>
        </table>
        <CostNote r={r} />
      </ScrollCard>
    );
  }
  return null;
}

function Parameters({ r }) {
  const params = orderedParams(r);
  const coefs = r.coefficients || [];
  return (
    <ScrollCard title="Every parameter" sub={params.some((p) => p.ci) ? `with ${ciPct(r)} intervals` : null}>
      <table className="mini-table rec-stats-table">
        <thead><tr><th>Parameter</th><th>Estimate</th><th>{ciPct(r)} interval</th></tr></thead>
        <tbody>
          {params.map((p) => {
            const d = scaledParam(r, p);
            return <tr key={p.name}><td>{d.label}</td><td>{sig(d.value)}</td><td>{ciText(d.ci) || "—"}</td></tr>;
          })}
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

export default function RecurrentData({ r, datasetId = null, modelId = null }) {
  const notes = howWords(r);
  const systems = <Systems r={r} modelId={datasetId ? modelId : null} />;
  const hasSystems = (r.next_failure?.units || []).length > 0 || (r.system_residuals || []).length > 0 || !!r.system_costs;
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
