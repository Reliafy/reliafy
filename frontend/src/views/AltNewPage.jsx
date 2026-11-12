import { useEffect, useMemo, useRef, useState } from "react";
import { DataSourceStep } from "../components/DatasetPicker.jsx";
import { useNavigate } from "react-router-dom";
import Select from "../components/Select.jsx";
import RefLink from "../components/RefLink.jsx";
import { getEntry } from "../reference.js";
import NewDatasetModal from "../components/NewDatasetModal.jsx";
import ReadingSummary, { ReadingChange } from "../components/ReadingSummary.jsx";
import { useDatasetReading } from "../useDatasetReading.js";
import AltResultView from "../components/AltResultView.jsx";
import ModelFrame, { AnswerLine } from "../components/model/ModelFrame.jsx";
import { altAnswerParts } from "../altFrame.js";
import {
  getAltOptions, listDatasets, getDataset, fitAlt, saveAltModel, SPREADSHEET_ACCEPT,
} from "../api.js";
import { ErrorNotice } from "../components/StorageCap.jsx";
import {
  altDataIssues, altMapping, altMappingFromReading, altStressFromReading, altStressIssues, altStressPool, isThermal,
  stressLevelsWarning, suggestLifeModelFromReading,
} from "../altGuess.js";
import { codedStatusNote } from "../readingCodes.js";
import { fileStem } from "../datasetGuess.js";

// A thermal model's temperature must be absolute: the unit is asked, and °C or
// °F are converted to kelvin before the fit.
const TEMPERATURE_OPTIONS = [
  { value: "°C", label: "°C" }, { value: "K", label: "K (kelvin)" }, { value: "°F", label: "°F" },
];

const STEPS = ["Source", "Model", "Result"];
// What an ALT fit takes from a dataset's reading (the rest shown quieter); its
// stresses are picked from the reading's covariates (Z).
const USES = ["x", "c", "n", "tl", "tr", "z"];
// Stress units offered (any other can be typed).
const STRESS_UNITS = ["°C", "K", "°F", "V", "kV", "MPa", "kPa", "psi", "bar", "%RH", "A", "W", "g", "rpm", "N", "kN"];

