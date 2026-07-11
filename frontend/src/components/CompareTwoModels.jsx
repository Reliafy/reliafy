import { useRef, useState } from "react";
import ModelPicker from "./ModelPicker.jsx";
import CompareResult from "./CompareResult.jsx";
import SaveAnalysisButton from "./SaveAnalysisButton.jsx";
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

export default function CompareTwoModels() {
  const [sideA, setSideA] = useState(() => EMPTY_SIDE("Item A"));
  const [sideB, setSideB] = useState(() => EMPTY_SIDE("Item B"));
  const [unit, setUnit] = useState("");
  const [result, setResult] = useState(null);
  const [inputs, setInputs] = useState(null); // specs that produced the result
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const a = await buildSpec(sideA, "Item A");
      const b = await buildSpec(sideB, "Item B");
      setResult(await compareTwoModels(a, b, unit));
      setInputs({ a, b, unit: unit || null });
    } catch (err) {
      setError(err.message);
      setResult(null);
      setInputs(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="strategy-tool">
      <div className="compare-sides">
        <SideEditor tag="a" side={sideA} onChange={setSideA} />
        <SideEditor tag="b" side={sideB} onChange={setSideB} />
      </div>

      <div className="strategy-actions">
        <label className="calc-t">
          <span>Unit (optional)</span>
          <input type="text" placeholder="e.g. Hours" value={unit}
            onChange={(e) => setUnit(e.target.value)} />
        </label>
        <button onClick={run} disabled={loading}>
          {loading ? "Comparing…" : "Compare"}
        </button>
        {result && inputs && (
          <SaveAnalysisButton
            kind="compare_two"
            inputs={inputs}
            defaultName={`${result.a.label} vs ${result.b.label}`}
          />
        )}
      </div>

      {error && <div className="error">{error}</div>}

      {result && <CompareResult result={result} />}
    </div>
  );
}
