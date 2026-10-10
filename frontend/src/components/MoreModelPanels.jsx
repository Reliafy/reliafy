import Coefficients from "./Coefficients.jsx";
import LifeAside from "./LifeSummary.jsx";
import Plot from "./Plot.jsx";
import { ResultDetails } from "./ui/ResultSummary.jsx";
import { DATA_INK, fitLine } from "../plotTheme.js";
import { formatNumber } from "../format.js";
import "./MoreModels.css";

// Result panels for the models of #179 / #63: the semi-parametric and
// shared-frailty regressions (their coefficient table and the spread
// between groups) and Royston-Parmar's curve over the data.

const fmtP = (p) => (p == null ? "—" : p < 0.001 ? "< 0.001" : formatNumber(p, { sig: 2 }));
const fmtCi = (ci) => (ci && ci[0] != null && ci[1] != null ? `${formatNumber(ci[0])}–${formatNumber(ci[1])}` : "—");

// Plain names for the table's rows SurPyval names by symbol.
const TERM = { theta: "Spread between groups θ" };
const PART = { baseline: "Baseline", coefficients: "Covariates", frailty: "Groups", parameters: "Spline" };

// The spread between groups, beside the coefficients: θ with its interval
// in words, how alike two units of one group are, and whether the groups
// differ at all.
function FrailtyAside({ frailty }) {
  const ci = frailty.theta_ci;
  return (
    <div className="aside">
      <div className="gof-card">
        <div className="gofh">Group effect</div>
        <div className="gofr">
          <span className="gk">Grouped by</span>
          <span className="gv">{frailty.group_column} · {frailty.n_groups} groups</span>
        </div>
        <div className="gofr">
          <span className="gk" title="How much the groups' hidden multipliers vary">Spread θ</span>
          <span className="gv-col">
            <span className="gv">{formatNumber(frailty.theta)}</span>
            {ci && <span className="param-ci">95% {fmtCi(ci)}</span>}
          </span>
        </div>
        {frailty.kendall_tau != null && (
          <div className="gofr" title="Kendall's τ between two units of the same group: 0 = no more alike than any two units.">
            <span className="gk">Likeness within a group τ</span>
            <span className="gv">{formatNumber(frailty.kendall_tau, { sig: 2 })}</span>
          </div>
        )}
      </div>
      <div className="life-reading">{frailty.reading}</div>
      <p className="life-method">
        Each group shares a hidden multiplier on its failure rate, averaging 1; θ is how much it varies.
        The interval is from the {frailty.theta_ci_method}. The coefficients are hazard ratios within a group.
      </p>
    </div>
  );
}

