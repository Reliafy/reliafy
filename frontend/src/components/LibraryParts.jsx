import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  addModelToLibrary, createLibrary, createModelFromLibrary, fitDatasetWithPrior, getDataset, getLibrarySources, listDatasets,
  listMyLibraries, searchLibrary, updateLibrary,
} from "../api.js";
import { useAppConfig } from "../ConfigProvider.jsx";
import Modal from "./Modal.jsx";
import Field from "./ui/Field.jsx";
import { Select, TextArea, TextInput } from "./ui/Controls.jsx";
import { saveErrorText } from "../confirm.js";
import {
  familyName, isLife, lifeWords, pickerDetail, pickerSources, rangeText, recordPath, sig, sourcePath,
} from "../libraryModels.js";

// The library's shared pieces: a look-up (search across the sources, each hit a link to its record),
// and the two actions a record has on its pages: Use as a model… and Use as a prior…. Picking a
// record inside a dialog is "Pick a library record" (LibraryRecordPicker.jsx), a modal of its own.

export function LibraryLookup({ label = "Records" }) {
  const [q, setQ] = useState("");
  const [source, setSource] = useState("");
  const [sources, setSources] = useState([]);
  const [rows, setRows] = useState(null);
  useEffect(() => {
    let live = true;
    getLibrarySources().then((d) => live && setSources(pickerSources(d.sources)), () => {});
    return () => { live = false; };
  }, []);
  useEffect(() => {
    let live = true;
    const t = setTimeout(() => searchLibrary({ q: q.trim() || undefined, source: source || undefined, pageSize: 12 })
      .then((d) => live && setRows(d.results || []), () => live && setRows([])), 250);
    return () => { live = false; clearTimeout(t); };
  }, [q, source]);
  return (
    <div className="lib-picker">
      <div className="fit2-pair">
        <TextInput type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, equipment, failure mode"
                   aria-label="Search the data library" />
        <Select aria-label="Library" value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">Every library</option>
          {sources.map((s) => <option key={s.id} value={s.id}>{s.mine ? `${s.name} (yours)` : s.short_name || s.name}</option>)}
        </Select>
      </div>
      {rows === null ? <p className="rim-tquiet">Searching…</p> : rows.length === 0 ? <p className="rim-tquiet">No records match.</p> : (
        <ul className="lib-look" aria-label={label}>
          {rows.map((r) => (
            <li key={r.id}>
              <Link to={recordPath(r.id)}>{r.label}</Link>
              <span className="evidence-meta">{pickerDetail(r)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Use as a model…: the record saved to the user's models (a rate → an exponential, cited).
export function UseAsModelDialog({ record, onClose }) {
  const navigate = useNavigate();
  const [name, setName] = useState(`${record.label} (${record.source})`);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const save = async () => {
    setBusy(true);
    try {
      const model = await createModelFromLibrary(record.id, name.trim());
      navigate(`/models/m/${model.id}`);
    } catch (e) {
      setBusy(false);
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };
  return (
    <Modal title="Use as a model" onClose={onClose} locked={busy} trapFocus
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
               <button type="button" onClick={save} disabled={busy || !name.trim()} aria-busy={busy || undefined}>{busy ? "Saving…" : "Save the model"}</button>
             </>
           )}>
      {isLife(record) ? (
        <p className="rw-fhelp">
          Saves a {familyName(record.family || record.distribution?.family)} model with the record’s parameters
          {record.params ? ` (${lifeWords({ family: record.family, params: record.params, level: record.level }, record.units)})` : ""},
          its bounds as the interval. The record and its library are named on the model.
        </p>
      ) : (
        <p className="rw-fhelp">
          Saves an exponential model at the record’s mean rate ({sig(record.mean)} {record.units}), with its 5–95% range
          ({rangeText(record)}) as the interval: the source’s uncertainty, not a fit’s. The record is cited on the model.
        </p>
      )}
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
  const body = { dataset_id: datasetId, time_column: timeCol, censor_column: censorCol || null, unit, distribution,
    prior: { kind: "library", record_id: record.id } };
  useEffect(() => {
    if (target !== "dataset" || !datasetId || !timeCol) { setResult(null); return undefined; }
    let live = true;
    const t = setTimeout(() => fitDatasetWithPrior(body).then((d) => live && setResult(d), (e) => live && setResult({ refused: e.message })), 300);
    return () => { live = false; clearTimeout(t); };
  }, [target, datasetId, timeCol, censorCol, unit, distribution]); // eslint-disable-line react-hooks/exhaustive-deps
  const go = async () => {
    if (target === "position") {
      navigate(`/asset-register/explorer?arrange=positions&tab=models&fit_prior=${encodeURIComponent(record.id)}`);
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
    <Modal title="Use as a prior" onClose={onClose} locked={busy} trapFocus
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
               <button type="button" onClick={go} disabled={busy || (target === "dataset" && !result?.can_save)} aria-busy={busy || undefined}>
                 {target === "position" ? "Pick the position…" : busy ? "Saving…" : "Save as a model"}
               </button>
             </>
           )}>
      <p className="rw-fhelp">
        {life
          ? `The record’s ${familyName(family)} is the prior (each parameter about its value${record.params?.some((p) => p.ci) ? ", between its bounds" : ", within about 30%"}); your own failures and running units move it.`
          : "The record’s distribution is the prior; your own failures and running units move it."}
      </p>
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


// New library… / Edit library…: a name, one line on what it holds, and notes or licence text shown
// with every record. ``library``: the one to edit (none: create).
export function LibraryFormDialog({ library = null, onClose, onDone }) {
  const [name, setName] = useState(library?.name || "");
  const [description, setDescription] = useState(library?.description || "");
  const [notes, setNotes] = useState(library?.notes || "");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const save = async () => {
    setBusy(true);
    try {
      const made = library
        ? await updateLibrary(library.id, { name: name.trim(), description: description.trim(), notes: notes.trim() })
        : await createLibrary({ name: name.trim(), description: description.trim(), notes: notes.trim() });
      onDone(made);
    } catch (e) {
      setBusy(false);
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
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
      {!library && <p className="rw-fhelp">A library of your own holds snapshots of your saved life models, to use as models or priors. Add a model from its page: Add to a library….</p>}
      <Field label="Name"><TextInput value={name} onChange={(e) => setName(e.target.value)} maxLength={120} autoFocus /></Field>
      <Field label="What it holds (one line)"><TextInput value={description} onChange={(e) => setDescription(e.target.value)} maxLength={300} /></Field>
      <Field label="Notes or licence text" help="Shown with every record in this library.">
        <TextArea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={4000} />
      </Field>
      {failed && <p className="field-error" role="alert">{failed}</p>}
    </Modal>
  );
}

// Add to a library…: a saved life model snapshotted into one of the user's libraries (or a new one
// made here), with a label, the equipment type, the failure mode and notes. A model is in no library
// until it's added (Derryn, 9 Nov 2026).
export function AddToLibraryDialog({ modelId, modelName, onClose, onDone }) {
  const [libs, setLibs] = useState(null);
  const [types, setTypes] = useState({});
  const [libraryId, setLibraryId] = useState("");
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [label, setLabel] = useState(modelName || "");
  const [equipment, setEquipment] = useState("other");
  const [mode, setMode] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const [done, setDone] = useState(null);
  useEffect(() => {
    let live = true;
    listMyLibraries().then((d) => {
      if (!live) return;
      const mine = (d.libraries || []).filter((l) => !l.read_only);
      setLibs(mine);
      setTypes(d.equipment_types || {});
      setLibraryId(mine[0]?.id || "new");
    }, () => live && setLibs([]));
    return () => { live = false; };
  }, []);
  const making = libraryId === "new";
  const save = async () => {
    setBusy(true);
    try {
      let lib = (libs || []).find((l) => l.id === libraryId) || null;
      if (making) lib = await createLibrary({ name: newName.trim(), description: newDescription.trim() });
      const out = await addModelToLibrary(lib.id, { modelId, label: label.trim(), equipmentType: equipment, failureMode: mode.trim(), notes: notes.trim() });
      setBusy(false);
      setDone({ library: lib, record: out.record });
      if (onDone) onDone(out, lib);
    } catch (e) {
      setBusy(false);
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };
  const ready = label.trim() && (making ? newName.trim() : libraryId);
  return (
    <Modal title="Add to a library" onClose={onClose} locked={busy} trapFocus
           footer={done ? <button type="button" onClick={onClose}>Done</button> : (
             <>
               <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
               <button type="button" onClick={save} disabled={busy || !ready} aria-busy={busy || undefined}>{busy ? "Adding…" : "Add to the library"}</button>
             </>
           )}>
      {done ? (
        <p role="status">
          Added <strong>{done.record?.label || label}</strong> to <Link to={sourcePath(done.library.id)} onClick={onClose}>{done.library.name}</Link>.
          {" "}<Link to={recordPath(done.record.id)} onClick={onClose}>Open the record</Link>.
        </p>
      ) : (
        <>
          <p className="rw-fhelp">
            Keeps a snapshot of <strong>{modelName}</strong> as it is now (its distribution, parameters and bounds, unit and sample
            sizes) in a library of yours, to use as a model or a prior. A later refit doesn’t change the record.
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
          <Field label="Label"><TextInput value={label} onChange={(e) => setLabel(e.target.value)} maxLength={200} /></Field>
          <div className="fit2-pair">
            <Field label="Equipment type">
              <Select aria-label="Equipment type" value={equipment} onChange={(e) => setEquipment(e.target.value)}>
                {Object.entries(types).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                {!types.other && <option value="other">Other equipment</option>}
              </Select>
            </Field>
            <Field label="Failure mode" help="Leave empty for all failures.">
              <TextInput value={mode} onChange={(e) => setMode(e.target.value)} maxLength={200} placeholder="e.g. Bearing wear" />
            </Field>
          </div>
          <Field label="Notes (optional)"><TextArea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={4000} /></Field>
          <p className="rim-tquiet">The time unit comes from the model.</p>
        </>
      )}
      {failed && <p className="field-error" role="alert">{failed}</p>}
    </Modal>
  );
}
