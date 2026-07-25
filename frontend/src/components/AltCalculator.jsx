import { useMemo, useState } from "react";
import Plot from "react-plotly.js";
import { evaluateAlt } from "../api.js";

const fmt = (v) =>
  v == null || !Number.isFinite(v)
    ? "—"
    : Math.abs(v) >= 1e-4 || v === 0
      ? Number(v).toLocaleString(undefined, { maximumSignificantDigits: 5 })
      : Number(v).toExponential(3);

const FUNCS = [
  { id: "sf", label: "Reliability R(t)", y: "Reliability" },
  { id: "ff", label: "Unreliability F(t)", y: "Unreliability" },
  { id: "hf", label: "Hazard rate h(t)", y: "Hazard" },
];

// Use-level calculator for an ALT model: enter the field/use stress (below the
// tested stresses) and read the extrapolated reliability curve, characteristic
// / mean / BX lives, and the acceleration factor against a reference (test)
// stress. Evaluation happens on the server (the fitted model lives there).
export default function AltCalculator({ modelId, results }) {
  const stresses = results.stresses || [];
  const levels = results.levels || [];
  const unit = results.unit || "";

  // Sensible defaults: use level = the mildest tested stress; reference = the
  // harshest. (For most accelerations "mild" is the lowest value.)
  const perDim = (j) => levels.map((l) => l.stress[j]).filter((v) => v != null);
  const defUse = stresses.map((_, j) => { const a = perDim(j); return a.length ? Math.min(...a) : 0; });
  const defRef = stresses.map((_, j) => { const a = perDim(j); return a.length ? Math.max(...a) : 0; });

  const [use, setUse] = useState(defUse.map(String));
  const [ref, setRef] = useState(defRef.map(String));
  const [useRef, setUseRef] = useState(true);
  const [active, setActive] = useState("sf");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const run = async () => {
    setBusy(true); setError(null);
    try {
      const u = use.map(Number);
      const rf = useRef ? ref.map(Number) : undefined;
      if (u.some((v) => !Number.isFinite(v))) throw new Error("Enter a number for each use-level stress.");
      setRes(await evaluateAlt(modelId, u, rf));
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  const curves = res?.curves || {};
  const traceX = curves.x || [];
  const traceY = curves[active] || [];
  const layout = useMemo(() => ({
    autosize: true, height: 340,
    margin: { l: 60, r: 20, t: 16, b: 46 },
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "#ffffff",
    xaxis: { title: unit ? `Time (${unit})` : "Time", gridcolor: "#eef1f5", zeroline: false },
    yaxis: { title: FUNCS.find((f) => f.id === active)?.y || "", gridcolor: "#eef1f5" },
    showlegend: false,
  }), [active, unit]);

  const m = res?.metrics || {};
  const af = res?.acceleration_factor;

  return (
    <div className="alt-calc">
      <div className="alt-calc-inputs">
        <div className="alt-stress-grid">
          {stresses.map((s, j) => (
            <label key={s.key} className="login-field">
              <span>Use-level {s.label}</span>
              <input type="number" value={use[j]} inputMode="decimal"
                     onChange={(e) => setUse((cur) => cur.map((v, k) => (k === j ? e.target.value : v)))} />
            </label>
          ))}
        </div>
        <label className="alt-ref-toggle">
          <input type="checkbox" checked={useRef} onChange={(e) => setUseRef(e.target.checked)} />
          <span>Acceleration factor vs a reference stress</span>
        </label>
        {useRef && (
          <div className="alt-stress-grid">
            {stresses.map((s, j) => (
              <label key={s.key} className="login-field">
                <span>Reference {s.label}</span>
                <input type="number" value={ref[j]} inputMode="decimal"
                       onChange={(e) => setRef((cur) => cur.map((v, k) => (k === j ? e.target.value : v)))} />
              </label>
            ))}
          </div>
        )}
        <button onClick={run} disabled={busy}>{busy ? "Computing…" : "Compute at use level"}</button>
        {error && <div className="error">{error}</div>}
      </div>

      {res && (
        <div className="alt-calc-out">
          <div className="alt-metrics">
            <div className="alt-metric"><span className="k">Characteristic life</span><span className="v">{fmt(m.characteristic_life)}{unit ? ` ${unit}` : ""}</span></div>
            <div className="alt-metric"><span className="k">Mean life</span><span className="v">{fmt(m.mean_life)}{unit ? ` ${unit}` : ""}</span></div>
            <div className="alt-metric"><span className="k">B10 life</span><span className="v">{fmt(m.b10)}{unit ? ` ${unit}` : ""}</span></div>
            <div className="alt-metric"><span className="k">B50 (median)</span><span className="v">{fmt(m.b50)}{unit ? ` ${unit}` : ""}</span></div>
            {af && (
              <div className="alt-metric accent">
                <span className="k">Acceleration factor</span>
                <span className="v">{fmt(af.value)}×</span>
              </div>
            )}
          </div>
          <div className="seg" style={{ alignSelf: "flex-start" }}>
            {FUNCS.map((f) => (
              <button key={f.id} className={"seg-btn" + (active === f.id ? " active" : "")}
                      onClick={() => setActive(f.id)}>{f.label}</button>
            ))}
          </div>
          <Plot data={[{ x: traceX, y: traceY, mode: "lines", type: "scatter", line: { color: "#2f6df6", width: 2 } }]}
                layout={layout} useResizeHandler style={{ width: "100%" }}
                config={{ displayModeBar: false, responsive: true }} />
          {curves.warning && <div className="calc-warn">{curves.warning}</div>}
        </div>
      )}
    </div>
  );
}
