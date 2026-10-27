import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import Select from "../components/Select.jsx";
import { datasetParts, usableDatasets } from "../datasetFit.js";
import PreviewTable from "../components/PreviewTable.jsx";
import NewDatasetModal from "../components/NewDatasetModal.jsx";
import { DatasetPartModal } from "../components/DatasetPartInput.jsx";
import Units from "../components/Units.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import {
  checkJointData, fitJointModel, getDataset, getJointOptions, getRbdJob, listDatasets,
} from "../api.js";
import { columnFacts } from "../lifeData.js";
import { covariateParts, guessLifetimeColumns, guessReadingColumns } from "../joint.js";

const NONE = { value: "", label: "— none —" };
const POLL_MS = 2000;

// The one dataset: an existing one holding its units' life data with their
// measurements (or one table holding both), or a new one uploaded or pasted
// (the Data library's own dialog, with its measurements).
function DatasetPicker({ datasets, value, onPick }) {
  const choices = usableDatasets("joint", datasets);
  const [modal, setModal] = useState(false);
  return (
    <div className="joint-table-pick">
      <div className="joint-row">
        <Select
          value={value?.id || ""}
          onChange={(id) => id && onPick(id)}
          placeholder="— choose a dataset —"
          ariaLabel="Dataset"
          options={[
            { value: "", label: "— choose a dataset —" },
            ...choices.map((d) => ({
              value: d.id, label: d.name,
              hint: d.measurements ? `${d.n_rows} units · ${d.measurements.n_rows} readings` : d.summary || undefined,
            })),
          ]}
        />
        <button type="button" className="secondary" onClick={() => setModal(true)}>Upload or paste…</button>
      </div>
      {choices.length === 0 && (
        <p className="hint">
          None of your datasets holds life data with measurements yet. Upload both here, or open a dataset under{" "}
          <Link to="/data">Data</Link> and add its measurements.
        </p>
      )}
      {modal && (
        <NewDatasetModal
          measurementsOpen
          onClose={() => setModal(false)}
          onCreated={(ds) => { setModal(false); onPick(ds.id, true); }}
        />
      )}
    </div>
  );
}

function ColumnSelect({ label, value, onChange, columns, optional = false }) {
  return (
    <label className="dist-field">
      <span className="dist-label">{label}</span>
      <Select
        value={value || ""}
        onChange={onChange}
        ariaLabel={label}
        options={[...(optional ? [NONE] : []), ...columns.map((c) => ({ value: c, label: c }))]}
      />
    </label>
  );
}

// A part's columns with the facts the guesses need.
function describe(part) {
  if (!part) return null;
  const facts = columnFacts({ columns: part.columns, dtypes: part.dtypes, blanks: part.blanks, values: part.values,
                              n_unique: part.n_unique, whole: part.whole, preview: part.preview });
  return { ...part, facts, described: part.columns.map((c) => ({ name: c, ...facts[c] })) };
}

