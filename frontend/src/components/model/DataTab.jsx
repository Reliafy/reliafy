// The Data tab: what the model was fitted to and how. The counts, the data
// table (scrolling inside its card), how it was fitted (the method and its
// options, the notes that used to sit under "Details") and every parameter
// with its interval.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import CiNote from "../CiNote.jsx";
import PreviewTable from "../PreviewTable.jsx";
import { paramView } from "../LifeSummary.jsx";
import { ScrollCard, TablePanel } from "./ModelLayouts.jsx";
import { getDataset } from "../../api.js";
import { formatNumber, formatPercent } from "../../format.js";
import { bestFitSentence, compareRows } from "../../lifeResults.js";
import { dataWords } from "../../modelFrame.js";
import { unitInText } from "../unitText.js";
import { fmtP } from "../RegressionChecks.jsx";

const fmtCi = (ci) => (ci && ci[0] != null && ci[1] != null ? `${formatNumber(ci[0])}–${formatNumber(ci[1])}` : "—");
const PART = { baseline: "Baseline", coefficients: "Covariate", frailty: "Groups", parameters: "Spline" };

// The adjustments a fit used, and the notes that say what this kind of
// model is, in words.
function howWords(result) {
  const o = result.options || {};
  const out = [];
  const method = o.how && o.how !== "MLE" ? o.how : "maximum likelihood";
  if (!result.params_only && result.kind !== "nonparametric") out.push(`Fitted by ${method}.`);
  const adj = [
    o.offset && "a 3-parameter offset",
    o.lfp && "a limited failure population",
    o.zi && "zero inflation",
    o.fixed && `fixed ${Object.entries(o.fixed).map(([k, v]) => `${k} = ${v}`).join(", ")}`,
  ].filter(Boolean);
  if (adj.length) out.push(`With ${adj.join(", ")}.`);
  const cox = o.cox;
  if (cox) {
    const bits = [cox.tie_method && `${cox.tie_method} ties`, cox.strata && `stratified on ${cox.strata}`,
                  cox.cluster && `clustered by ${cox.cluster}`].filter(Boolean);
    if (bits.length) out.push(`Cox options: ${bits.join(", ")}.`);
  }
  if ((result.selection?.candidates?.length || 0) > 1) {
    out.push(result.selection.summary
      || bestFitSentence(compareRows(result.selection.candidates, result.selection.criterion || "aic")));
  }
  if (result.mixture_summary) out.push(result.mixture_summary);
  if (result.mixture > 1) {
    out.push("A mixture has no covariance matrix, so it reports no confidence bounds: judge it on the AIC against a single fit (Diagnostics).");
  }
  if (result.interval_censored) out.push("Inspection data: each failure lies between two inspections.");
  switch (result.kind) {
    case "nonparametric":
      out.push(`${result.distribution} estimate: no distribution assumed, so no fitted parameters to check.`);
      break;
    case "flexible":
      out.push(`Royston-Parmar spline with ${result.spline?.n_terms ?? 3} terms on the log cumulative hazard. Its coefficients have no physical meaning on their own: read the curve, drawn over the data's own Kaplan-Meier curve.`);
      break;
    case "discrete":
      out.push("Discrete distribution: fitted to whole counts to failure (cycles, shocks or demands), so it has no probability plot.");
      break;
    default:
  }
  if (result.params_only) out.push("Made from parameters, not fitted to data: the functions and life figures work, but there's nothing to check it against.");
  if (result.tvc) {
    const t = result.tvc;
    out.push(`Each item's covariates follow its rows (${t.layout === "timeline" ? "timeline rows" : "start and stop rows"}).`);
  }
  return out;
}

function Counts({ result, split, datasetId }) {
  const s = split || result.split;
  const rows = [];
  if (result.tvc) {
    rows.push(["Items", result.tvc.items], ["Rows", result.tvc.rows], ["Failures", result.tvc.failures]);
  } else if (s && Number.isFinite(s.failed)) {
    rows.push(["Failed", s.failed]);
    if (s.running) rows.push(["Still running", s.running]);
    if (s.other) rows.push(["Other censored", s.other]);
  }
  if (result.n != null) rows.push(["Observations", result.n]);
  if (result.frailty) rows.push([`Groups (${result.frailty.group_column})`, result.frailty.n_groups]);
  return (
    <section className="gof-card mf-flex-none" aria-labelledby="mf-data-counts">
      <div className="gofh mf-card-head">
        <h3 className="mf-card-title" id="mf-data-counts">What it was fitted to</h3>
        {datasetId && <Link className="link" to={`/data/${datasetId}`}>Open the dataset ›</Link>}
      </div>
      {rows.filter(([, v]) => v != null).map(([k, v]) => (
        <div className="gofr" key={k}><span className="gk">{k}</span><span className="gv">{Number(v).toLocaleString()}</span></div>
      ))}
      {!rows.length && <p className="mf-note">{result.params_only ? "No data: made from parameters." : dataWords(result, s) || "—"}</p>}
      {result.unit && (
        <div className="gofr"><span className="gk">Time unit</span><span className="gv">{unitInText(result.unit)}</span></div>
      )}
    </section>
  );
}

