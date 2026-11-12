import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  addLibraryEntry, createLibrary, createModelFromLibrary, fitDatasetWithPrior, getDataset, getLibraryComponent, getLibraryRecord,
  listDatasets, listLibraries, updateLibrary,
} from "../api.js";
import { ErrorNotice } from "./StorageCap.jsx";
import { isCapRefusal } from "../plan.js";
import { entryPath, libraryPath } from "../libraries.js";
import CovariateCalculator from "./CovariateCalculator.jsx";
import { covariatesToSave, missingInputs } from "../covariate.js";
import { useAppConfig } from "../ConfigProvider.jsx";
import Modal from "./Modal.jsx";
import Field from "./ui/Field.jsx";
import { Select, TextArea, TextInput } from "./ui/Controls.jsx";
import { saveErrorText } from "../confirm.js";
import {
  familyName, isComponentId, isLife, lifeWords, rangeText, sig,
} from "../libraryModels.js";

// The library's shared pieces: the two actions a handbook record has on its pages (Use as a model…
// and Use as a prior…), New library… / Edit…, and Add to library…. Picking a record inside a dialog is "Pick a library record" (LibraryRecordPicker.jsx), a modal of its own.

// The record's covariates (a pipe's length, the clock, the demands a year, a handbook part's
// environment...), read from its page: {inputs, values, setValues, ready, missing}. One state for the
// dialogs that use a record (Use as a model…, Use as a prior…, the Fit dialog's record prior).
export function useRecordCovariates(recordId, start = null) {
  const [inputs, setInputs] = useState(null);
  const [values, setValues] = useState({});
  useEffect(() => {
    let live = true;
    if (!recordId) { setInputs(null); return undefined; }
    setInputs(null);
    (isComponentId(recordId) ? getLibraryComponent(recordId) : getLibraryRecord(recordId)).then((d) => {
      if (!live) return;
      const ins = (isComponentId(recordId) ? d.inputs : d.covariates) || [];
      setInputs(ins);
      setValues(Object.fromEntries(ins.map((i) => [i.key, start?.[i.key] != null ? String(start[i.key]) : ""])));
    }, () => live && setInputs([]));
    return () => { live = false; };
  }, [recordId]); // eslint-disable-line react-hooks/exhaustive-deps
  const missing = inputs ? missingInputs(inputs, values) : [];
  return { inputs, values, setValues, ready: inputs !== null, missing, toSave: covariatesToSave(inputs || [], values) };
}

// A record's covariates with its rate under them, in a dialog: the shared calculator, or nothing when
// the record has none.
export function RecordCovariatesField({ recordId, cov, idPrefix = "rc" }) {
  if (!cov.ready) return <p className="rim-tquiet">Reading its covariates…</p>;
  if (!cov.inputs.length) return null;
  return (
    <div className="lib-cov" role="group" aria-label="Its covariates">
      <p className="rw-fhelp">What it needs before it gives a rate. Left blank, a covariate takes its default; one with no default is needed.</p>
      <CovariateCalculator recordId={recordId} inputs={cov.inputs} values={cov.values} onChange={cov.setValues} idPrefix={idPrefix} stacked />
    </div>
  );
}