// A new condition and life model: one dataset (its life data with its
// measurements), the columns of each part, the covariates and the reading's
// path; Check data, then Fit (Pro, a job on the calculation service).
export default function JointNewPage() {
  const navigate = useNavigate();
  const [datasets, setDatasets] = useState([]);
  const [opts, setOpts] = useState(null);
  const [dataset, setDataset] = useState(null); // {id, name, life, reads, combined, missing}
  const [map, setMap] = useState({ id: "", x: "", xl: "", xr: "", c: "", tl: "" });
  const [interval, setInterval_] = useState(false);
  const [invert, setInvert] = useState(false);
  const [rmap, setRmap] = useState({ id: "", age: "", value: "" });
  const [covs, setCovs] = useState([]); // [{name, risk, path}]
  const [path, setPath] = useState("linear");
  const [unit, setUnit] = useState("");
  const [marker, setMarker] = useState("");
  const [markerUnit, setMarkerUnit] = useState("");
  const [name, setName] = useState("");
  const [check, setCheck] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null); // null | "check" | "fit"
  const [job, setJob] = useState(null);
  const [needsPro, setNeedsPro] = useState(null);
  const [addReadings, setAddReadings] = useState(false);
  const alive = useRef(true);
  const [params] = useSearchParams();

  useEffect(() => {
    alive.current = true;
    getJointOptions().then((o) => { setOpts(o); setPath(o.default_path || "linear"); }).catch(() => {});
    listDatasets().then((d) => setDatasets(d.datasets || [])).catch(() => {});
    return () => { alive.current = false; };
  }, []);

  const pick = async (id, refreshList = false) => {
    setError(null); setCheck(null);
    try {
      const full = await getDataset(id);
      if (refreshList) listDatasets().then((d) => setDatasets(d.datasets || [])).catch(() => {});
      const parts = datasetParts(full);
      // The readings: the measurements part, or the one table holding both
      // (the rows with the flag filled in are the lifetimes, every row a reading).
      const life = describe(parts.life);
      const reads = parts.measurements ? describe(parts.measurements) : parts.life ? life : null;
      const missing = !parts.life ? "life" : !parts.measurements && !parts.combined ? "measurements" : null;
      setDataset({ id, name: full.name, life, reads, combined: !parts.measurements && !!parts.life, missing,
                   readOnly: !!full.read_only });
      if (life) {
        const g = guessLifetimeColumns(life.described);
        setMap({ id: g.id, x: g.x, xl: "", xr: "", c: g.c, tl: "" });
        setInterval_(false);
        setInvert(g.invert);
        if (g.unit && !unit) setUnit(g.unit);
        setCovs(g.covariates.map((c) => ({ name: c, risk: false, path: false })));
      }
      if (reads) {
        const r = guessReadingColumns(reads.described);
        setRmap(r);
        if (!marker) setMarker(r.value);
      }
      if (!name) setName(full.name.replace(/\s*\(sample\)$/i, "").replace(/\.(csv|tsv|txt|xlsx)$/i, ""));
    } catch (err) { setError(err.message); }
  };

  // A link from the Data list picks the dataset (?dataset=; the earlier
  // ?lifetimes= / ?readings= links name the same one).
  useEffect(() => {
    const id = params.get("dataset") || params.get("lifetimes") || params.get("readings");
    if (id) pick(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const mapping = interval
    ? { id: map.id, xl: map.xl, xr: map.xr, c: map.c, tl: map.tl }
    : { id: map.id, x: map.x, c: map.c, tl: map.tl };
  const parts = covariateParts(covs);
  const body = useMemo(() => ({
    dataset_id: dataset?.id,
    mapping: Object.fromEntries(Object.entries(mapping).filter(([, v]) => v)),
    readings_mapping: rmap,
    c_invert: invert,
    ...parts,
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [dataset?.id, JSON.stringify(mapping), JSON.stringify(rmap), invert, JSON.stringify(parts)]);

  const ready = dataset && dataset.life && dataset.reads && !dataset.missing;
  const mapped = ready && map.id && map.c && (interval ? map.xl && map.xr : map.x) && rmap.id && rmap.age && rmap.value;

  const onCheck = async () => {
    setBusy("check"); setError(null);
    try { setCheck(await checkJointData(body)); }
    catch (err) { setCheck(null); setError(err.message); }
    finally { setBusy(null); }
  };

  const poll = async (jobId) => {
    while (alive.current) {
      const j = await getRbdJob(jobId);
      setJob(j);
      if (j.status === "done") {
        const id = j.result?.model_id;
        if (id) navigate(`/models/joint/${id}`);
        else setError("The fit finished but the model wasn't saved. Try again.");
        return;
      }
      if (j.status === "failed") throw new Error(j.error || "The fit failed.");
      await new Promise((r) => setTimeout(r, POLL_MS));
    }
  };

  const onFit = async () => {
    setBusy("fit"); setError(null); setNeedsPro(null); setJob(null);
    try {
      const out = await fitJointModel({
        ...body, name: name.trim(), path_model: path, unit, marker: marker.trim(), marker_unit: markerUnit.trim(),
      });
      if (out.model_id) navigate(`/models/joint/${out.model_id}`);
      else if (out.job?.job_id) {
        setJob(out.job);
        await poll(out.job.job_id);
      }
    } catch (err) {
      if (err.status === 402) setNeedsPro(err.message);
      else setError(err.message);
    } finally {
      if (alive.current) setBusy(null);
    }
  };

  const lifeCols = dataset?.life?.columns || [];
  const readCols = dataset?.reads?.columns || [];
  const setCov = (i, patch) => setCovs((cur) => cur.map((c, k) => (k === i ? { ...c, ...patch } : c)));
  const pathOpt = (opts?.paths || []).find((p) => p.id === path);
  const unitWord = unit ? unit.toLowerCase() : "the time unit";

  return (
    <div className="app joint-new">
      <PageHeader
        crumbs={[{ label: "Model", to: "/models" }, { label: "Condition and life", to: "/models/joint" }]}
        title="New condition and life model"
        meta="Fits how a reading drifts on each unit and how the risk of failing rises with it, together."
      />

      <div className="card">
        <h2>1. Your dataset</h2>
        <p className="hint">
          One dataset holding both: the <strong>life data</strong> (one row per unit: its id, its age at failure or now,
          whether it failed, and any covariates) and its <strong>measurements</strong> (one row per reading: the unit's id,
          its age when read, and the value). Ages are since new, in one time unit, in both.
        </p>
        <DatasetPicker datasets={datasets} value={dataset} onPick={pick} />
        {dataset && (
          <div className="joint-tables">
            <div className="joint-table-pick">
              <div className="picker-label">Life data{dataset.life ? ` · ${dataset.life.n_rows.toLocaleString()} rows` : ""}</div>
              {dataset.life?.preview?.length > 0 && (
                <PreviewTable columns={dataset.life.columns} rows={dataset.life.preview.slice(0, 4)} />
              )}
              {!dataset.life && <p className="hint">This dataset holds readings alone: add its life data under <Link to={`/data/${encodeURIComponent(dataset.id)}`}>Data</Link> first.</p>}
            </div>
            <div className="joint-table-pick">
              <div className="picker-label">
                Measurements{dataset.reads && !dataset.combined ? ` · ${dataset.reads.n_rows.toLocaleString()} readings` : dataset.combined ? " · in the same table" : ""}
              </div>
              {dataset.missing === "measurements" ? (
                <div className="ds-part-empty">
                  <p>No measurements yet: this dataset has its units' lives, but no readings taken on them.</p>
                  {dataset.readOnly ? (
                    <p className="muted-line">It is read-only; pick another, or upload your own.</p>
                  ) : (
                    <button type="button" onClick={() => setAddReadings(true)}>Add measurements</button>
                  )}
                </div>
              ) : dataset.reads?.preview?.length > 0 && !dataset.combined ? (
                <PreviewTable columns={dataset.reads.columns} rows={dataset.reads.preview.slice(0, 4)} />
              ) : dataset.combined ? (
                <p className="hint">
                  The readings are the rows of the one table; the rows with the censoring flag filled in are each unit's
                  outcome. Its page under <Link to={`/data/${encodeURIComponent(dataset.id)}`}>Data</Link> can split it
                  into the two parts.
                </p>
              ) : null}
            </div>
          </div>
        )}
      </div>

      {ready && (
        <div className="card">
          <h2>2. Columns</h2>
          <h3 className="joint-h3">Life data</h3>
          <div className="joint-fields">
            <ColumnSelect label="Unit id" value={map.id} columns={lifeCols} onChange={(v) => setMap({ ...map, id: v })} />
            {interval ? (
              <>
                <ColumnSelect label="Last seen working (age)" value={map.xl} columns={lifeCols} onChange={(v) => setMap({ ...map, xl: v })} />
                <ColumnSelect label="Found failed (age)" value={map.xr} columns={lifeCols} onChange={(v) => setMap({ ...map, xr: v })} />
              </>
            ) : (
              <ColumnSelect label="Age at failure, or now" value={map.x} columns={lifeCols} onChange={(v) => setMap({ ...map, x: v })} />
            )}
            <ColumnSelect label="Censoring flag" value={map.c} columns={lifeCols} onChange={(v) => setMap({ ...map, c: v })} />
            <ColumnSelect label="Entry age (optional)" value={map.tl} columns={lifeCols} optional onChange={(v) => setMap({ ...map, tl: v })} />
          </div>
          <label className="joint-check">
            <input type="checkbox" checked={invert} onChange={(e) => setInvert(e.target.checked)} />
            My flag is 1 = failed, 0 = still running <span className="muted">(Reliafy's is 0 = failed, 1 = still running)</span>
          </label>
          <label className="joint-check">
            <input type="checkbox" checked={interval} onChange={(e) => setInterval_(e.target.checked)} />
            Failures found at inspections (an age range per unit; flag 2)
          </label>

          <h3 className="joint-h3">Measurements</h3>
          <div className="joint-fields">
            <ColumnSelect label="Reading's unit id" value={rmap.id} columns={readCols} onChange={(v) => setRmap({ ...rmap, id: v })} />
            <ColumnSelect label="Age when read" value={rmap.age} columns={readCols} onChange={(v) => setRmap({ ...rmap, age: v })} />
            <ColumnSelect label="Value" value={rmap.value} columns={readCols} onChange={(v) => setRmap({ ...rmap, value: v })} />
          </div>

          <h3 className="joint-h3">Covariates (optional)</h3>
          {covs.length === 0 ? (
            <p className="muted-line">No other numeric columns in the life data.</p>
          ) : (
            <div className="maint-scroll">
              <table className="calc-table joint-covs">
                <thead>
                  <tr><th>Column</th><th>Changes the risk</th><th>Changes the reading's path</th></tr>
                </thead>
                <tbody>
                  {covs.map((c, i) => (
                    <tr key={c.name}>
                      <td>{c.name}</td>
                      <td><input type="checkbox" aria-label={`${c.name} changes the risk`} checked={c.risk} onChange={(e) => setCov(i, { risk: e.target.checked })} /></td>
                      <td><input type="checkbox" aria-label={`${c.name} changes the path`} checked={c.path} onChange={(e) => setCov(i, { path: e.target.checked })} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="hint">
            A covariate in the risk changes the failure rate at the same reading (a harsher site, say); one in the
            path changes how the reading itself moves (a heavier load wearing faster). Numbers only (0/1 for yes/no).
          </p>
        </div>
      )}

      {ready && (
        <div className="card">
          <h2>3. Model</h2>
          <div className="joint-fields">
            <label className="dist-field">
              <span className="dist-label">Reading's path</span>
              <Select
                value={path}
                onChange={setPath}
                ariaLabel="Reading's path"
                options={(opts?.paths || [{ id: "linear", name: "Linear", formula: "a + b t" }])
                  .map((p) => ({ value: p.id, label: p.name, hint: p.formula }))}
              />
            </label>
            <Units value={unit} onChange={setUnit} />
          </div>
          {pathOpt?.description && <p className="hint">{pathOpt.description}</p>}
          <div className="joint-fields">
            <label className="dist-field">
              <span className="dist-label">What is read</span>
              <input value={marker} onChange={(e) => setMarker(e.target.value)} placeholder="e.g. vibration" />
            </label>
            <label className="dist-field">
              <span className="dist-label">Its unit (optional)</span>
              <input value={markerUnit} onChange={(e) => setMarkerUnit(e.target.value)} placeholder="e.g. mm/s" />
            </label>
            <label className="dist-field">
              <span className="dist-label">Model name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Feed pumps" />
            </label>
          </div>
          <p className="hint">Ages and the risk horizons are in {unitWord}, counted from new.</p>

          <div className="joint-actions">
            <button type="button" className="secondary" disabled={!mapped || !!busy} onClick={onCheck}>
              {busy === "check" ? "Checking…" : "Check data"}
            </button>
            <button type="button" disabled={!mapped || !name.trim() || !!busy} onClick={onFit}>
              {busy === "fit" ? "Fitting…" : "Fit model"}
            </button>
          </div>

          {check && (
            <div className="card note joint-check-out" role="status">
              <p style={{ margin: 0 }}>
                {check.n_units} units: {check.n_failed} failed, {check.n_running} still running.{" "}
                {check.n_readings} readings on {check.n_with_readings} units.
              </p>
              {(check.notes || []).map((n) => <p key={n} className="muted" style={{ margin: "4px 0 0" }}>{n}</p>)}
            </div>
          )}
          {job && busy === "fit" && (
            <p className="hint" role="status">
              {job.status === "running" ? "Fitting on the calculation service…" : "Queued for the calculation service…"}
              {job.queue_position ? ` ${job.queue_position} ahead.` : ""} A fleet takes from a few seconds to about a
              minute.
            </p>
          )}
          {needsPro && (
            <div className="card note" role="status">
              <p style={{ margin: 0 }}>{needsPro}</p>
              <div className="rbd-upgrade-actions"><Link className="cta cta-solid" to="/billing">Upgrade to Pro</Link></div>
            </div>
          )}
          {error && <div className="card error" role="alert">{error}</div>}
        </div>
      )}
      {!ready && error && <div className="card error" role="alert">{error}</div>}
      {addReadings && dataset && (
        <DatasetPartModal
          datasetId={dataset.id}
          part="measurements"
          onClose={() => setAddReadings(false)}
          onDone={() => { setAddReadings(false); pick(dataset.id, true); }}
        />
      )}
    </div>
  );
}
