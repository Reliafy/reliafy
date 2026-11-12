import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import Select from "../components/Select.jsx";
import { datasetParts } from "../datasetFit.js";
import DatasetPicker from "../components/DatasetPicker.jsx";
import PreviewTable from "../components/PreviewTable.jsx";
import NewDatasetModal from "../components/NewDatasetModal.jsx";
import { DatasetPartModal } from "../components/DatasetPartInput.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import {
  cancelRbdJob, checkJointData, fitJointModel, getDataset, getJointOptions, getRbdJob, listDatasets,
} from "../api.js";
import { CANCELLED_TEXT, createRunGuard } from "../jobCancel.js";
import { columnFacts } from "../lifeData.js";
import { jointIssues, jointMappingsFromReading, jointRequest } from "../joint.js";
import { emptyReading } from "../datasetReading.js";
import { useDatasetReading } from "../useDatasetReading.js";
import ReadingSummary, { ReadingChange } from "../components/ReadingSummary.jsx";
import MeasurementsReadingChange from "../components/MeasurementsReadingChange.jsx";
import ProTag from "../components/ProTag.jsx";

const POLL_MS = 2000;

// The one dataset: an existing one holding its units' life data with their measurements (or one
// table holding both), picked from the shared list (DatasetPicker), or a new one uploaded or pasted
// (the Data library's own dialog, with its measurements).
function UploadNew({ onPick }) {
  const [modal, setModal] = useState(false);
  return (
    <>
      <button type="button" className="secondary" onClick={() => setModal(true)}>Upload or paste a new dataset…</button>
      {modal && (
        <NewDatasetModal
          measurementsOpen
          onClose={() => setModal(false)}
          onCreated={(ds) => { setModal(false); onPick(ds.id, true); }}
        />
      )}
    </>
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
// measurements), how each part is read (the dataset's reading, one line each,
// with Change: no column questions), the covariates and the reading's path;
// Check data, then Fit (Pro, a job on the calculation service).
export default function JointNewPage() {
  const navigate = useNavigate();
  const [datasets, setDatasets] = useState(null); // null while the list loads
  const [opts, setOpts] = useState(null);
  const [dataset, setDataset] = useState(null); // {id, name, life, reads, combined, missing}
  const [detail, setDetail] = useState(null); // the dataset's detail (getDataset)
  const [covs, setCovs] = useState([]); // [{name, risk, path}]
  const [path, setPath] = useState("linear");
  const [markerTyped, setMarkerTyped] = useState(null);
  const [measEditing, setMeasEditing] = useState(false);
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
    listDatasets().then((d) => setDatasets(d.datasets || [])).catch(() => setDatasets([]));
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
      setDetail(full);
      setMeasEditing(false);
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

  // How the dataset is read (kept with it): the life data from its main
  // reading, the readings from its measurements part's (or the one table's).
  const rd = useDatasetReading(detail);
  const meas = rd.reading?.measurements || detail?.reading?.measurements || null;
  const reading = rd.reading ? { ...rd.reading, ...(meas ? { measurements: meas } : {}) } : null;
  const derived = useMemo(
    () => (reading ? jointMappingsFromReading(reading, { combined: !!dataset?.combined, lifeFacts: dataset?.life?.facts || {} }) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(reading), dataset?.combined, dataset?.life],
  );
  const map = derived?.map || { id: "", x: "", xl: "", xr: "", c: "", tl: "" };
  const rmap = derived?.rmap || { id: "", age: "", value: "" };
  const invert = !!derived?.invert;
  const unit = derived?.unit || "";
  const markerUnit = derived?.markerUnit || "";
  const marker = markerTyped ?? rmap.value;
  // The covariates offered: the reading's Z (numbers only), each in neither part to start.
  const covNames = (derived?.covariates || []).join("\u0000");
  useEffect(() => {
    setCovs((cur) => (derived?.covariates || []).map((c) => cur.find((k) => k.name === c) || { name: c, risk: false, path: false }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [covNames]);
  const issues = [
    ...jointIssues(map, rmap),
    ...(derived?.statusIssue ? [{ table: "life", row: "c", text: derived.statusIssue }] : []),
  ];
  const body = useMemo(() => ({ dataset_id: dataset?.id, ...jointRequest(map, rmap, invert, covs) }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [dataset?.id, JSON.stringify(map), JSON.stringify(rmap), invert, JSON.stringify(covs)]);

  const ready = dataset && dataset.life && dataset.reads && !dataset.missing;
  const editing = rd.editing || measEditing;
  const mapped = ready && !editing && issues.length === 0;

  const onCheck = async () => {
    setBusy("check"); setError(null);
    try { setCheck(await checkJointData(body)); }
    catch (err) { setCheck(null); setError(err.message); }
    finally { setBusy(null); }
  };

  // The fit in flight, so Cancel can stop it (jobCancel.js).
  const runGuard = useRef(null);
  if (!runGuard.current) runGuard.current = createRunGuard();
  const [cancelNote, setCancelNote] = useState(null);

  const poll = async (jobId, token) => {
    while (alive.current && runGuard.current.isCurrent(token)) {
      const j = await getRbdJob(jobId);
      if (!runGuard.current.isCurrent(token)) return;
      setJob(j);
      if (j.status === "done") {
        const id = j.result?.model_id;
        if (id) navigate(`/models/joint/${id}`);
        else setError("The fit finished but the model wasn't saved. Try again.");
        return;
      }
      if (j.status === "failed") throw new Error(j.error || "The fit failed.");
      if (j.status === "cancelled") { setCancelNote(CANCELLED_TEXT); return; }
      await new Promise((r) => setTimeout(r, POLL_MS));
    }
  };

  const onFit = async () => {
    setBusy("fit"); setError(null); setNeedsPro(null); setJob(null); setCancelNote(null);
    // The token lets Cancel stop a fit that runs in the request itself (no
    // queue): the server then saves nothing.
    const token = runGuard.current.start();
    try {
      const out = await fitJointModel({
        ...body, name: name.trim(), path_model: path, unit, marker: marker.trim(), marker_unit: markerUnit.trim(),
        run_token: token,
      });
      if (!runGuard.current.isCurrent(token)) return; // cancelled while it ran
      if (out.model_id) navigate(`/models/joint/${out.model_id}`);
      else if (out.job?.job_id) {
        setJob(out.job);
        await poll(out.job.job_id, token);
      }
    } catch (err) {
      if (!runGuard.current.isCurrent(token)) return;
      if (err.status === 402) setNeedsPro(err.message);
      else setError(err.message);
    } finally {
      // Only this fit's own state: a cancelled one leaves a newer fit alone.
      const mine = runGuard.current.isCurrent(token);
      runGuard.current.finish(token);
      if (alive.current && mine) setBusy(null);
    }
  };

  // Stop waiting, and cancel the fit on the server (its job, or the fit
  // running in the request): nothing is saved.
  const cancelFit = () => {
    const token = runGuard.current.cancel();
    const id = job?.job_id || token;
    if (id) cancelRbdJob(id).catch(() => {});
    setJob(null);
    setBusy(null);
    setCancelNote(CANCELLED_TEXT);
  };

  const readCols = dataset?.reads?.columns || [];
  // Change: the life data's reading (the main one), or the measurements part's own.
  const startChange = () => { setMeasEditing(false); rd.startChange(); if (meas && !rd.reading?.measurements) rd.setDraft({ ...rd.reading, measurements: meas }); };
  const startMeasChange = () => (dataset?.combined ? startChange() : (rd.cancelChange(), setMeasEditing(true)));
  const keepMeasurements = async (next) => {
    if (await rd.keep({ ...(rd.reading || emptyReading()), measurements: next })) setMeasEditing(false);
  };
  const lifeIssues = issues.filter((i) => i.table === "life");
  const readIssues = issues.filter((i) => i.table === "reads");
  const issueList = (list, onFix) => list.length > 0 && (
    <div className="xcn-below" role="status">
      {list.map((i) => <p key={i.text} className="xcn-issue">{i.text}</p>)}
      <button type="button" className="link" onClick={onFix}>Change the reading</button>
    </div>
  );
  const setCov = (i, patch) => setCovs((cur) => cur.map((c, k) => (k === i ? { ...c, ...patch } : c)));
  const pathOpt = (opts?.paths || []).find((p) => p.id === path);
  const unitWord = unit ? unit.toLowerCase() : "the time unit";

  return (
    <div className="app joint-new">
      <PageHeader
        crumbs={[{ label: "Models", to: "/models" }, { label: "Condition and life", to: "/models/joint" }]}
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
        <p className="hint" data-testid="joint-use-degradation">
          Only readings, no failures? Use <Link to="/models/degradation">Degradation</Link> instead: it projects each
          item's readings to a failure threshold.
        </p>
        <div className="joint-new-row"><UploadNew onPick={pick} /></div>
        <DatasetPicker kind="joint" datasets={datasets} value={dataset?.id} onPick={(d) => pick(d.id)}
                       empty="Pick a dataset to see its life data and its measurements.">
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
        </DatasetPicker>
      </div>

      {ready && (
        <div className="card">
          <h2>2. How the data is read</h2>
          <h3 className="joint-h3">Life data</h3>
          {!editing && (
            <ReadingSummary
              name={dataset.name}
              reading={rd.reading}
              source={rd.source}
              use={["i", "x", "c", "tl", "z"]}
              onChange={startChange}
              onConfirm={rd.confirm}
              confirming={rd.saving}
              readOnly={rd.readOnly}
            />
          )}
          {!editing && issueList(lifeIssues, startChange)}
          <ReadingChange name={dataset.name} rd={rd} />

          <h3 className="joint-h3">Measurements</h3>
          <p className="muted-line" style={{ margin: 0 }}>m is what was measured on each item over time: readings, not covariates.</p>
          {!editing && (dataset.combined ? (
            <p className="muted-line" style={{ margin: 0 }}>
              From the same table: i = {rmap.id || "—"} · x = {rmap.age || "—"} · m = {rmap.value || "—"}
            </p>
          ) : (
            <ReadingSummary
              name={dataset.name}
              reading={{ ...emptyReading(), ...(meas || {}) }}
              source={meas?.source === "saved" ? "saved" : "guessed"}
              use={["i", "x", "m"]}
              note="Its measurements: the readings on each item, at its age when read."
              onChange={startMeasChange}
              onConfirm={() => keepMeasurements({ ...(meas || {}), source: "saved" })}
              confirming={rd.saving}
              readOnly={rd.readOnly}
            />
          ))}
          {!editing && issueList(readIssues, startMeasChange)}
          {measEditing && (
            <MeasurementsReadingChange
              name={dataset.name}
              columns={readCols}
              facts={dataset.reads?.facts || {}}
              value={meas}
              onKeep={keepMeasurements}
              onCancel={() => setMeasEditing(false)}
              saving={rd.saving}
              error={rd.error}
              readOnly={rd.readOnly}
            />
          )}

          <h3 className="joint-h3">Covariates (optional)</h3>
          {covs.length === 0 ? (
            <p className="muted-line">No covariates: the reading's Z has no numeric columns. Change the reading to add some.</p>
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
          </div>
          {pathOpt?.description && <p className="hint">{pathOpt.description}</p>}
          <div className="joint-fields">
            <label className="dist-field">
              <span className="dist-label">What is read</span>
              <input value={marker} onChange={(e) => setMarkerTyped(e.target.value)} placeholder="e.g. vibration" />
            </label>
            <label className="dist-field">
              <span className="dist-label">Model name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Feed pumps" />
            </label>
          </div>
          <p className="hint">Ages and the risk horizons are in {unitWord}, counted from new.</p>

          <div className="joint-actions">
            {ready && editing && (
              <span className="hint ds-next-why" role="status" style={{ margin: 0 }}>First save or cancel the change to the reading.</span>
            )}
            {ready && !editing && issues.length > 0 && (
              <span className="hint ds-next-why" role="status" style={{ margin: 0 }}>
                First settle what the reading lacks: {[...new Set(issues.map((i) => `${i.row} (${i.table === "life" ? "life data" : "measurements"})`))].join(", ")}.
              </span>
            )}
            <button type="button" className="secondary" disabled={!mapped || !!busy} onClick={onCheck}>
              {busy === "check" ? "Checking…" : "Check data"}
            </button>
            <button type="button" disabled={!mapped || !name.trim() || !!busy} onClick={onFit}>
              {busy === "fit" ? "Fitting…" : <>Fit model<ProTag /></>}
            </button>
            {busy === "fit" && (
              <button type="button" className="secondary" onClick={cancelFit}>
                Cancel
              </button>
            )}
          </div>
          {cancelNote && !busy && <p className="hint" role="status">{cancelNote}</p>}

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
