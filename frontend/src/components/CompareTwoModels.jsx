import { useRef, useState } from "react";
import Plot from "react-plotly.js";
import ModelPicker from "./ModelPicker.jsx";
import { getColumns, compareTwoModels } from "../api.js";

const COLORS = { a: "#0284c7", b: "#db2777" };

const fmt = (v) =>
  v == null
    ? "—"
    : Math.abs(v) >= 1e-4 || v === 0
    ? Number(v).toPrecision(5)
    : Number(v).toExponential(3);

// Minimal CSV parse: pull a numeric column (and an optional 0/1 censor column).
function parseColumn(text, col, censorCol) {
  const lines = text.replace(/\r/g, "").split("\n").filter((l) => l.trim());
  const headers = lines[0].split(",").map((s) => s.trim());
  const xi = headers.indexOf(col);
  const ci = censorCol ? headers.indexOf(censorCol) : -1;
  const x = [];
  const c = [];
  for (let i = 1; i < lines.length; i++) {
    const cells = lines[i].split(",");
    const v = Number(cells[xi]);
    if (!Number.isFinite(v)) continue;
    x.push(v);
    if (ci >= 0) {
      const cv = Number(cells[ci]);
      c.push(Number.isFinite(cv) ? cv : 0);
    }
  }
  return ci >= 0 ? { x, c } : { x };
}