// New Accelerated Life model — a 3-step wizard like the life-data flow: a
// saved dataset (an upload is saved as one first, with how its columns are
// read); the Model step reads the life columns from the dataset's reading and
// holds the model's own inputs: the distribution, the life-stress
// relationship and its stress columns (from the reading's Z), each with its
// unit and the use stress.
export default function AltNewPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);

  const [lifeModels, setLifeModels] = useState([]);
  const [dists, setDists] = useState([]);
  const [datasets, setDatasets] = useState(null); // null while the list loads

  // An uploaded file, while it is saved as a dataset (NewDatasetModal).
  const [file, setFile] = useState(null);
  const [datasetId, setDatasetId] = useState(null);
  const [sourceName, setSourceName] = useState("");
  const [detail, setDetail] = useState(null); // the dataset (getDataset)

  const [distribution, setDistribution] = useState("weibull");
  const [lifeModel, setLifeModel] = useState("arrhenius");
  const [stress, setStress] = useState([{ col: "", label: "" }]);
  // The use stress, as typed in each stress's unit: the Calculator starts there.
  const [useStress, setUseStress] = useState(["", ""]);
  // Until the user picks a stress column, it follows the life-stress model.
  const [stressTouched, setStressTouched] = useState(false);

  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  const [result, setResult] = useState(null);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getAltOptions().then((o) => { setLifeModels(o.life_models || []); setDists(o.distributions || []); }).catch(() => {});
    listDatasets().then((d) => setDatasets(d.datasets || [])).catch(() => setDatasets([]));
  }, []);

  const lm = useMemo(() => lifeModels.find((m) => m.id === lifeModel), [lifeModels, lifeModel]);
  const nStress = lm?.n_stress || 1;

  // How the dataset's columns are read (kept with it): x with its range, c,
  // n, tl and tr come from there; the stresses are offered from its Z.
  const rd = useDatasetReading(detail);
  const derived = useMemo(() => altMappingFromReading(rd.reading, rd.facts, rd.nRows), [rd.reading, rd.facts, rd.nRows]);
  // x and/or the range xl–xr (inspection data, #237), c, n, tl, tr.
  const map = derived?.map || { x: "", xl: "", xr: "", c: "", n: "", tl: "", tr: "" };
  const unit = derived?.unit || "";
  const fitC = derived?.status?.c || "";
  const csv = rd.cols;

  // A dataset's stresses suggest the life-stress relationship (a kV or load
  // the inverse power law, a temperature Arrhenius), once per dataset; the
  // user can change it.
  const suggestedFor = useRef(null);
  useEffect(() => {
    if (!detail || !rd.reading || suggestedFor.current === detail.id) return;
    suggestedFor.current = detail.id;
    const suggested = suggestLifeModelFromReading(rd.cols, rd.reading, fitC);
    if (suggested && suggested !== lifeModel && !(isThermal(suggested) && isThermal(lifeModel))) setLifeModel(suggested);
  }, [detail, rd.reading]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep the stress-column slots in sync with the chosen life-stress model and
  // the reading: guessed from the reading's Z until the user picks one.
  useEffect(() => {
    if (rd.cols && rd.reading && !stressTouched) {
      setStress(altStressFromReading(rd.cols, rd.reading, { nStress, lifeModel, c: fitC }));
      return;
    }
    setStress((cur) => {
      const next = cur.slice(0, nStress);
      while (next.length < nStress) next.push({ col: "", label: "" });
      return next;
    });
  }, [nStress, lifeModel, rd.reading, rd.cols]); // eslint-disable-line react-hooks/exhaustive-deps

  // An uploaded file is saved as a dataset first, through the upload's own
  // screen (how its columns are read), then the fit goes on from it.
  const pickFile = (picked) => {
    if (!picked) return;
    setError(null);
    setFile(picked);
  };
  const onCreated = (ds) => {
    setFile(null);
    if (!ds?.id) return;
    setDatasets((cur) => [ds, ...(cur || []).filter((d) => d.id !== ds.id)]);
    pickDataset(ds);
  };

  const pickDataset = async (d) => {
    setDatasetId(d.id); setSourceName(d.name); setResult(null); setError(null); setLoading(true);
    try {
      const full = await getDataset(d.id);
      if (!d.name) setSourceName(full.name || "dataset");
      setUseStress(["", ""]);
      setStressTouched(false);
      setDetail(full);
      setStep(2);
    } catch (err) { setError(err); } finally { setLoading(false); }
  };

  const onDrop = (e) => { e.preventDefault(); setDragging(false); pickFile(e.dataTransfer.files?.[0]); };

  // What's posted: the reading's life columns (x, its range, c, n, tl, tr).
  const mapping = altMapping(map);
  // What the reading lacks or this fit can't read, else the fit's own checks.
  const missing = derived?.missing || null;
  const dataIssues = missing ? [] : altDataIssues(map);
  const dataValid = !!derived && !missing && dataIssues.length === 0;
  // The stress columns (not the life columns) and a thermal model's unit.
  const stressIssues = altStressIssues(stress, nStress, lifeModel, map);
  const mappingValid = dataValid && stressIssues.length === 0 && !rd.editing;
  const useFor = (j) => (useStress[j] === "" || useStress[j] == null ? null : useStress[j]);

  const setStressAt = (j, patch) =>
    setStress((cur) => cur.map((s, k) => (k === j ? { ...s, ...patch } : s)));

  const onFit = async () => {
    if (!mappingValid) return;
    setLoading(true); setError(null);
    try {
      const opts = {
        datasetId, mapping, stress: stress.slice(0, nStress),
        distribution, lifeModel, unit,
      };
      const res = await fitAlt(null, opts);
      setResult(res);
      const src = (sourceName || "dataset").replace(/\.csv$/i, "");
      setName(`${dists.find((d) => d.id === distribution)?.name || "ALT"} — ${src}`);
      setStep(3);
    } catch (err) { setError(err); } finally { setLoading(false); }
  };

  const onSave = async () => {
    if (!name.trim()) return;
    setSaving(true); setError(null);
    try {
      const saved = await saveAltModel(name.trim(), null, {
        datasetId: result.dataset_id || datasetId, mapping, stress: stress.slice(0, nStress),
        distribution, lifeModel, unit,
      });
      navigate(`/models/alt/${saved.id}`);
    } catch (err) { setError(err); setSaving(false); }
  };

  const goBack = () => { setError(null); if (step === 1) return navigate("/models/alt"); setStep((s) => s - 1); };

  const stepper = (
    <div className="steps">
      {STEPS.map((label, i) => {
        const n = i + 1;
        return (
          <span className="step-wrap" key={label}>
            {i > 0 && <span className="sep" />}
            <span className={`step${step === n ? " active" : ""}`}><span className="dot">{n}</span>{label}</span>
          </span>
        );
      })}
    </div>
  );

  let nav;
  if (step === 1) {
    nav = (<><button className="secondary" onClick={goBack} disabled={loading}>Cancel</button>
      <span className="hint" style={{ margin: 0 }}>Pick a saved dataset, or upload a CSV or Excel file, to continue</span></>);
  } else if (step === 2) {
    const why = !dataValid ? "First fix how the columns are read: Change the reading."
      : rd.editing ? "First save or cancel the change to the reading."
      : !mappingValid ? `First settle the note${new Set(stressIssues.map((i) => i.stress)).size === 1 ? "" : "s"} beside the stress${nStress > 1 ? "es" : ""}.`
      : null;
    nav = (<><button className="secondary" onClick={goBack} disabled={loading}>Back</button>
      {why && <span className="hint ds-next-why" role="status" style={{ margin: 0 }}>{why}</span>}
      <button onClick={onFit} disabled={!mappingValid || loading}>{loading ? "Fitting…" : "Fit model"}</button></>);
  } else {
    nav = (<><button className="secondary" onClick={goBack} disabled={saving}>Back</button>
      <button onClick={onSave} disabled={!name.trim() || saving}>{saving ? "Saving…" : "Save model"}</button></>);
  }

  // The stresses: the reading's Z (else the numeric columns with no role),
  // and any column already picked.
  const pool = csv && rd.reading ? altStressPool(csv, rd.reading, fitC) : [];
  const stressOptions = [...pool, ...stress.map((s) => s.col).filter((c) => c && !pool.includes(c))]
    .filter((c) => !Object.values(mapping).includes(c))
    .map((c) => ({ value: c, label: c }));

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/models")}>Model</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/models/alt")}>Accelerated life</button> /{" "}
            <b>New model</b>
          </div>
          <h1>New accelerated-life model</h1>
          <p>Pick data, choose a distribution, a life-stress relationship and its stresses, then fit and save.</p>
        </div>
      </header>

      <div className="card fit-flow">
        <div className="fit-flow-head">{stepper}</div>
        {step === 1 && (
          <>
            <DataSourceStep
              kind="accelerated"
              datasets={datasets}
              onUse={pickDataset}
              busy={loading}
              upload={(
                <>
            <div className={`dropzone${dragging ? " dragging" : ""}`}
                 onClick={() => inputRef.current?.click()}
                 onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                 onDragLeave={() => setDragging(false)} onDrop={onDrop}>
              <span className="dz-ic">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 16V4m0 0 4 4m-4-4-4 4" /><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
                </svg>
              </span>
              {loading ? <span className="dz-big">Reading the dataset…</span>
                : file ? <span className="dz-big filename">{file.name}</span>
                : <span className="dz-big">Drop a CSV or Excel file here or <strong>click to browse</strong></span>}
              <span className="dz-hint">one row per unit: failure time · stress level(s) · optional censoring</span>
              <input ref={inputRef} type="file" accept={`.csv,text/csv,${SPREADSHEET_ACCEPT}`} hidden
                     onChange={(e) => { pickFile(e.target.files?.[0]); e.target.value = ""; }} />
            </div>
                </>
              )}
            />
          </>
        )}

        {file && (
          <NewDatasetModal title="Save the file as a dataset" initialFile={file} initialName={fileStem(file.name)}
                           withMeasurements={false} onCreated={onCreated} onClose={() => setFile(null)} />
        )}

        {step === 2 && csv && rd.reading && (
          <div className="fit-step">
            <ReadingSummary name={sourceName} reading={rd.reading} source={rd.source} use={USES}
                            note={codedStatusNote(derived?.status)}
                            onChange={rd.editing ? null : rd.startChange}
                            onConfirm={rd.confirm} confirming={rd.saving} readOnly={rd.readOnly} />
            <ReadingChange name={sourceName} rd={rd} />
            {!rd.editing && <ErrorNotice error={rd.error} />}
            {(missing || dataIssues.length > 0) && (
              <div className="xcn-below" role="status">
                {missing
                  ? <p className="xcn-issue" style={{ margin: 0 }}>{missing}</p>
                  : dataIssues.map((i) => <p key={i.text} className="xcn-issue">{i.text} Change the reading to fix it.</p>)}
                {!rd.editing && (
                  <button type="button" className="secondary" style={{ alignSelf: "flex-start" }}
                          onClick={rd.startChange}>Change the reading</button>
                )}
              </div>
            )}
            {dataValid && !rd.editing && (
              <>
            <div className="alt-model-pick">
              <div className="dist-field" style={{ width: 260 }}>
                <span className="dist-label">Life distribution</span>
                <Select value={distribution} onChange={setDistribution} ariaLabel="Life distribution"
                        options={dists.map((d) => ({ value: d.id, label: d.name }))} />
              </div>
              <div className="dist-field" style={{ width: 320 }}>
                <span className="dist-label">Life-stress relationship</span>
                <Select value={lifeModel} onChange={setLifeModel} ariaLabel="Life-stress relationship"
                        options={lifeModels.map((m) => ({ value: m.id, label: `${m.name} · ${m.n_stress} stress${m.n_stress > 1 ? "es" : ""}` }))} />
              </div>
            </div>
            {lm?.desc && (
              <p className="muted-line" style={{ margin: 0 }}>
                {lm.desc}{" "}
                <RefLink text entryId={lifeModel} label={`About ${lm.name}`} />
                {getEntry(lifeModel) && getEntry(distribution) ? " · " : ""}
                <RefLink text entryId={distribution} label={`About the ${dists.find((d) => d.id === distribution)?.name || "distribution"}`} />
              </p>
            )}
            {/* The model's own inputs: its stress columns, each with its unit and the use stress. */}
            <div className="xcn">
              {stress.slice(0, nStress).map((s, j) => {
                const temperature = j === 0 && isThermal(lifeModel);
                const many = s.col ? stressLevelsWarning(csv, s.col) : null;
                const issues = stressIssues.filter((i) => i.stress === j);
                return (
                  <div className="xcn-row" key={j}>
                    <span className="xcn-key">
                      <code>Stress {j + 1}</code>
                      <span className="xcn-words">{temperature ? "the temperature each unit was tested at" : "the stress each unit was tested at"}</span>
                    </span>
                    <div className="xcn-fields">
                      <Select value={s.col} className="xcn-pick" ariaLabel={`Stress ${j + 1} column`}
                              onChange={(v) => { setStressTouched(true); setStressAt(j, { col: v }); }}
                              options={[{ value: "", label: "— pick a column —" }, ...stressOptions]} />
                      <span className="xcn-unit">
                        <span className="xcn-words">unit</span>
                        {temperature ? (
                          <Select value={TEMPERATURE_OPTIONS.some((o) => o.value === s.unit) ? s.unit : ""}
                                  onChange={(v) => setStressAt(j, { unit: v })} options={TEMPERATURE_OPTIONS}
                                  placeholder="°C, K or °F" ariaLabel={`Stress ${j + 1} unit`} />
                        ) : (
                          <>
                            <input className="units-input" type="text" list={`alt-units-${j}`} maxLength={24}
                                   aria-label={`Stress ${j + 1} unit`} placeholder="V, kV, MPa…"
                                   value={s.unit || ""} onChange={(e) => setStressAt(j, { unit: e.target.value })} />
                            <datalist id={`alt-units-${j}`}>{STRESS_UNITS.map((u) => <option value={u} key={u} />)}</datalist>
                          </>
                        )}
                      </span>
                      <label className="xcn-unit">
                        <span className="xcn-words">use stress</span>
                        <input className="units-input alt-use-in" type="number" step="any" inputMode="decimal"
                               aria-label={`Stress ${j + 1} use stress`} value={useStress[j] ?? ""}
                               onChange={(e) => setUseStress((u) => u.map((v, k) => (k === j ? e.target.value : v)))} />
                        <span className="xcn-words">{s.unit ? `in ${s.unit}` : "in that unit"}</span>
                      </label>
                    </div>
                    {(issues.length > 0 || many) && (
                      <div className="xcn-below">
                        {issues.map((i) => <p key={i.text} className="xcn-issue" role="status">{i.text}</p>)}
                        {many && <p className="xcn-issue xcn-note" role="status">{many}</p>}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
              </>
            )}
          </div>
        )}

        {step === 3 && result && (
          <div className="fit-step">
            <label className="login-field">
              <span>Model name</span>
              <input type="text" autoFocus value={name} placeholder="e.g. Valve seal — Arrhenius"
                     onChange={(e) => setName(e.target.value)} />
            </label>
            <p className="muted-line" style={{ margin: 0 }}>
              Review the fit below. Go <b>Back</b> to change anything and fit again, or save it: the Calculator and
              the Diagnostics tests run once it's saved.
            </p>
            {/* The model page's frame, inside the wizard: the answer line over the tabs. */}
            <ModelFrame embedded notice={<div className="mf-wizard-head"><AnswerLine parts={altAnswerParts(result.results)} /></div>}>
              <AltResultView results={result.results} initialUse={useStress.slice(0, nStress).every((v, j) => useFor(j) != null) ? useStress.slice(0, nStress) : null} />
            </ModelFrame>
          </div>
        )}

        <ErrorNotice error={error} />

        <div className="fit-flow-foot">
          <div className="row" style={{ margin: 0 }}>{nav}</div>
        </div>
      </div>
    </div>
  );
}