// Use as a model…: the record saved to the user's models (a rate → an exponential, cited), under its
// covariates (every one it needs: to fix some at a position and set the rest in an RBD, attach it
// from the Explorer's Life model › From the data library… instead).
export function UseAsModelDialog({ record, onClose }) {
  const navigate = useNavigate();
  const [name, setName] = useState(`${record.label} (${record.source})`);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const cov = useRecordCovariates(isLife(record) ? null : record.id);
  const save = async () => {
    setBusy(true);
    try {
      const model = await createModelFromLibrary(record.id, name.trim(), null, cov.toSave);
      navigate(`/models/m/${model.id}`);
    } catch (e) {
      setBusy(false);
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };
  const blocked = !isLife(record) && (!cov.ready || cov.missing.length > 0);
  return (
    <Modal title="Use as a model" onClose={onClose} locked={busy} trapFocus className="cov-modal"
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
               <button type="button" onClick={save} disabled={busy || !name.trim() || blocked} aria-busy={busy || undefined}>{busy ? "Saving…" : "Save the model"}</button>
             </>
           )}>
      {isComponentId(record.id) ? (
        <p className="rw-fhelp">
          Saves an exponential model at the component’s constant rate over the period below: its failure modes as
          competing risks, −ln(R) ÷ the calendar hours. The modes’ 5–95% range across plants is the interval. The
          component and the covariates are named on the model.
        </p>
      ) : isLife(record) ? (
        <p className="rw-fhelp">
          Saves a {familyName(record.family || record.distribution?.family)} model with the record’s parameters
          {record.params ? ` (${lifeWords({ family: record.family, params: record.params, level: record.level }, record.units)})` : ""},
          its bounds as the interval. The record and its library are named on the model.
        </p>
      ) : (
        <p className="rw-fhelp">
          Saves an exponential model at the record’s mean rate ({sig(record.mean)} {record.units}) under the covariates
          below. Where the source gives a spread (a gamma or lognormal across plants), the model keeps it, so its page
          shows the 5–95% range ({rangeText(record)}, scaled by the covariates): the source’s spread, not a fit’s
          confidence. The record and the covariates are named on the model.
        </p>
      )}
      {!isLife(record) && <RecordCovariatesField recordId={record.id} cov={cov} idPrefix="use" />}
      {cov.missing.length > 0 && <p className="field-error">Give {cov.missing.map((i) => i.label).join(", ")}.</p>}
      <Field label="Name"><TextInput value={name} onChange={(e) => setName(e.target.value)} /></Field>
      {failed && <p className="field-error" role="alert">{failed}</p>}
    </Modal>
  );
}