// Editor for one side of the comparison: a parametric life model, or a CSV of
// raw times fit non-parametrically (Kaplan–Meier).
function SideEditor({ tag, side, onChange }) {
  const inputRef = useRef(null);
  const set = (patch) => onChange({ ...side, ...patch });

  const pickFile = async (f) => {
    if (!f) return;
    try {
      const cols = await getColumns(f);
      set({
        file: f,
        columns: cols.columns,
        timeCol: cols.columns[0] || "",
        censorCol: "",
      });
    } catch {
      set({ file: f, columns: [], timeCol: "", censorCol: "" });
    }
  };

  return (
    <div className="compare-side">
      <div className="compare-side-head" style={{ color: COLORS[tag] }}>
        <span className="combo-dot" style={{ background: COLORS[tag] }} />
        <input
          className="compare-label"
          value={side.label}
          placeholder={tag === "a" ? "Item A" : "Item B"}
          onChange={(e) => set({ label: e.target.value })}
        />
      </div>

      <div className="seg">
        <button
          className={"seg-btn" + (side.mode === "model" ? " active" : "")}
          onClick={() => set({ mode: "model" })}
        >
          Model
        </button>
        <button
          className={"seg-btn" + (side.mode === "data" ? " active" : "")}
          onClick={() => set({ mode: "data" })}
        >
          Data (non-parametric)
        </button>
      </div>

      {side.mode === "model" ? (
        <ModelPicker
          value={side.model}
          onChange={(m) => set({ model: m })}
        />
      ) : (
        <div className="compare-data">
          <button className="secondary" onClick={() => inputRef.current?.click()}>
            {side.file ? side.file.name : "Upload CSV"}
          </button>
          <input
            ref={inputRef}
            type="file"
            accept=".csv,text/csv"
            hidden
            onChange={(e) => pickFile(e.target.files?.[0])}
          />
          {side.columns?.length > 0 && (
            <div className="compare-cols">
              <label className="calc-t">
                <span>Time column</span>
                <div className="select-wrap">
                  <select
                    value={side.timeCol}
                    onChange={(e) => set({ timeCol: e.target.value })}
                  >
                    {side.columns.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
              </label>
              <label className="calc-t">
                <span>Censor column (optional)</span>
                <div className="select-wrap">
                  <select
                    value={side.censorCol}
                    onChange={(e) => set({ censorCol: e.target.value })}
                  >
                    <option value="">— none —</option>
                    {side.columns.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
              </label>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const EMPTY_SIDE = (label) => ({
  label,
  mode: "model",
  model: null,
  file: null,
  columns: [],
  timeCol: "",
  censorCol: "",
});

async function buildSpec(side, fallback) {
  const label = side.label || fallback;
  if (side.mode === "data") {
    if (!side.file || !side.timeCol)
      throw new Error(`${label}: upload a CSV and choose the time column.`);
    const text = await side.file.text();
    const parsed = parseColumn(text, side.timeCol, side.censorCol || null);
    if (!parsed.x.length) throw new Error(`${label}: no numeric values in that column.`);
    return { label, kind: "nonparametric", x: parsed.x, c: parsed.c || null };
  }
  const m = side.model;
  if (!m || !m.distribution_id) throw new Error(`${label}: choose a life model.`);
  if (m.kind === "regression")
    throw new Error(`${label}: proportional-hazards models aren't supported here.`);
  return {
    label: side.label || m.distribution || fallback,
    kind: "parametric",
    distribution_id: m.distribution_id,
    params: m.params,
  };
}

const METRICS = [
  { id: "b10", label: "B10 life" },
  { id: "median", label: "Median" },
  { id: "mttf", label: "MTTF" },
];

export default function CompareTwoModels() {
  const [sideA, setSideA] = useState(() => EMPTY_SIDE("Item A"));
  const [sideB, setSideB] = useState(() => EMPTY_SIDE("Item B"));
  const [unit, setUnit] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const a = await buildSpec(sideA, "Item A");
      const b = await buildSpec(sideB, "Item B");
      setResult(await compareTwoModels(a, b, unit));
    } catch (err) {
      setError(err.message);
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const u = result?.unit ? ` (${result.unit})` : "";
  let traces = [];
  let layout = {};
  if (result) {
    traces = [
      {
        x: result.time,
        y: result.a.sf,
        mode: "lines",
        line: { color: COLORS.a, width: 2.5 },
        name: result.a.label,
        type: "scatter",
        connectgaps: false,
      },
      {
        x: result.time,
        y: result.b.sf,
        mode: "lines",
        line: { color: COLORS.b, width: 2.5 },
        name: result.b.label,
        type: "scatter",
        connectgaps: false,
      },
    ];
    const xc = result.verdict.crossover_time;
    layout = {
      autosize: true,
      height: 420,
      margin: { l: 64, r: 20, t: 20, b: 70 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "#ffffff",
      font: { color: "#334155", family: "Inter, system-ui, sans-serif" },
      showlegend: true,
      legend: { orientation: "h", y: -0.2 },
      xaxis: {
        title: { text: `t${u}`, standoff: 12 },
        gridcolor: "#e2e8f0",
        zeroline: false,
      },
      yaxis: {
        title: { text: "Reliability, R(t)", standoff: 12 },
        gridcolor: "#e2e8f0",
        range: [0, 1.02],
        zeroline: false,
      },
      shapes:
        xc == null
          ? []
          : [
              {
                type: "line",
                x0: xc,
                x1: xc,
                yref: "paper",
                y0: 0,
                y1: 1,
                line: { color: "#94a3b8", width: 1, dash: "dot" },
              },
            ],
    };
  }

  return (
    <div className="strategy-tool">
      <div className="compare-sides">
        <SideEditor tag="a" side={sideA} onChange={setSideA} />
        <SideEditor tag="b" side={sideB} onChange={setSideB} />
      </div>

      <div className="strategy-actions">
        <label className="calc-t">
          <span>Unit (optional)</span>
          <input
            type="text"
            placeholder="e.g. Hours"
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
          />
        </label>
        <button onClick={run} disabled={loading}>
          {loading ? "Comparing…" : "Compare"}
        </button>
      </div>

      {error && <div className="error">{error}</div>}

      {result && (
        <>
          <div
            className={
              "strategy-reco" +
              (result.verdict.more_reliable === "mixed" ? " strategy-reco-warn" : "")
            }
          >
            <span className="strategy-reco-icon">
              {result.verdict.more_reliable === "mixed" ? "⇄" : "✓"}
            </span>
            <span>{result.verdict.text}</span>
          </div>

          {result.tests &&
            (result.tests.available ? (
              <div className="compare-tests">
                <div className="rbd-section-head">
                  Test of difference (log-rank)
                </div>
                <div
                  className={
                    "strategy-reco" +
                    (result.tests.significant ? "" : " strategy-reco-warn")
                  }
                >
                  <span className="strategy-reco-icon">
                    {result.tests.significant ? "✓" : "≈"}
                  </span>
                  <span>{result.tests.summary}</span>
                </div>
                <table className="calc-table">
                  <thead>
                    <tr>
                      <th>Test</th>
                      <th>χ² statistic</th>
                      <th>dof</th>
                      <th>p-value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.tests.results.map((r) => (
                      <tr key={r.id}>
                        <td className="calc-row-label">
                          {r.label}
                          {r.id === result.tests.primary ? " ★" : ""}
                        </td>
                        <td>{fmt(r.statistic)}</td>
                        <td>{r.dof}</td>
                        <td className={r.p_value < result.tests.alpha ? "strategy-best" : ""}>
                          {r.p_value < 1e-4
                            ? r.p_value.toExponential(2)
                            : r.p_value.toFixed(4)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="muted-line">
                  H₀: the two have the same survival distribution. A small
                  p-value (&lt; {result.tests.alpha}) rejects it — the difference
                  is unlikely to be chance. Gehan–Wilcoxon weights early
                  differences; Tarone–Ware is in between.
                </p>
              </div>
            ) : (
              <p className="muted-line compare-tests">{result.tests.reason}</p>
            ))}

          <Plot
            data={traces}
            layout={layout}
            config={{ displayModeBar: true, responsive: true }}
            style={{ width: "100%" }}
            useResizeHandler
          />

          <table className="calc-table strategy-table">
            <thead>
              <tr>
                <th>Metric{u}</th>
                <th style={{ color: COLORS.a }}>{result.a.label}</th>
                <th style={{ color: COLORS.b }}>{result.b.label}</th>
              </tr>
            </thead>
            <tbody>
              {METRICS.map((m) => {
                const va = result.a.metrics[m.id];
                const vb = result.b.metrics[m.id];
                const restricted =
                  m.id === "mttf" &&
                  (result.a.metrics.mttf_restricted ||
                    result.b.metrics.mttf_restricted);
                return (
                  <tr key={m.id}>
                    <td className="calc-row-label">
                      {m.label}
                      {restricted ? " *" : ""}
                    </td>
                    <td className={va != null && vb != null && va >= vb ? "strategy-best" : ""}>
                      {fmt(va)}
                    </td>
                    <td className={va != null && vb != null && vb > va ? "strategy-best" : ""}>
                      {fmt(vb)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {(result.a.metrics.mttf_restricted || result.b.metrics.mttf_restricted) && (
            <p className="muted-line">
              * MTTF from non-parametric data is a restricted mean (area under the
              Kaplan–Meier curve) and can understate the true mean when the data
              is censored.
            </p>
          )}
        </>
      )}
    </div>
  );
}
