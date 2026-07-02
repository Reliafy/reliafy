import { useMemo, useState } from "react";
import Plot from "react-plotly.js";
import { analyzeRbd } from "../api.js";
import ValidationPanel from "./RbdValidation.jsx";
import CovariatesModal from "./CovariatesModal.jsx";

// Linear interpolation of y at xq on the (x, y) grid (null y = gap).
function interp(x, y, xq) {
  if (!x || !y || xq < x[0] || xq > x[x.length - 1]) return null;
  for (let i = 1; i < x.length; i++) {
    if (xq <= x[i]) {
      const y0 = y[i - 1];
      const y1 = y[i];
      if (y0 == null || y1 == null) return null;
      const x0 = x[i - 1];
      const x1 = x[i];
      const f = x1 === x0 ? 0 : (xq - x0) / (x1 - x0);
      return y0 + f * (y1 - y0);
    }
  }
  return null;
}

const fmt = (v) =>
  v == null
    ? "—"
    : Math.abs(v) >= 1e-4 || v === 0
    ? v.toPrecision(5)
    : v.toExponential(3);

const FUNCS = [
  { id: "sf", label: "Reliability, R(t)" },
  { id: "ff", label: "Unreliability, F(t)" },
];
const NODE_COLORS = ["#0284c7", "#16a34a", "#db2777", "#d97706", "#7c3aed", "#0891b2"];