// Use as a prior…: which data to fit: a position (the Explorer's Fit dialog, prefilled) or one of
// the user's datasets (fitted here and saved as a model).
export function UseAsPriorDialog({ record, onClose }) {
  const navigate = useNavigate();
  const { maintenance } = useAppConfig();
  const [target, setTarget] = useState(maintenance ? "position" : "dataset");
  const [datasets, setDatasets] = useState(null);
  const [datasetId, setDatasetId] = useState("");
  const [columns, setColumns] = useState([]);
  const [timeCol, setTimeCol] = useState("");
  const [censorCol, setCensorCol] = useState("");
  const life = isLife(record);
  const family = record.family || record.distribution?.family;
  const [unit, setUnit] = useState(life && record.units ? String(record.units).toLowerCase() : "hours");
  const [distribution, setDistribution] = useState(life ? family : "exponential");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  useEffect(() => { listDatasets().then((d) => setDatasets(Array.isArray(d) ? d : d.datasets || []), () => setDatasets([])); }, []);
  useEffect(() => {
    if (!datasetId) return;
    getDataset(datasetId).then((d) => {
      const cols = (d.columns || d.preview?.columns || []).map((c) => (typeof c === "string" ? c : c.name)).filter(Boolean);
      setColumns(cols);
      setTimeCol(cols[0] || "");
      setCensorCol(cols[1] || "");
    }, () => setColumns([]));
  }, [datasetId]);
  const cov = useRecordCovariates(life ? null : record.id);
  const body = { dataset_id: datasetId, time_column: timeCol, censor_column: censorCol || null, unit, distribution,
    prior: { kind: "library", record_id: record.id, ...(Object.keys(cov.toSave).length ? { covariates: cov.toSave } : {}) } };
  const covSig = JSON.stringify(cov.toSave);
  useEffect(() => {
    if (target !== "dataset" || !datasetId || !timeCol) { setResult(null); return undefined; }
    let live = true;
    const t = setTimeout(() => fitDatasetWithPrior(body).then((d) => live && setResult(d), (e) => live && setResult({ refused: e.message })), 300);
    return () => { live = false; clearTimeout(t); };
  }, [target, datasetId, timeCol, censorCol, unit, distribution, covSig]); // eslint-disable-line react-hooks/exhaustive-deps
  const go = async () => {
    if (target === "position") {
      const c = Object.keys(cov.toSave).length ? `&fit_prior_cov=${encodeURIComponent(JSON.stringify(cov.toSave))}` : "";
      navigate(`/asset-register/explorer?arrange=positions&tab=models&fit_prior=${encodeURIComponent(record.id)}${c}`);
      return;
    }
    setBusy(true);
    try {
      const model = await fitDatasetWithPrior({ ...body, save: true });
      navigate(`/models/m/${model.id}`);
    } catch (e) {
      setBusy(false);
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };
  return (
    <Modal title="Use as a prior" onClose={onClose} locked={busy} trapFocus className="cov-modal"
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
               <button type="button" onClick={go} disabled={busy || cov.missing.length > 0 || (target === "dataset" && !result?.can_save)} aria-busy={busy || undefined}>
                 {target === "position" ? "Pick the position…" : busy ? "Saving…" : "Save as a model"}
               </button>
             </>
           )}>
      <p className="rw-fhelp">
        {life
          ? `The record’s ${familyName(family)} is the prior (each parameter about its value${record.params?.some((p) => p.ci) ? ", between its bounds" : ", within about 30%"}); your own failures and running units move it.`
          : "The record’s distribution is the prior, under its covariates; your own failures and running units move it."}
      </p>
      {!life && <RecordCovariatesField recordId={record.id} cov={cov} idPrefix="prior" />}
      <Field label="Fit">
        <Select aria-label="Fit" value={target} onChange={(e) => setTarget(e.target.value)}>
          {maintenance && <option value="position">A position’s history (in the Explorer)</option>}
          <option value="dataset">One of my datasets</option>
        </Select>
      </Field>
      {target === "dataset" && (
        <>
          <Field label="Dataset">
            <Select aria-label="Dataset" value={datasetId} onChange={(e) => setDatasetId(e.target.value)}>
              <option value="">{datasets === null ? "Loading…" : "Pick a dataset"}</option>
              {(datasets || []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
          </Field>
          {columns.length > 0 && (
            <div className="fit2-pair">
              <Select aria-label="Time column" value={timeCol} onChange={(e) => setTimeCol(e.target.value)}>{columns.map((c) => <option key={c} value={c}>{c}</option>)}</Select>
              <Select aria-label="Censor column (0 failed, 1 still running)" value={censorCol} onChange={(e) => setCensorCol(e.target.value)}>
                <option value="">None: every row failed</option>{columns.map((c) => <option key={c} value={c}>{c}</option>)}
              </Select>
              <Select aria-label="The times' unit" value={unit} onChange={(e) => setUnit(e.target.value)}>
                {["hours", "days", "weeks", "months", "years"].map((x) => <option key={x} value={x}>{x}</option>)}
              </Select>
              {life ? (
                <Select aria-label="Distribution" value={family} disabled>
                  <option value={family}>{familyName(family)} (the record’s)</option>
                </Select>
              ) : (
                <Select aria-label="Distribution" value={distribution} onChange={(e) => setDistribution(e.target.value)}>
                  <option value="exponential">Exponential (the record's prior exactly)</option><option value="weibull">Weibull</option><option value="lognormal">Lognormal</option>
                </Select>
              )}
            </div>
          )}
          {result?.refused && <p className="field-error" role="alert">{result.refused}</p>}
          {result && !result.refused && <p className="ml-lead" role="status">{result.words}</p>}
        </>
      )}
      {failed && <p className="field-error" role="alert">{failed}</p>}
    </Modal>
  );
}


// New library… / Edit…: a name, one line on what it holds, where its contents come from (source and
// citation) and notes. ``library``: the one to edit (none: create). A refusal at the Free plan's
// limit shows its words with the upgrade link.
export function LibraryFormDialog({ library = null, onClose, onDone }) {
  const [name, setName] = useState(library?.name || "");
  const [description, setDescription] = useState(library?.description || "");
  const [source, setSource] = useState(library?.source || "");
  const [citation, setCitation] = useState(library?.citation || "");
  const [notes, setNotes] = useState(library?.notes || "");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const save = async () => {
    setBusy(true);
    setFailed(null);
    const body = { name: name.trim(), description: description.trim(), source: source.trim(), citation: citation.trim(), notes: notes.trim() };
    try {
      onDone(library ? await updateLibrary(library.id, body) : await createLibrary(body));
    } catch (e) {
      setBusy(false);
      setFailed(isCapRefusal(e) ? e : saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };
  return (
    <Modal title={library ? "Edit library" : "New library"} onClose={onClose} locked={busy} trapFocus
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
               <button type="button" onClick={save} disabled={busy || !name.trim()} aria-busy={busy || undefined}>
                 {busy ? "Saving…" : library ? "Save" : "Create the library"}
               </button>
             </>
           )}>
      {!library && (
        <p className="rw-fhelp">
          A library holds copies of your datasets and models, to keep, share with other workspaces or publish. Add to it
          from a dataset’s or model’s ⋯ menu: <strong>Add to library…</strong>.
        </p>
      )}
      <Field label="Name"><TextInput value={name} onChange={(e) => setName(e.target.value)} maxLength={120} autoFocus /></Field>
      <Field label="What it holds (one line)"><TextInput value={description} onChange={(e) => setDescription(e.target.value)} maxLength={300} /></Field>
      <Field label="Source" help="Where the data and models come from, e.g. a site, a test programme or a report.">
        <TextInput value={source} onChange={(e) => setSource(e.target.value)} maxLength={300} />
      </Field>
      <Field label="Citation" help="How to cite it. Needed to publish.">
        <TextInput value={citation} onChange={(e) => setCitation(e.target.value)} maxLength={1000} />
      </Field>
      <Field label="Notes" help="Shown on the library’s page.">
        <TextArea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={4000} />
      </Field>
      <ErrorNotice error={failed} className="field-error" role="alert" />
    </Modal>
  );
}

// Add to library…: a copy of a dataset or a model (any kind: fitted, from parameters, from a handbook
// or a prior) as it is now, into one of your libraries or a new one made here. Nothing is ever added
// automatically (Derryn, 9 Nov 2026). ``collection``: the model's ("models", "recurrent_models",
// "alt_models"); a dataset passes ``datasetId`` instead of ``modelId``.
export function AddToLibraryDialog({ modelId = null, modelName = "", collection = "models", datasetId = null, datasetName = "", onClose, onDone }) {
  const [libs, setLibs] = useState(null);
  const [libraryId, setLibraryId] = useState("");
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const [done, setDone] = useState(null);
  const name = datasetId ? datasetName : modelName;
  useEffect(() => {
    let live = true;
    listLibraries().then((d) => {
      if (!live) return;
      const mine = (d.libraries || []).filter((l) => l.relation === "yours" && l.can_edit && !l.builtin);
      setLibs(mine);
      setLibraryId(mine[0]?.id || "new");
    }, () => live && (setLibs([]), setLibraryId("new")));
    return () => { live = false; };
  }, []);
  const making = libraryId === "new";
  const save = async () => {
    setBusy(true);
    setFailed(null);
    try {
      let lib = (libs || []).find((l) => l.id === libraryId) || null;
      if (making) {
        lib = await createLibrary({ name: newName.trim(), description: newDescription.trim() });
        setLibs((xs) => [lib, ...(xs || [])]);
        setLibraryId(lib.id);
      }
      const out = await addLibraryEntry(lib.id, datasetId ? { dataset_id: datasetId } : { model_id: modelId, collection });
      setBusy(false);
      setDone({ library: out.library || lib, entry: out.entry });
      if (onDone) onDone(out, lib);
    } catch (e) {
      setBusy(false);
      setFailed(isCapRefusal(e) ? e : saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };
  const ready = making ? newName.trim() : libraryId;
  return (
    <Modal title="Add to library" onClose={onClose} locked={busy} trapFocus
           footer={done ? <button type="button" onClick={onClose}>Done</button> : (
             <>
               <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
               <button type="button" onClick={save} disabled={busy || !ready || libs === null} aria-busy={busy || undefined}>
                 {busy ? "Adding…" : "Add to the library"}
               </button>
             </>
           )}>
      {done ? (
        <p role="status">
          Added <strong>{done.entry?.name || name}</strong> to{" "}
          <Link to={libraryPath(done.library.id)} onClick={onClose}>{done.library.name}</Link>.
          {done.entry?.id && <>{" "}<Link to={entryPath(done.library.id, done.entry.id)} onClick={onClose}>Open the entry</Link>.</>}
        </p>
      ) : (
        <>
          <p className="rw-fhelp">
            Adds <strong>{name || (datasetId ? "this dataset" : "this model")}</strong> to a library of yours. The library keeps
            a copy as it is now; later edits here don’t change it.
          </p>
          <Field label="Library">
            <Select aria-label="Library" value={libraryId} onChange={(e) => setLibraryId(e.target.value)} disabled={libs === null}>
              {libs === null && <option value="">Loading…</option>}
              {(libs || []).map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              <option value="new">New library…</option>
            </Select>
          </Field>
          {making && (
            <div className="fit2-pair">
              <TextInput aria-label="New library's name" placeholder="Library name" value={newName} onChange={(e) => setNewName(e.target.value)} maxLength={120} />
              <TextInput aria-label="New library's description" placeholder="What it holds (one line)" value={newDescription}
                         onChange={(e) => setNewDescription(e.target.value)} maxLength={300} />
            </div>
          )}
        </>
      )}
      <ErrorNotice error={failed} className="field-error" role="alert" />
    </Modal>
  );
}
