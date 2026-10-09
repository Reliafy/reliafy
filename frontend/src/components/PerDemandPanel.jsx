import { useEffect, useState } from "react";
import { createPerDemandModel, getDataset, listDatasets } from "../api.js";
import SegmentedControl from "./ui/SegmentedControl.jsx";

const isCount = (v, min) => v !== "" && Number.isInteger(Number(v)) && Number(v) >= min;
const pct = (v) => `${(v * 100).toFixed(v > 0.99 || v < 0.01 ? 2 : 1)}%`;

// Per-demand (Binomial) reliability for one-shot and protective equipment,
// where "reliability" is per demand, not over time. One count, or several
// batches of demands (sites, lots of different sizes, test campaigns) pooled
// into one failure probability with exact bounds (#233) -- entered here or
// read from a dataset with one row per batch. Rendered as a page panel; calls
// onCreated with the saved model.
export default function PerDemandPanel({ onCreated, onBack }) {
  const [name, setName] = useState("");
  const [source, setSource] = useState("enter"); // "enter" | "dataset"
  const [rows, setRows] = useState([{ label: "", demands: "", failures: "" }]);
  const [conf, setConf] = useState("95"); // confidence % of the exact bounds
  const [datasets, setDatasets] = useState(null);
  const [datasetId, setDatasetId] = useState("");
  const [columns, setColumns] = useState([]);
  const [cols, setCols] = useState({ demands: "", failures: "", batch: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (source !== "dataset" || datasets !== null) return;
    listDatasets().then((d) => setDatasets(d.datasets || [])).catch(() => setDatasets([]));
  }, [source, datasets]);

  const pickDataset = async (id) => {
    setDatasetId(id);
    setColumns([]);
    setCols({ demands: "", failures: "", batch: "" });
    if (!id) return;
    try {
      const full = await getDataset(id);
      const c = full.preview_columns || [];
      setColumns(c);
      const find = (re) => c.find((n) => re.test(n)) || "";
      setCols({ demands: find(/demand|trial|test|n$/i), failures: find(/fail|defect|reject/i),
                batch: find(/batch|lot|site|campaign|group/i) });
    } catch (err) {
      setError(err.message);
    }
  };

  const nc = Number(conf);
  const confValid = conf !== "" && nc > 0 && nc < 100;
  const rowOk = (r) => isCount(r.demands, 1) && isCount(r.failures, 0) && Number(r.failures) <= Number(r.demands);
  const entered = source === "enter" && rows.every(rowOk);
  const fromData = source === "dataset" && datasetId && cols.demands && cols.failures;
  const valid = name.trim() && confValid && (entered || fromData);

  // Pooled counts for the preview (entered rows only).
  const N = entered ? rows.reduce((s, r) => s + Number(r.demands), 0) : null;
  const F = entered ? rows.reduce((s, r) => s + Number(r.failures), 0) : null;
  // Zero failures: the success run, R >= (1 - C)^(1/n), in closed form.
  const rLower = entered && F === 0 && confValid ? Math.pow(1 - nc / 100, 1 / N) : null;

  const setRow = (i, key, value) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [key]: value } : r)));

  const onSave = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = source === "enter"
        ? { batches: rows.map((r, i) => ({ label: r.label.trim() || (rows.length > 1 ? `Batch ${i + 1}` : ""),
                                          demands: Number(r.demands), failures: Number(r.failures) })) }
        : { dataset_id: datasetId, demands_column: cols.demands, failures_column: cols.failures,
            ...(cols.batch ? { batch_column: cols.batch } : {}) };
      onCreated(await createPerDemandModel(name.trim(), body, nc / 100));
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <div className="card per-demand-new">
      <p className="muted-line" style={{ marginTop: 0 }}>
        Per-demand reliability for one-shot or protective equipment (a valve
        that must open, a device that must start). Enter how many times it was
        demanded and how many times it failed — as one count, or one row per
        batch (sites, lots, test campaigns), which are pooled into one failure
        probability per demand. Bounds are <b>exact</b> at your confidence; with{" "}
        <b>zero failures</b> the lower bound is the success-run demonstration.
      </p>

      <label className="login-field">
        <span>Model name</span>
        <input type="text" autoFocus value={name} placeholder="e.g. Relief valve — open on demand"
               onChange={(e) => setName(e.target.value)} />
      </label>

      <SegmentedControl
        label="Source"
        value={source}
        onChange={setSource}
        style={{ margin: "0.9rem 0 0.6rem" }}
        options={[
          { value: "enter", label: "Enter counts" },
          { value: "dataset", label: "From a dataset" },
        ]}
      />

      {source === "enter" ? (
        <div className="pd-batches">
          <div className={"pd-batch pd-batch-head" + (rows.length > 1 ? " multi" : "")} aria-hidden="true">
            {rows.length > 1 && <span>Batch</span>}
            <span>Demands</span><span>Failures</span>{rows.length > 1 && <span />}
          </div>
          {rows.map((r, i) => (
            <div className={"pd-batch" + (rows.length > 1 ? " multi" : "")} key={i}>
              {rows.length > 1 && (
                <input type="text" aria-label={`Batch ${i + 1} name`} placeholder={`Batch ${i + 1}`}
                       value={r.label} onChange={(e) => setRow(i, "label", e.target.value)} />
              )}
              <input type="number" min="1" step="1" aria-label="Demands" placeholder="Demands"
                     value={r.demands} onChange={(e) => setRow(i, "demands", e.target.value)} />
              <input type="number" min="0" step="1" aria-label="Failures" placeholder="Failures"
                     value={r.failures} onChange={(e) => setRow(i, "failures", e.target.value)} />
              {rows.length > 1 && (
                <button className="secondary pd-remove" aria-label={`Remove batch ${i + 1}`}
                        onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}>×</button>
              )}
            </div>
          ))}
          <button className="secondary pd-add"
                  onClick={() => setRows((rs) => [...rs, { label: "", demands: "", failures: "" }])}>
            + Add a batch
          </button>
        </div>
      ) : (
        <div className="pd-dataset">
          <label className="login-field">
            <span>Dataset (one row per batch)</span>
            <select value={datasetId} onChange={(e) => pickDataset(e.target.value)}>
              <option value="">{datasets === null ? "Loading…" : "Choose a dataset"}</option>
              {(datasets || []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </label>
          {columns.length > 0 && (
            <div className="row" style={{ gap: "0.6rem", marginTop: "0.6rem", flexWrap: "wrap" }}>
              {[["demands", "Demands column"], ["failures", "Failures column"], ["batch", "Batch name (optional)"]].map(
                ([key, label]) => (
                  <label className="login-field" key={key} style={{ flex: "1 1 160px" }}>
                    <span>{label}</span>
                    <select value={cols[key]} onChange={(e) => setCols((c) => ({ ...c, [key]: e.target.value }))}>
                      <option value="">—</option>
                      {columns.map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </label>
                ))}
            </div>
          )}
        </div>
      )}

      <label className="login-field" style={{ maxWidth: 200, marginTop: "0.8rem" }}>
        <span>Confidence (%)</span>
        <input type="number" min="1" max="99" step="1" value={conf}
               onChange={(e) => setConf(e.target.value)} />
      </label>

      {entered && (rLower != null ? (
        <p className="muted-line" style={{ marginBottom: 0 }}>
          Success run — {N} demand{N === 1 ? "" : "s"}, zero failures demonstrates
          reliability <b>≥ {pct(rLower)}</b> at {nc}% confidence.
        </p>
      ) : (
        <p className="muted-line" style={{ marginBottom: 0 }}>
          {rows.length > 1 ? <>Pooled: {F} failure{F === 1 ? "" : "s"} in {N} demands — </> : null}
          failure probability per demand <b>{pct(F / N)}</b>. Exact {confValid ? `${nc}%` : ""} bounds
          come with the model.
        </p>
      ))}
      {error && <div className="error">{error}</div>}

      <div className="fit-flow-foot">
        <span />
        <div className="row" style={{ margin: 0 }}>
          <button className="secondary" onClick={onBack} disabled={busy}>Back</button>
          <button onClick={onSave} disabled={!valid || busy}>{busy ? "Creating…" : "Create model"}</button>
        </div>
      </div>
    </div>
  );
}