function Results({ result, t, tMax, conditionalAge = 0 }) {
  const x = result.time;
  const [active, setActive] = useState("sf");
  const unit = result.unit;
  const cond = conditionalAge > 0;
  const sLabel = `${conditionalAge}${unit ? ` ${unit}` : ""}`;
  // When conditioning, the x-axis is additional time beyond the survived age s.
  const tLabel = cond
    ? `additional time${unit ? ` (${unit})` : ""}`
    : unit
    ? `t (${unit})`
    : "t";
  const baseLabel = FUNCS.find((f) => f.id === active)?.label || active;
  const activeLabel = cond
    ? baseLabel.replace("R(t)", `R(t | ${sLabel})`).replace("F(t)", `F(t | ${sLabel})`)
    : baseLabel;

  const idToLabel = useMemo(
    () => Object.fromEntries((result.nodes || []).map((n) => [n.id, n.label])),
    [result.nodes]
  );

  const sysY = active === "sf" ? result.system.sf : result.system.ff;
  const sysAtT = t == null ? null : interp(x, sysY, Number(t));

  // System curve (bold) plus a faint curve per node.
  const traces = [
    {
      x,
      y: sysY,
      mode: "lines",
      line: { color: "#0f172a", width: 3 },
      name: "System",
      type: "scatter",
      connectgaps: false,
    },
  ];
  (result.nodes || []).forEach((n, i) => {
    const y = active === "sf" ? n.sf : n.sf.map((v) => (v == null ? null : 1 - v));
    traces.push({
      x,
      y,
      mode: "lines",
      line: { color: NODE_COLORS[i % NODE_COLORS.length], width: 1.25, dash: "dot" },
      name: n.label,
      type: "scatter",
      connectgaps: false,
      opacity: 0.7,
    });
  });
  if (sysAtT != null) {
    traces.push({
      x: [Number(t)],
      y: [sysAtT],
      mode: "markers",
      marker: { color: "#0f172a", size: 9, line: { color: "#fff", width: 1 } },
      type: "scatter",
      showlegend: false,
      hoverinfo: "y",
    });
  }

  const layout = {
    autosize: true,
    height: 440,
    margin: { l: 64, r: 20, t: 20, b: 70 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "#ffffff",
    font: { color: "#334155", family: "Inter, system-ui, sans-serif" },
    showlegend: true,
    legend: { orientation: "h", y: -0.18 },
    xaxis: {
      title: { text: tLabel, standoff: 12 },
      automargin: true,
      gridcolor: "#e2e8f0",
      linecolor: "#cbd5e1",
      range: [0, tMax != null ? Number(tMax) : x[x.length - 1]],
      zeroline: false,
    },
    yaxis: {
      title: { text: activeLabel, standoff: 12 },
      automargin: true,
      gridcolor: "#e2e8f0",
      linecolor: "#cbd5e1",
      range: [0, 1.02],
      zeroline: false,
    },
    shapes:
      t == null
        ? []
        : [
            {
              type: "line",
              x0: Number(t),
              x1: Number(t),
              yref: "paper",
              y0: 0,
              y1: 1,
              line: { color: "#94a3b8", width: 1, dash: "dot" },
            },
          ],
  };

  const importance = result.importance || {};
  const impNodes = Object.keys(importance.birnbaum || {});

  return (
    <div className="calc">
      <div className="params">
        <div className="stat">
          <div className="value">{fmt(result.mttf)}</div>
          <div className="name">
            {cond ? "Mean residual life" : "MTTF"}
            {unit ? ` (${unit})` : ""}
          </div>
        </div>
        <div className="stat">
          <div className="value">{fmt(sysAtT)}</div>
          <div className="name">
            {active === "sf" ? "R" : "F"}(t={t ?? "—"}
            {cond ? ` | ${sLabel}` : ""})
          </div>
        </div>
        <div className="stat">
          <div className="value">{(result.nodes || []).length}</div>
          <div className="name">components</div>
        </div>
      </div>

      <div className="calc-controls">
        <div className="seg">
          {FUNCS.map((f) => (
            <button
              key={f.id}
              className={"seg-btn" + (active === f.id ? " active" : "")}
              onClick={() => setActive(f.id)}
              title={f.label}
            >
              {f.id === "sf" ? "R(t)" : "F(t)"}
            </button>
          ))}
        </div>
      </div>

      <Plot
        data={traces}
        layout={layout}
        config={{ displayModeBar: true, responsive: true }}
        style={{ width: "100%" }}
        useResizeHandler
      />

      {impNodes.length > 0 && (
        <div className="rbd-importance">
          <div className="rbd-section-head">
            Importance at t = {fmt(importance.time)}
            {unit ? ` ${unit}` : ""}
          </div>
          <table className="calc-table">
            <thead>
              <tr>
                <th>Component</th>
                <th title="Birnbaum importance">Birnbaum</th>
                <th title="Fussell-Vesely importance">Fussell-Vesely</th>
              </tr>
            </thead>
            <tbody>
              {impNodes.map((id) => (
                <tr key={id}>
                  <td className="calc-row-label">{idToLabel[id] || id}</td>
                  <td>{fmt(importance.birnbaum?.[id])}</td>
                  <td>{fmt(importance.fussell_vesely?.[id])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="rbd-sets">
        <div className="rbd-set">
          <div className="rbd-section-head">Minimal path sets</div>
          <ul>
            {result.structure.min_path_sets.map((s, i) => (
              <li key={i}>{s.join(" · ")}</li>
            ))}
          </ul>
        </div>
        <div className="rbd-set">
          <div className="rbd-section-head">Minimal cut sets</div>
          <ul>
            {result.structure.min_cut_sets.map((s, i) => (
              <li key={i}>{s.join(" · ")}</li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

// RBD calculator tab. Validation is performed on the Builder tab; this tab
// consumes the shared result (``validation`` + ``stale``) and only offers the
// reliability calculation once the diagram is a valid, analytically solvable
// RBD.
export default function RbdCalculator({ graph, validation, stale }) {
  const [result, setResult] = useState(null);
  const [phase, setPhase] = useState("idle"); // idle | calculating | error
  const [error, setError] = useState(null);
  const [tMax, setTMax] = useState(""); // x-axis 'to' limit (blank = auto)
  const [evalT, setEvalT] = useState(""); // time at which R(t)/F(t) is read off
  const [condAge, setCondAge] = useState(""); // conditional survival age s
  const [covValues, setCovValues] = useState({}); // {nodeId: {covName: value}}
  const [calcSig, setCalcSig] = useState(null); // inputs used for the last calc
  const [showCov, setShowCov] = useState(false);

  const unitLabel = graph.unit ? ` (${graph.unit})` : "";
  const canCalculate = !!validation?.can_calculate && !stale;

  // Nodes backed by a proportional-hazards model need covariate values before
  // they can be evaluated.
  const covNodes = useMemo(
    () =>
      (graph.nodes || [])
        .filter(
          (n) =>
            n.data?.model?.kind === "regression" &&
            (n.data.model.covariates || []).length
        )
        .map((n) => ({
          id: n.id,
          label: n.data.label || n.id,
          covariates: n.data.model.covariates,
        })),
    [graph.nodes]
  );

  const covValue = (node, c) => covValues[node.id]?.[c.name] ?? c.default;

  // The covariate payload sent to the backend (filled with defaults).
  const covPayload = () => {
    const out = {};
    for (const node of covNodes) {
      out[node.id] = {};
      for (const c of node.covariates) out[node.id][c.name] = covValue(node, c);
    }
    return out;
  };

  // Signature of the calculation inputs, so we can tell when the shown result
  // is out of date with the current "To" / covariate / conditional selections.
  const inputSig = JSON.stringify({ t: tMax, s: condAge, cov: covPayload() });
  const dirty = result != null && calcSig != null && inputSig !== calcSig;

  const runCalculation = async () => {
    setPhase("calculating");
    setError(null);
    try {
      const cov = covPayload();
      const s = condAge === "" ? null : Number(condAge);
      const res = await analyzeRbd(
        graph,
        tMax === "" ? null : Number(tMax),
        cov,
        s
      );
      setResult(res);
      let usedTMax = tMax;
      // Prefill the prompts with the range actually used so the user can see
      // and adjust them.
      const limit = res.time[res.time.length - 1];
      if (tMax === "") {
        usedTMax = Number(limit.toPrecision(4));
        setTMax(usedTMax);
      }
      if (evalT === "") setEvalT(Number((limit / 2).toPrecision(4)));
      setCalcSig(JSON.stringify({ t: usedTMax, s: condAge, cov }));
      setPhase("idle");
    } catch (err) {
      setError(err.message);
      setPhase("error");
    }
  };

  return (
    <div className="rbd-calc">
      <div className="rbd-calc-actions">
        <button
          onClick={runCalculation}
          disabled={!canCalculate || phase === "calculating"}
          title={
            canCalculate
              ? "Run the reliability calculation"
              : "Validate the RBD on the Builder tab first"
          }
        >
          {phase === "calculating"
            ? "Calculating…"
            : result && !stale
            ? "Recalculate"
            : "Calculate"}
        </button>
        {dirty && (
          <span className="hint">Recalculate to apply your changes.</span>
        )}
      </div>

      {canCalculate && covNodes.length > 0 && (
        <div className="rbd-cov-bar">
          <button className="secondary" onClick={() => setShowCov(true)}>
            Set covariates
          </button>
          <span className="hint">
            {covNodes.length} proportional-hazards node
            {covNodes.length === 1 ? "" : "s"} —{" "}
            {covNodes
              .map(
                (node) =>
                  `${node.label}: ` +
                  node.covariates
                    .map((c) => `${c.name}=${covValue(node, c)}`)
                    .join(", ")
              )
              .join(" · ")}
          </span>
        </div>
      )}

      {canCalculate && (
        <div className="calc-controls rbd-calc-inputs">
          <label className="calc-t">
            <span>To{unitLabel} — x-axis limit</span>
            <input
              type="number"
              min="0"
              step="any"
              placeholder="auto"
              value={tMax}
              onChange={(e) => setTMax(e.target.value)}
            />
          </label>
          <label className="calc-t">
            <span>Evaluate at t{unitLabel}</span>
            <input
              type="number"
              min="0"
              max={tMax || undefined}
              step="any"
              value={evalT}
              onChange={(e) => setEvalT(e.target.value)}
            />
          </label>
          <label className="calc-t">
            <span>Given survived to{unitLabel}</span>
            <input
              type="number"
              min="0"
              step="any"
              placeholder="0"
              value={condAge}
              onChange={(e) => setCondAge(e.target.value)}
            />
          </label>
        </div>
      )}

      {!validation && (
        <p className="muted-line">
          Validate the RBD on the Builder tab to confirm it is a valid,
          analytically solvable diagram before calculating.
        </p>
      )}

      {validation && <ValidationPanel validation={validation} stale={stale} />}

      {validation && !canCalculate && (
        <p className="hint">
          Calculation is disabled until the diagram is a valid, analytically
          solvable RBD — validate it on the Builder tab.
        </p>
      )}

      {error && <div className="card error">{error}</div>}

      {result && !stale && (
        <Results
          result={result}
          t={evalT === "" ? null : Number(evalT)}
          tMax={tMax === "" ? null : Number(tMax)}
          conditionalAge={result.conditional_age || 0}
        />
      )}

      {showCov && (
        <CovariatesModal
          covNodes={covNodes}
          values={covValues}
          onApply={(v) => {
            setCovValues(v);
            setShowCov(false);
          }}
          onClose={() => setShowCov(false)}
        />
      )}
    </div>
  );
}