// Every term SurPyval reports, with its interval and p-value: the tab's main
// content for these models (θ sits in the Group effect panel instead).
function CoefTable({ result }) {
  const rows = (result.coef_table || []).filter((r) => !(result.frailty && r.part === "frailty"));
  const ratio = result.ratio_label;
  const showRatio = ratio && rows.some((r) => r.exp_value != null);
  const showP = rows.some((r) => r.p != null);
  const parts = [...new Set(rows.map((r) => r.part))];
  return (
    <div className="gof-card mm-table-card">
      <div className="gofh">Coefficients</div>
      <div className="rs-table-wrap">
        <table className="mini-table">
          <thead>
            <tr>
              <th>Term</th><th>Estimate</th>{showRatio && <th>{ratio[0].toUpperCase() + ratio.slice(1)}</th>}
              <th>95% interval</th>{showP && <th>p-value</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              // Buckley-James's interval is its bootstrap one, not the table's.
              const coef = (result.coefficients || []).find((c) => c.name === r.name);
              const ci = r.part === "coefficients" && coef?.ci ? coef.ci : r.ci;
              const unit = r.part === "coefficients" && coef?.covariate_unit;
              return (
                <tr key={`${r.part}-${r.name}`}>
                  <td>
                    {parts.length > 1 && <span className="mm-part">{PART[r.part] || r.part} · </span>}
                    {TERM[r.name] || r.name}
                    {unit && <span className="mm-part"> (per {unit})</span>}
                  </td>
                  <td>{formatNumber(r.value, { sig: 4 })}</td>
                  {showRatio && <td>{r.exp_value != null ? formatNumber(r.exp_value, { sig: 4 }) : "—"}</td>}
                  <td>{fmtCi(ci)}</td>
                  {showP && <td>{fmtP(r.p)}</td>}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function GroupTable({ frailty }) {
  const groups = frailty.groups || [];
  if (!groups.length) return null;
  const shown = groups.slice(0, 50);
  return (
    <ResultDetails summary={`Each ${frailty.group_column || "group"}'s frailty`}>
      <p className="rs-note" style={{ marginTop: 0 }}>
        Above 1: that group fails sooner than the average group with the same covariates; below 1, later.
        {groups.length > shown.length ? ` The ${shown.length} highest of ${groups.length}.` : ""}
      </p>
      <div className="rs-table-wrap">
        <table className="mini-table">
          <thead><tr><th>{frailty.group_column || "Group"}</th><th>Frailty</th></tr></thead>
          <tbody>
            {shown.map((g) => (
              <tr key={g.label}><td>{g.label}</td><td>{formatNumber(g.frailty, { sig: 3 })}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </ResultDetails>
  );
}

// The Coefficients tab: unchanged for the everyday regressions; for these
// models, the coefficients beside the group effect (frailty) and the full
// table under Details.
export function RegressionCoefficients({ result }) {
  if (!result.coef_table?.length) {
    return <Coefficients coefficients={result.coefficients} ratioLabel={result.ratio_label} />;
  }
  const noFit = !(result.gof || []).length && result.gof_note;
  const showP = (result.coef_table || []).some((r) => r.p != null);
  return (
    <>
      <div className="detail-panel life-panel mm-coef-panel">
        <div className="mm-coef-main">
          <CoefTable result={result} />
          <p className="life-method mm-note">
            {result.ci_method ? `Covariate intervals: ${result.ci_method}. ` : ""}
            {showP ? "A p-value under 0.05 means the data show that term matters. " : ""}
            {noFit ? result.gof_note : ""}
          </p>
        </div>
        {result.frailty && <FrailtyAside frailty={result.frailty} />}
      </div>
      {result.frailty && <GroupTable frailty={result.frailty} />}
    </>
  );
}

// Royston-Parmar: the fitted curve over the data's own Kaplan-Meier curve,
// beside the life model's usual panel.
export function FlexibleSurvival({ result, split = null, level = 90, onLevel = null, name = null,
                                  modelId = null }) {
  const c = result.functions?.curves || {};
  const est = result.estimate;
  const traces = [];
  if (est?.x?.length) {
    traces.push({
      type: "scatter", mode: "lines", x: est.x, y: est.R, name: est.label || "Kaplan-Meier",
      line: { shape: "hv", color: DATA_INK, width: 1.25 },
      hovertemplate: `%{x:,.4~g}: R=%{y:.3f} (${est.label || "Kaplan-Meier"})<extra></extra>`,
    });
  }
  traces.push(fitLine({ x: c.x, y: c.sf, name: "Fitted spline", hovertemplate: "%{x:,.4~g}: R=%{y:.3f}<extra></extra>" }));
  return (
    <div className="detail-panel life-panel">
      <div className="plotwrap">
        <Plot
          data={traces}
          layout={{
            height: 470,
            xaxis: { title: { text: result.unit ? `Time (${result.unit})` : "Time" }, rangemode: "tozero" },
            yaxis: { title: { text: "Reliability, R(t)" }, range: [0, 1.02] },
            showlegend: true,
            legend: { x: 1, xanchor: "right", y: 1, yanchor: "top", bgcolor: "rgba(255,255,255,0.8)" },
          }}
          download={`${name || result.distribution} — survival curve`}
        />
      </div>
      {/* The spline's coefficients mean nothing on their own (they're under
          Details): the panel gives its size, the data, the fit and the life. */}
      <LifeAside
        result={{ ...result, params: [], extra_params: [{ name: "Spline terms", value: result.spline?.n_terms ?? 3 }] }}
        split={split} level={level} onLevel={onLevel} modelId={modelId} name={name}
      />
    </div>
  );
}
