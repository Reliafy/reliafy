import Select from "./Select.jsx";
import { useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import ModelPicker from "./ModelPicker.jsx";
import CompareResult, { COLORS } from "./CompareResult.jsx";
import SaveAnalysisButton from "./SaveAnalysisButton.jsx";
import { getColumns, compareTwoModels, SPREADSHEET_ACCEPT } from "../api.js";
import { useSpreadsheet } from "./ExcelSheetPicker.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { modelFromSearch, plainName } from "../modelNext.js";
import { guessLifeColumns } from "../datasetGuess.js";
import { columnFacts } from "../lifeData.js";
import { parseColumn, statusReading } from "../compareData.js";


// Editor for one side of the comparison: a parametric non-repairable model, or a CSV of
// raw times fit non-parametrically (Kaplan–Meier).
// Both sides start on "Saved model" (#294): side A with the one a link asked
// for (``wanted``) or the one used last chosen, side B for the user to pick. A saved model names its side, unless
// the side was named by hand.
function SideEditor({ tag, side, onChange, wanted = null, onUnit = null }) {
  const inputRef = useRef(null);
  const set = (patch) => onChange({ ...side, ...patch });
  const { toCsv, modal: sheetModal } = useSpreadsheet();

  const pickFile = async (picked) => {
    if (!picked) return;
    const f = await toCsv(picked);
    if (!f) return;
    try {
      const cols = await getColumns(f);
      // The time and status columns guessed as the fit's Data step guesses them.
      const facts = columnFacts(cols);
      const g = guessLifeColumns((cols.columns || []).map((name) => ({ name, ...facts[name] })));
      set({
        file: f,
        columns: cols.columns,
        facts,
        timeCol: g.x || cols.columns[0] || "",
        censorCol: g.c || "",
      });
    } catch {
      set({ file: f, columns: [], facts: {}, timeCol: "", censorCol: "" });
    }
  };

  return (
    <div className="compare-side">
      <div className="compare-side-head">
        <span className="combo-dot" style={{ background: COLORS[tag] }} />
        <input
          className="compare-label"
          value={side.label}
          placeholder={tag === "a" ? "Item A" : "Item B"}
          onChange={(e) => set({ label: e.target.value })}
        />
      </div>

      <SegmentedControl
        label="Source"
        value={side.mode}
        onChange={(mode) => set({ mode })}
        options={[
          { value: "model", label: "Model" },
          { value: "data", label: "Data (non-parametric)" },
        ]}
      />

      {side.mode === "model" ? (
        <ModelPicker
          value={side.model}
          preferSaved
          autoPick={tag === "a"}
          wanted={wanted}
          onChange={(m) => {
            const auto = [tag === "a" ? "Item A" : "Item B", "", plainName(side.model?.name)].includes(side.label);
            set({ model: m, ...(m?.source === "saved" && auto ? { label: plainName(m.name) } : {}) });
            if (m?.unit) onUnit?.(m.unit);
          }}
        />
      ) : (
        <div className="compare-data">
          <button className="secondary" onClick={() => inputRef.current?.click()}>
            {side.file ? side.file.name : "Upload CSV or Excel"}
          </button>
          <input
            ref={inputRef}
            type="file"
            accept={`.csv,text/csv,${SPREADSHEET_ACCEPT}`}
            hidden
            onChange={(e) => { pickFile(e.target.files?.[0]); e.target.value = ""; }}
          />
          {sheetModal}
          {side.columns?.length > 0 && (
            <div className="compare-cols">
              <label className="calc-t">
                <span>Time column</span>
                <Select
                  value={side.timeCol}
                  onChange={(v) => set({ timeCol: v })}
                  options={side.columns}
                />
              </label>
              <label className="calc-t">
                <span>Failed or still running? (optional)</span>
                <Select
                  value={side.censorCol}
                  onChange={(v) => set({ censorCol: v })}
                  options={[{ value: "", label: "— every row failed —" }, ...side.columns]}
                />
              </label>
              {side.censorCol && statusReading(side.facts?.[side.censorCol]?.values, side.censorCol) && (
                <p className="hint" role="status">
                  Read as: {statusReading(side.facts[side.censorCol].values, side.censorCol)}.
                </p>
              )}
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
  facts: {},
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
  if (!m || !m.distribution_id) throw new Error(`${label}: choose a non-repairable model.`);
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
  const wanted = modelFromSearch(useLocation().search);

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
        {/* A saved model brings its unit, unless one is already set. */}
        <SideEditor tag="a" side={sideA} onChange={setSideA} wanted={wanted} onUnit={(u) => setUnit((v) => v || u)} />
        <SideEditor tag="b" side={sideB} onChange={setSideB} onUnit={(u) => setUnit((v) => v || u)} />
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
      </div>

      {error && <div className="error">{error}</div>}

      {result && (
        <CompareResult
          result={result}
          actions={inputs && (
            <SaveAnalysisButton
              kind="compare_two"
              inputs={inputs}
              defaultName={`${result.a.label} vs ${result.b.label}`}
            />
          )}
        />
      )}
    </div>
  );
}