// The first rows of the saved dataset, when nothing better is in the result.
export function DatasetRows({ datasetId }) {
  const [ds, setDs] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    if (!datasetId) return undefined;
    let live = true;
    getDataset(datasetId).then((d) => live && setDs(d)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [datasetId]);
  if (!datasetId) return null;
  return (
    <ScrollCard title="The data" sub={ds ? `first ${ds.preview?.length || 0} of ${Number(ds.n_rows).toLocaleString()} rows` : null}>
      {error ? <p className="mf-note">Couldn't load the data: {error}</p>
        : !ds ? <p className="mf-note">Loading…</p>
        : <PreviewTable columns={ds.preview_columns} rows={ds.preview} />}
    </ScrollCard>
  );
}

function FailuresTable({ result }) {
  const e = result.plot?.empirical;
  const u = result.unit ? ` (${unitInText(result.unit)})` : "";
  return (
    <ScrollCard title="The failures" sub={`${e.x.length} · fraction failed by each, from the data (${e.method}) and the model`}>
      <table className="mini-table">
        <thead><tr><th>Time{u}</th><th className="mf-num">Data</th><th className="mf-num">Model</th></tr></thead>
        <tbody>
          {e.x.map((x, i) => (
            <tr key={i}>
              <td>{formatNumber(x, { sig: 4 })}</td>
              <td className="mf-num">{formatPercent(e.F[i], { sig: 3 })}</td>
              <td className="mf-num">{formatPercent(e.model_F[i], { sig: 3 })}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollCard>
  );
}

function LifeTable({ result }) {
  const e = result.estimate || {};
  const u = result.unit ? ` (${unitInText(result.unit)})` : "";
  const table = !!e.at_risk;
  const band = (e.cb_lower || []).some((v) => v != null);
  return (
    <ScrollCard title={result.kind === "flexible" ? "The data's Kaplan-Meier curve" : "Life table"}
                sub={table ? "units at risk and failing at each failure time" : null}>
      <table className="mini-table">
        <thead>
          <tr>
            <th>Time{u}</th>
            {table && <th className="mf-num">At risk</th>}
            {table && <th className="mf-num">Failed</th>}
            <th className="mf-num">R(t)</th>
            {band && <th className="mf-num">95% band</th>}
          </tr>
        </thead>
        <tbody>
          {(e.x || []).map((x, i) => (
            <tr key={i}>
              <td>{formatNumber(x, { sig: 4 })}</td>
              {table && <td className="mf-num">{formatNumber(e.at_risk[i], { sig: 6 })}</td>}
              {table && <td className="mf-num">{formatNumber(e.failed[i], { sig: 6 })}</td>}
              <td className="mf-num">{formatNumber(e.R[i])}</td>
              {band && <td className="mf-num">{e.cb_lower[i] != null ? `${formatNumber(e.cb_lower[i])}–${formatNumber(e.cb_upper[i])}` : "—"}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollCard>
  );
}

function CountsTable({ result }) {
  const k = result.counts;
  return (
    <ScrollCard title="Failures at each count" sub="observed and what the model expects">
      <table className="mini-table">
        <thead>
          <tr><th>Count</th><th className="mf-num">At risk</th><th className="mf-num">Failed</th>
            <th className="mf-num">Expected</th><th className="mf-num">Model's chance</th></tr>
        </thead>
        <tbody>
          {k.k.map((c, i) => (
            <tr key={c}>
              <td>{c}</td>
              <td className="mf-num">{formatNumber(k.at_risk[i], { sig: 6 })}</td>
              <td className="mf-num">{formatNumber(k.failed[i], { sig: 6 })}</td>
              <td className="mf-num">{formatNumber(k.expected[i], { sig: 3 })}</td>
              <td className="mf-num">{formatPercent(k.pmf[i], { sig: 3 })}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollCard>
  );
}

// Every parameter: SurPyval's full table where the fit has one (a spline, a
// semi-parametric or frailty regression), else the parameters and the
// coefficients with their intervals.
function Parameters({ result }) {
  const table = result.coef_table || [];
  const base = { ...result, distribution_id: String(result.distribution_id || "").replace(/_(ph|aft|po|ah|frailty)$/, "") };
  if (table.length) {
    const parts = [...new Set(table.map((r) => r.part))];
    const ratio = result.ratio_label;
    const showRatio = ratio && table.some((r) => r.exp_value != null);
    const showP = table.some((r) => r.p != null);
    return (
      <ScrollCard title="Every parameter" sub="with 95% intervals">
        <table className="mini-table">
          <thead>
            <tr>
              <th>Term</th><th className="mf-num">Estimate</th>
              {showRatio && <th className="mf-num">{ratio[0].toUpperCase() + ratio.slice(1)}</th>}
              <th className="mf-num">95% interval</th>{showP && <th className="mf-num">p</th>}
            </tr>
          </thead>
          <tbody>
            {table.map((r) => {
              const coef = (result.coefficients || []).find((c) => c.name === r.name);
              const ci = r.part === "coefficients" && coef?.ci ? coef.ci : r.ci;
              return (
                <tr key={`${r.part}-${r.name}`}>
                  <td>{parts.length > 1 && <span className="mm-part">{PART[r.part] || r.part} · </span>}{r.name}</td>
                  <td className="mf-num">{formatNumber(r.value, { sig: 4 })}</td>
                  {showRatio && <td className="mf-num">{r.exp_value != null ? formatNumber(r.exp_value, { sig: 4 }) : "—"}</td>}
                  <td className="mf-num">{fmtCi(ci)}</td>
                  {showP && <td className="mf-num">{fmtP(r.p)}</td>}
                </tr>
              );
            })}
          </tbody>
        </table>
      </ScrollCard>
    );
  }
  const params = result.params || [];
  const extra = result.extra_params || [];
  const coefs = result.coefficients || [];
  if (!params.length && !extra.length && !coefs.length) {
    return (
      <section className="gof-card mf-flex-none">
        <div className="gofh">Parameters</div>
        <p className="mf-note">None: {result.kind === "nonparametric" ? "the estimate assumes no distribution." : "this model has none."}</p>
      </section>
    );
  }
  return (
    <ScrollCard title="Every parameter" sub={params.some((p) => p.ci) ? "with 95% intervals" : null}>
      <table className="mini-table">
        <thead><tr><th>Parameter</th><th className="mf-num">Estimate</th><th className="mf-num">95% interval</th></tr></thead>
        <tbody>
          {params.map((p) => {
            const v = paramView(result.kind === "regression" ? base : result, p);
            return <tr key={p.name}><td>{v.label}</td><td className="mf-num">{formatNumber(p.value, { sig: 4 })}</td><td className="mf-num">{v.ci || "—"}</td></tr>;
          })}
          {extra.map((p) => (
            <tr key={p.name}><td>{p.name}</td><td className="mf-num">{formatNumber(p.value, { sig: 4 })}</td><td className="mf-num">—</td></tr>
          ))}
          {coefs.map((c) => (
            <tr key={`c-${c.name}`}>
              <td>{c.name}{c.covariate_unit ? <span className="mm-part"> (per {c.covariate_unit})</span> : null}</td>
              <td className="mf-num">β {formatNumber(c.value, { sig: 4 })}</td>
              <td className="mf-num">{fmtCi(c.ci)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <CiNote params={params} note={result.ci_note} />
    </ScrollCard>
  );
}

// A shared-frailty model: each group's estimated multiplier, highest first.
function GroupFrailties({ frailty }) {
  const groups = frailty.groups || [];
  if (!groups.length) return null;
  return (
    <ScrollCard title={`Each ${frailty.group_column || "group"}'s frailty`}
                sub="above 1: fails sooner than the average group with the same covariates">
      <table className="mini-table">
        <thead><tr><th>{frailty.group_column || "Group"}</th><th className="mf-num">Frailty</th></tr></thead>
        <tbody>
          {groups.map((g) => (
            <tr key={g.label}><td>{g.label}</td><td className="mf-num">{formatNumber(g.frailty, { sig: 3 })}</td></tr>
          ))}
        </tbody>
      </table>
    </ScrollCard>
  );
}

export default function DataTab({ result, split, datasetId = null }) {
  const notes = howWords(result);
  let table = null;
  if (result.plot?.empirical) table = <FailuresTable result={result} />;
  else if (result.estimate?.x?.length) table = <LifeTable result={result} />;
  else if (result.counts?.k?.length) table = <CountsTable result={result} />;
  else if (datasetId) table = <DatasetRows datasetId={datasetId} />;
  return (
    <TablePanel
      main={<>
        <Counts result={result} split={split} datasetId={datasetId} />
        {table}
        {result.frailty && <GroupFrailties frailty={result.frailty} />}
      </>}
      side={
        <>
          <Parameters result={result} />
          {notes.length > 0 && (
            <section className="gof-card mf-flex-none" aria-labelledby="mf-data-how">
              <div className="gofh"><h3 className="mf-card-title" id="mf-data-how">How it was fitted</h3></div>
              {notes.map((n, i) => <p className="mf-note" key={i}>{n}</p>)}
            </section>
          )}
        </>
      }
    />
  );
}
