import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  createModelFromLibrary, fitDatasetWithPrior, getDataset, getLibrarySources, listDatasets, searchLibrary,
} from "../api.js";
import { useAppConfig } from "../ConfigProvider.jsx";
import Modal from "./Modal.jsx";
import Field from "./ui/Field.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import { saveErrorText } from "../confirm.js";
import { leftOutWords, pickerDetail, rangeText, recordPath, sig, usableSource, whyNot } from "../libraryModels.js";
import "./LibraryParts.css";

// The library's shared pieces: a picker (search across the sources; each hit as a stacked item: its
// name, then one quiet line with its value, 5–95% range and source, and a Details link), and the two
// actions a record has on its pages: Use as a model… and Use as a prior….
//
// ``use``: "model" or "prior" shows only the records that can be that on their own (the search's
// ``use`` filter; a grey line says what was left out) and starts on the first library that has any;
// "look" shows every record (the Library page's search).

export function LibraryPicker({ value, onPick, use = "model", label = "Data library records" }) {
  const filtered = use !== "look";
  const [q, setQ] = useState("");
  const [source, setSource] = useState(filtered ? null : ""); // null: not chosen yet (the default comes with the sources)
  const [sources, setSources] = useState([]);
  const [rows, setRows] = useState(null);
  const [leftOut, setLeftOut] = useState(null);
  useEffect(() => {
    let live = true;
    getLibrarySources().then((d) => {
      if (!live) return;
      const list = d.sources || [];
      setSources(list);
      setSource((cur) => (cur === null ? (list.find(usableSource) || list[0])?.id || "" : cur));
    }, () => live && setSource((cur) => (cur === null ? "" : cur)));
    return () => { live = false; };
  }, []);
  useEffect(() => {
    if (source === null) return undefined;
    let live = true;
    const t = setTimeout(() => searchLibrary({ q: q.trim() || undefined, source: source || undefined, pageSize: 12, use: filtered ? use : undefined })
      .then((d) => { if (live) { setRows(d.results || []); setLeftOut(d.left_out || null); } }, () => live && setRows([])), 250);
    return () => { live = false; clearTimeout(t); };
  }, [q, source, use, filtered]);
  const hidden = filtered ? leftOutWords(leftOut) : null;
  return (
    <div className="lib-picker">
      <div className="fit2-pair">
        <TextInput type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, equipment, failure mode"
                   aria-label="Search the data library" />
        <Select aria-label="Library" value={source || ""} onChange={(e) => setSource(e.target.value)}>
          <option value="">Every library</option>
          {sources.map((s) => <option key={s.id} value={s.id}>{s.short_name || s.name}</option>)}
        </Select>
      </div>
      {rows === null ? <p className="rim-tquiet">Searching…</p> : rows.length === 0 ? <p className="rim-tquiet">No records match.</p> : (
        <div className="evidence-picker lib-records" role="radiogroup" aria-label={label}>
          {rows.map((r) => {
            const why = filtered ? whyNot(r, use) : null;
            return (
              <label key={r.id} className={"evidence-option lib-record" + (value === r.id ? " selected" : "") + (why ? " off" : "")} title={why || undefined}>
                <input type="radio" name={`lib-${use}`} checked={value === r.id} disabled={!!why} onChange={() => onPick(r)} />
                <span className="evidence-name">{r.label}</span>
                <span className="evidence-meta">
                  {pickerDetail(r)}
                  {" · "}<Link to={recordPath(r.id)} target="_blank" rel="noreferrer">Details</Link>
                  {why ? ` · ${why}` : ""}
                </span>
              </label>
            );
          })}
        </div>
      )}
      {hidden && <p className="rim-tquiet lib-leftout">{hidden}</p>}
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
      <p className="rw-fhelp">
        Saves an exponential model at the record’s mean rate ({sig(record.mean)} {record.units}), with its 5–95% range
        ({rangeText(record)}) as the interval: the source’s uncertainty, not a fit’s. The record is cited on the model.
      </p>
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
  const [unit, setUnit] = useState("hours");
  const [distribution, setDistribution] = useState("exponential");
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
      <p className="rw-fhelp">The record’s distribution is the prior; your own failures and running units move it.</p>
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
              <Select aria-label="Distribution" value={distribution} onChange={(e) => setDistribution(e.target.value)}>
                <option value="exponential">Exponential (the record's prior exactly)</option><option value="weibull">Weibull</option><option value="lognormal">Lognormal</option>
              </Select>
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
