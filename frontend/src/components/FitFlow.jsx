import { useEffect, useMemo, useRef, useState } from "react";
import {
  getColumns,
  getDistributions,
  fitModel,
  saveModel,
  listDatasets,
  getDataset,
  SPREADSHEET_ACCEPT,
} from "../api.js";
import { useSpreadsheet } from "./ExcelSheetPicker.jsx";
import ColumnMapper from "./ColumnMapper.jsx";
import ColumnRoles from "./ColumnRoles.jsx";
import HeaderNote, { detectHeader } from "./HeaderNote.jsx";
import { useUnsavedFitScope } from "./UnsavedFitReminder.jsx";
import { forgetUnsavedFit, rememberUnsavedFit, unsavedFitRecord } from "../unsavedFit.js";
import Covariates from "./Covariates.jsx";
import CoxOptions from "./CoxOptions.jsx";
import PreviewTable from "./PreviewTable.jsx";
import DistributionStep from "./DistributionStep.jsx";
import CompetingRisksStep, { CR_OPTIONS } from "./CompetingRisksStep.jsx";
import { frailtyFitOptions, groupProblem, withGroup } from "../moreModels.js";
import { usableDatasets } from "../datasetFit.js";
import ResultView from "./ResultView.jsx";
import ModelFrame, { AnswerLine } from "./model/ModelFrame.jsx";
import ModelNextSteps from "./ModelNextSteps.jsx";
import { answerParts } from "../modelFrame.js";
import { ResultDetails } from "./ui/ResultSummary.jsx";
import { TvcToggle } from "./TvcColumns.jsx";
import { guessTvc, tvcMapping, tvcProblems, tvcSummaryParts } from "../tvcData.js";
import { guessUnit, isNumeric } from "../datasetGuess.js";
import {
  EMPTY_MAPPING, columnFacts, guessMapping, isSimplePaste, statusSummary, summaryParts,
  dataStepProblems, dataSplit, parsePastedValues, addMissingFlags, flagsLookSwapped,
} from "../lifeData.js";
import { RequiredUnit } from "./Units.jsx";

const STEPS = ["Source", "Data", "Model", "Result"];
const PASTED = "pasted-values.csv";

// A saved dataset's detail in the shape /api/columns gives.
const datasetColumns = (full) => ({
  columns: full.preview_columns || [],
  preview: full.preview || [],
  n_rows: full.n_rows,
  n_unique: full.n_unique,
  dtypes: full.dtypes,
  blanks: full.blanks,
  values: full.values,
});

// The paste parser lives in lifeData.js (unit-tested there).
export { parsePastedValues };

// Fit flow rendered as a page panel: (1) pick a data source, (2) map columns
// (+ unit, covariates), (3) pick a model and fit, (4) review the fit, then
// name it beside Save and save — with Back to change anything and re-fit before saving. Calls
// ``onSaved`` with the saved model; ``onCancel`` backs out to the list.
// ``initialSource`` opens the source step on "upload" (default) or "paste".
export default function FitFlow({ onSaved, onCancel, onPerDemand, initialDatasetId, autoFit, initialSource }) {
  const [step, setStep] = useState(1);
  // Source step: "upload" (dropzone) or "paste" (values typed / pasted in).
  const [source, setSource] = useState(initialSource === "paste" ? "paste" : "upload");
  const [pasted, setPasted] = useState("");
  // A paste mixing bare times with "time flag" lines: the lines to offer
  // "Add 0 (failed)" for, shown with the error and applied only on a click.
  const [pasteFix, setPasteFix] = useState(null);
  const [file, setFile] = useState(null);
  // A CSV whose first row is all numbers has no header (#434): it's read as
  // data (col 1, col 2, …) and said so, with Undo. { original, kept }:
  // the file as uploaded, and whether its first row was kept as the names.
  const [headerNote, setHeaderNote] = useState(null);
  const [datasetId, setDatasetId] = useState(null);
  const [sourceName, setSourceName] = useState("");
  const [csv, setCsv] = useState(null); // { columns, preview, n_rows, dtypes, blanks, values }
  const [mapping, setMapping] = useState(EMPTY_MAPPING);
  const [unit, setUnit] = useState("");
  // A paste of one or two plain columns skips the mapping: only the unit is
  // asked for, with "Change columns" to see the full mapping (#291).
  const [simple, setSimple] = useState(false);
  const [covariates, setCovariates] = useState([]);
  // Covariates that change over time (#60): null, "intervals" or "timeline".
  const [tvc, setTvc] = useState(null);
  const [covUnits, setCovUnits] = useState({}); // optional unit per covariate (#265)
  const [advanced, setAdvanced] = useState(false);
  const [formula, setFormula] = useState("");
  const [distributions, setDistributions] = useState([]);
  const [distribution, setDistribution] = useState("weibull");
  const [fitOpts, setFitOpts] = useState({});
  const [coxOpts, setCoxOpts] = useState({}); // Cox PH: ties, strata, cluster (#61)
  // A shared-frailty model's Group by column (#179), sent with the mapping.
  const [group, setGroup] = useState("");
  const [datasets, setDatasets] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [dragging, setDragging] = useState(false);
  // An Excel workbook becomes a CSV of the chosen sheet before anything else.
  const { toCsv, modal: sheetModal } = useSpreadsheet();
  const inputRef = useRef(null);

  // Step 4 (Result): the fit, a name, and the save action.
  const [result, setResult] = useState(null);
  const [split, setSplit] = useState(null);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [fitMethods, setFitMethods] = useState([]);

  useEffect(() => {
    getDistributions()
      .then((d) => { setDistributions(d.distributions); setFitMethods(d.fit_methods || []); })
      .catch(() =>
        setDistributions([{ id: "weibull", name: "Weibull", covariates: false }])
      );
    listDatasets()
      .then((d) => setDatasets(d.datasets))
      .catch(() => setDatasets([]));
  }, []);

  // Whether the data implies a proportional-hazards model.
  const hasCovariates = advanced ? formula.trim() !== "" : covariates.length > 0;

  // Model options filtered by the data that was entered. A failure-mode
  // column (#177) fits the modes as competing risks.
  const byMode = !!mapping.e;
  // Covariates over time (#60) take the regressions that can fit them.
  const options = useMemo(
    () => (byMode ? CR_OPTIONS : distributions)
      .filter((d) => !!d.covariates === hasCovariates && (!tvc || d.tvc !== false)),
    [distributions, hasCovariates, byMode, tvc]
  );

  // Keep the selected model valid for the current filtered list.
  useEffect(() => {
    if (options.length && !options.some((o) => o.id === distribution)) {
      setDistribution(options[0].id);
    }
  }, [options, distribution]);

  const selectedOpt = distributions.find((d) => d.id === distribution);
  const fitMapping = withGroup(mapping, selectedOpt, group);
  const distName =
    distribution === "best"
      ? "best model"
      : mapping.e
      ? "by failure mode"
      : [...distributions, ...CR_OPTIONS].find((d) => d.id === distribution)?.name || "model";

  // New columns in: guess the mapping and unit, clear covariates. Returns
  // them (the guided first run fits straight away).
  const loadColumns = (cols, simplePaste = false) => {
    const facts = columnFacts(cols);
    const g = guessMapping(cols.columns, facts);
    const map = simplePaste
      // A pasted flag column is 0 = failed, 1 = still running, as the paste box says.
      ? { ...EMPTY_MAPPING, x: "time", c: cols.columns.includes("censored") ? "censored" : "" }
      : g.mapping;
    // Start and stop rows of items (#60): fit their covariates over time.
    const timeVarying = simplePaste ? null : guessTvc(cols.columns, facts, cols.n_rows);
    const tvcMap = timeVarying && tvcMapping(map, "intervals", cols.columns, facts, cols.n_rows);
    const used = new Set(Object.values(tvcMap || {}).filter((v) => typeof v === "string" && v));
    setCsv(cols);
    setMapping(tvcMap || map);
    setTvc(timeVarying ? "intervals" : null);
    setUnit(simplePaste ? "" : g.unit || (timeVarying ? guessUnit(timeVarying.xl) : ""));
    setSimple(simplePaste);
    setCovariates(timeVarying ? cols.columns.filter((c) => !used.has(c) && isNumeric(facts[c]?.dtype)) : []);
    setGroup("");
    return { mapping: tvcMap || map, unit: simplePaste ? "" : g.unit };
  };

  // ``keepHeader``: read the first row as the column names even when it's
  // all numbers (the header notice's Undo).
  const pickFile = async (picked, { keepHeader = false } = {}) => {
    if (!picked) return;
    const f = await toCsv(picked);
    if (!f) return;
    // Server enforces the same ceiling; fail fast before uploading.
    if (f.size > 5 * 1024 * 1024) {
      setError(`That file is ${(f.size / (1024 * 1024)).toFixed(1)} MB — the limit is 5 MB. Try trimming unused columns or rows.`);
      return;
    }
    // No header row (#434): the file gains one (col 1, col 2, …), and says
    // so. Pasted values are always named.
    const { file: use, note } = f.name === PASTED ? { file: f, note: null }
      : await detectHeader(picked, f, { keepHeader });
    setFile(use);
    setHeaderNote(note);
    setDatasetId(null);
    setSourceName(f.name);
    setError(null);
    setLoading(true);
    try {
      const cols = await getColumns(use);
      loadColumns(cols, isSimplePaste(cols.columns) && use.name === PASTED);
      setStep(2);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Use an already-saved dataset as the source — no re-upload needed.
  const pickDataset = async (d) => {
    setFile(null);
    setHeaderNote(null);
    setDatasetId(d.id);
    setSourceName(d.name);
    setError(null);
    setLoading(true);
    try {
      const full = await getDataset(d.id);
      loadColumns(datasetColumns(full));
      setStep(2);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Guided first-run: when handed a dataset id (e.g. the bearings sample), skip
  // the source step. Load its columns and jump to Data; with autoFit, fit a
  // Weibull straight away and land on the Result so a new user sees a finished
  // model — β verdict, curve, calculator — one save away from activation.
  const booted = useRef(false);
  useEffect(() => {
    if (!initialDatasetId || booted.current) return;
    booted.current = true;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const full = await getDataset(initialDatasetId);
        setFile(null);
        setDatasetId(initialDatasetId);
        setSourceName(full.name || "dataset");
        const { mapping: map, unit: guessedUnit } = loadColumns(datasetColumns(full));
        if (autoFit && map.x) {
          const res = await fitModel("weibull", null, map, { datasetId: initialDatasetId, unit: guessedUnit });
          setSplit(null);
          setResult(res);
          setName(`${res.distribution} — ${(full.name || "dataset").replace(/\s*\(sample\)\s*$/i, "")}`);
          setStep(4);
        } else {
          setStep(2);
        }
      } catch (err) {
        setError(err.message);
        setStep(1);
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialDatasetId, autoFit]);

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    pickFile(e.dataTransfer.files?.[0]);
  };

  // Pasted values become a small CSV file in the browser and go through the
  // same upload path as a real file (/api/columns, then the fit), so nothing
  // downstream changes.
  const usePasted = () => {
    let parsed;
    setPasteFix(null);
    try {
      parsed = parsePastedValues(pasted);
    } catch (err) {
      setError(err.message);
      if (err.fix === "add-flags") setPasteFix(err.lines);
      return;
    }
    pickFile(new File([parsed.csv], PASTED, { type: "text/csv" }));
  };

  const toggleCovariate = (col) =>
    setCovariates((prev) =>
      prev.includes(col) ? prev.filter((c) => c !== col) : [...prev, col]
    );

  // Columns already claimed by a survival field (x/xl/xr/c/n/tl/tr) can't also
  // be covariates. Disable them in the picker and drop any that got mapped.
  const mappedColumns = useMemo(
    () => new Set(Object.values(mapping).filter((v) => typeof v === "string" && v)),
    [mapping]
  );
  useEffect(() => {
    setCovariates((prev) =>
      prev.some((c) => mappedColumns.has(c)) ? prev.filter((c) => !mappedColumns.has(c)) : prev
    );
  }, [mappedColumns]);

  // What the mapping reads as, and what stops it fitting, before the fit.
  const facts = useMemo(() => (csv ? columnFacts(csv) : {}), [csv]);
  const problems = useMemo(
    () => (!csv ? [] : tvc ? tvcProblems(mapping, facts, tvc, hasCovariates ? 1 : 0)
      : dataStepProblems(mapping, facts, csv.n_rows)),
    [csv, mapping, facts, tvc, hasCovariates, unit]
  );
  // Covariates over time on or off, or the rows' layout changed (#60).
  const changeTvc = (layout) => {
    setTvc(layout);
    setMapping((m) => tvcMapping(m, layout, csv.columns, facts, csv.n_rows));
  };
  const mappingValid = problems.length === 0;
  // With a count column the value counts aren't units: read the file instead.
  const [fileSplit, setFileSplit] = useState(null);
  useEffect(() => {
    let live = true;
    setFileSplit(null);
    if (file && mapping.n) {
      dataSplit(file, mapping)
        .then((s) => live && s && setFileSplit({ failed: s.failed, running: s.running, left: 0, interval: s.other }))
        .catch(() => {});
    }
    return () => { live = false; };
  }, [file, mapping]);
  const summary = csv && !tvc ? statusSummary(mapping, facts, csv.n_rows) || fileSplit : null;
  // Most units still running often means the sheet's flags are 1 = failed:
  // say so on the Data step, with the same flip the column mapper uses.
  const swapped = flagsLookSwapped(mapping, summary);
  const swapFlags = () => setMapping((m) => ({ ...m, c_invert: !m.c_invert }));

  // Cox PH's own options travel with a Cox fit only.
  const familyOpts = frailtyFitOptions(options.find((d) => d.id === distribution), fitOpts);
  const coxFit = distribution === "cox_ph" ? { fitOptions: { cox: coxOpts } }
    : familyOpts ? { fitOptions: familyOpts } : {};
  const coxColumns = (csv?.columns || []).filter(
    (c) => !mappedColumns.has(c) && !(advanced ? false : covariates.includes(c)));

  const onFit = async () => {
    if (!file && !datasetId) return;
    setLoading(true);
    setError(null);
    try {
      const opts = {
        unit,
        ...(datasetId ? { datasetId } : {}),
        ...(hasCovariates ? (advanced ? { formula } : { covariates, covariateUnits: covUnits }) : {}),
        ...(hasCovariates ? coxFit : byMode ? {} : { fitOptions: fitOpts }),
      };
      const res = await fitModel(distribution, file, fitMapping, opts);
      setSplit(await dataSplit(file, mapping).catch(() => null));
      setResult(res);
      const src = file?.name || sourceName || "dataset";
      setName(`${res.distribution} — ${src.replace(/\.csv$/i, "")}`);
      setStep(4);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // The fit-statistics dialog's comparison (#293): Best fit's ranking on the
  // same data and options, and a refit with the distribution picked from it.
  const compareFit = () =>
    fitModel("best", file, mapping, {
      unit, ...(datasetId ? { datasetId } : {}),
      fitOptions: { offset: fitOpts.offset, zi: fitOpts.zi, lfp: fitOpts.lfp },
    }).then((res) => res.selection);
  // A fit with options of its own (a fixed β, say) isn't swapped for a plain one.
  const ownOptions = Object.values(fitOpts || {}).some(
    (v) => v && (typeof v !== "object" || Object.keys(v).length > 0));
  const pickFit = async (id) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fitModel(id, file, mapping, { unit, ...(datasetId ? { datasetId } : {}) });
      setDistribution(id);
      setFitOpts({});
      setResult(res);
      const src = file?.name || sourceName || "dataset";
      setName(`${res.distribution} — ${src.replace(/\.csv$/i, "")}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // A fit on the Result step is kept in this browser until it's saved, so the
  // next visit to Models can offer to save it (#434).
  const fitScope = useUnsavedFitScope();
  const remembered = useRef(0);

  // What a save sends besides the data: also kept with an unsaved fit.
  const saveOpts = {
    unit,
    ...(hasCovariates
      ? { ...(advanced ? { formula } : { covariates, covariateUnits: covUnits }), ...coxFit }
      : byMode ? {} : { fitOptions: fitOpts }),
  };
  const persist = async () => {
    const model = await saveModel(name.trim(), distribution, file, fitMapping, {
      ...saveOpts, datasetId: datasetId || undefined,
    });
    forgetUnsavedFit(fitScope);
    return model;
  };

  useEffect(() => {
    if (step !== 4 || !result || !name.trim()) return;
    const turn = ++remembered.current;
    const record = (csv) => unsavedFitRecord({
      name: name.trim(), distribution, mapping: fitMapping, opts: saveOpts,
      datasetId, csv, fileName: file?.name,
    });
    (file && !datasetId ? file.text() : Promise.resolve(null))
      .catch(() => null)
      .then((csv) => turn === remembered.current && rememberUnsavedFit(fitScope, record(csv)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, result, name]);

  const onSave = async () => {
    if (!name.trim()) return;
    remembered.current += 1; // a remember still reading the file is stale now
    setSaving(true);
    setError(null);
    try {
      onSaved?.(await persist());
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  // "Use this model" on a fit not saved yet (#294): save it under the name
  // beside Save, then the tool opens with it (the caller navigates).
  const saveForUse = async () => {
    if (!name.trim()) throw new Error("Name the model beside Save first.");
    remembered.current += 1;
    setSaving(true);
    try {
      return (await persist()).id;
    } finally {
      setSaving(false);
    }
  };

  // Back from step 1 leaves the flow entirely; from Result it returns to Model.
  const goBack = () => {
    setError(null);
    if (step === 1) return onCancel?.();
    setStep((s) => s - 1);
  };

  const stepper = (
    <div className="steps">
      {STEPS.map((label, i) => {
        const n = i + 1;
        return (
          <span className="step-wrap" key={label}>
            {i > 0 && <span className="sep" />}
            <span className={`step${step === n ? " active" : ""}`}>
              <span className="dot">{n}</span>
              {label}
            </span>
          </span>
        );
      })}
    </div>
  );

  let nav;
  if (step === 1) {
    nav = (
      <>
        <button className="secondary" onClick={goBack} disabled={loading}>Cancel</button>
        <span className="hint" style={{ margin: 0 }}>
          {source === "paste"
            ? "Paste your values, or pick a dataset, to continue"
            : "Upload a CSV or Excel file, or pick a dataset, to continue"}
        </span>
      </>
    );
  } else if (step === 2) {
    nav = (
      <>
        <button className="secondary" onClick={goBack} disabled={loading}>Back</button>
        <button data-wt="fit-next" onClick={() => setStep(3)} disabled={!mappingValid}>Next</button>
      </>
    );
  } else if (step === 3) {
    nav = (
      <>
        <button className="secondary" onClick={goBack} disabled={loading}>Back</button>
        <button data-wt="fit-run" onClick={onFit} disabled={!distribution || loading || !!groupProblem(selectedOpt, group)}
                title={groupProblem(selectedOpt, group) || undefined}>
          {loading ? "Fitting…" : `Fit ${distName}`}
        </button>
      </>
    );
  } else {
    // The name sits beside Save: it is only needed to save (#311).
    nav = (
      <>
        <button className="secondary" onClick={goBack} disabled={saving}>Back</button>
        <input
          className="fit-save-name"
          type="text"
          aria-label="Model name"
          title="Model name"
          value={name}
          placeholder="Model name"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSave()}
        />
        <button onClick={onSave} disabled={!name.trim() || saving}>
          {saving ? "Saving…" : "Save model"}
        </button>
      </>
    );
  }

  return (
    <div className="card fit-flow">
      {step === 1 && (
        <>
          <div className="source-toggle" role="tablist" aria-label="Data source">
            <button
              type="button"
              role="tab"
              aria-selected={source === "upload"}
              className={`source-tab${source === "upload" ? " active" : ""}`}
              onClick={() => { setSource("upload"); setError(null); }}
            >
              Upload CSV / Excel
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={source === "paste"}
              className={`source-tab${source === "paste" ? " active" : ""}`}
              onClick={() => { setSource("paste"); setError(null); }}
            >
              Paste values
            </button>
          </div>

          {source === "paste" && (
            <div className="paste-source">
              <textarea
                className="paste-area"
                value={pasted}
                spellCheck={false}
                autoFocus
                disabled={loading}
                placeholder={"One value per line, e.g.\n312\n420\n506\n\nor with a censoring flag:\n120 0\n340 0\n500 1"}
                onChange={(e) => { setPasted(e.target.value); setPasteFix(null); }}
              />
              {pasteFix && (
                <div className="row" style={{ margin: 0 }}>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => { setPasted(addMissingFlags(pasted)); setPasteFix(null); setError(null); }}
                  >
                    Add 0 (failed) to the {pasteFix.length} line{pasteFix.length === 1 ? "" : "s"} without a flag
                  </button>
                </div>
              )}
              <p className="hint" style={{ margin: 0 }}>
                Times to failure, one per line (or separated by commas / spaces).
                Add a second column for censoring: <b>0 = the unit failed</b>,{" "}
                <b>1 = it was still running</b> when observation stopped.
              </p>
              <div className="row" style={{ margin: 0 }}>
                <button type="button" onClick={usePasted} disabled={loading || !pasted.trim()}>
                  {loading ? "Reading values…" : "Use these values"}
                </button>
              </div>
            </div>
          )}

          {source === "upload" && (
          <div
            className={`dropzone${dragging ? " dragging" : ""}`}
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <span className="dz-ic">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 16V4m0 0 4 4m-4-4-4 4" />
                <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
              </svg>
            </span>
            {loading ? (
              <span className="dz-big">Reading file…</span>
            ) : file ? (
              <span className="dz-big filename">{file.name}</span>
            ) : (
              <span className="dz-big">
                Drop a CSV or Excel file here or <strong>click to browse</strong>
              </span>
            )}
            <span className="dz-hint">columns: time · censored · covariates</span>
            <input
              ref={inputRef}
              type="file"
              accept={`.csv,text/csv,${SPREADSHEET_ACCEPT}`}
              hidden
              onChange={(e) => { pickFile(e.target.files?.[0]); e.target.value = ""; }}
            />
          </div>
          )}
          {sheetModal}

          {usableDatasets("life", datasets).length > 0 && (
            <div className="recent">
              <div className="recent-h">Or use a saved dataset</div>
              {usableDatasets("life", datasets).slice(0, 5).map((d) => (
                <button
                  key={d.id}
                  type="button"
                  className="recent-row"
                  disabled={loading}
                  onClick={() => pickDataset(d)}
                >
                  <span className="recent-ic">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M14 3v5h5M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" />
                    </svg>
                  </span>
                  <span className="recent-name">{d.name}</span>
                  <span className="recent-meta">
                    {d.n_rows.toLocaleString()} rows · {d.n_columns} cols
                  </span>
                </button>
              ))}
            </div>
          )}

          {onPerDemand && (
            <div className="perdemand-cta">
              <span className="muted-line" style={{ margin: 0 }}>
                Not time-to-failure data? Model one-shot / protective equipment:
              </span>
              <button type="button" className="secondary" onClick={onPerDemand}>
                Per-demand
              </button>
            </div>
          )}
        </>
      )}

      {/* data-wt: the guided walkthrough's anchors (walkthroughs.js). */}
      {step === 2 && csv && (
        <div className="fit-step" data-wt="fit-data">
          <p className="muted-line">
            {sourceName === PASTED ? "Pasted values" : sourceName} · {csv.n_rows} rows
            {!simple && ` · ${csv.columns.length} columns`}
          </p>
          <HeaderNote note={headerNote} onPick={pickFile} disabled={loading} />
          {simple ? (
            <div className="ds-row">
              <RequiredUnit label="Unit of these times" value={unit} onChange={setUnit} listId="paste-units" autoFocus />
            </div>
          ) : (
            <>
              <PreviewTable columns={csv.columns} rows={csv.preview} />
              <ColumnMapper
                columns={csv.columns}
                mapping={mapping}
                onChange={setMapping}
                unit={unit}
                onUnitChange={setUnit}
                renderUnit={() => <RequiredUnit value={unit} onChange={setUnit} listId="x-units" />}
                facts={facts}
                timeVarying={tvc}
                failureMode
              />
              <ColumnRoles
                columns={csv.columns}
                mapping={mapping}
                covariates={advanced ? [] : covariates}
                facts={facts}
                timeVarying={tvc}
                covariatesAllowed={!advanced}
                failureMode
                onChange={(next, { col, role }) => {
                  // A unit guessed from the old time column follows the new one.
                  if (role === "x" && (!unit || unit === guessUnit(mapping.x))) setUnit(guessUnit(col));
                  setMapping(next.mapping);
                  if (!advanced) setCovariates(next.covariates);
                }}
              />
              <ResultDetails
                summary="Advanced (regression): covariates"
                open={covariates.length > 0 || advanced || !!tvc}
              >
                <TvcToggle layout={tvc} onChange={changeTvc} />
                <Covariates
                  columns={csv.columns}
                  selected={covariates}
                  onToggle={toggleCovariate}
                  advanced={advanced}
                  onSetAdvanced={setAdvanced}
                  formula={formula}
                  onSetFormula={setFormula}
                  disabledColumns={mappedColumns}
                  units={covUnits}
                  onSetUnit={(col, u) => setCovUnits((prev) => ({ ...prev, [col]: u }))}
                  folded
                />
              </ResultDetails>
            </>
          )}
          {problems.length > 0 ? (
            <ul className="ds-problems" role="status">
              {problems.map((p) => <li key={p}>{p}</li>)}
            </ul>
          ) : tvc ? (
            <p className="ds-summary" role="status">
              {tvcSummaryParts(mapping, facts, csv.n_rows, tvc).map((part, i) => {
                const [num, ...rest] = part.split(" ");
                return <span key={part}>{i > 0 && ", "}<b>{num}</b> {rest.join(" ")}</span>;
              })}
              <span className="ds-summary-note"> · covariates change over time</span>
            </p>
          ) : summary ? (
            <p className="ds-summary" role="status">
              {summaryParts(summary).map((part, i) => {
                const [num, ...rest] = part.split(" ");
                return (
                  <span key={part}>
                    {i > 0 && ", "}
                    <b>{num}</b> {rest.join(" ")}
                  </span>
                );
              })}
              {!mapping.c && (
                <span className="ds-summary-note">
                  {simple ? " · every value is a time to failure"
                    : mapping.e ? " · a blank failure mode is a unit still running"
                    : " · no status column, so every row is a failure"}
                </span>
              )}
            </p>
          ) : null}
          {problems.length === 0 && swapped && (
            <div className="ds-flag-notice" role="status">
              <span>
                Most units are marked as still running ({swapped.code}).
                If {swapped.code} means failed in your sheet, swap the flags.
              </span>
              <button type="button" className="secondary" onClick={swapFlags}>Swap the flags</button>
            </div>
          )}
          {problems.length === 0 && !swapped && simple && mapping.c && mapping.c_invert && (
            <p className="ds-flag-notice" role="status">
              <span>Flags swapped: 1 = failed, 0 = still running.</span>
              <button type="button" className="link" onClick={swapFlags}>Swap back</button>
            </p>
          )}
          {simple && (
            <button type="button" className="link ds-change" onClick={() => setSimple(false)}>
              Change columns
            </button>
          )}
        </div>
      )}

      {step === 3 && (
        <div className="fit-step">
          <p className="muted-line">
            {byMode
              ? hasCovariates
                ? `Failure modes from “${mapping.e}”, with covariates — choose a regression by mode.`
                : `Failure modes from “${mapping.e}” — they are fitted as competing risks.`
              : tvc
              ? "Covariates change over time — choose a regression model. Each item's covariates follow its rows."
              : hasCovariates
              ? "Covariates detected — choose a regression model (proportional-hazards or accelerated-failure-time)."
              : "Choose a parametric distribution or a non-parametric estimator."}
          </p>
          {byMode ? (
            <CompetingRisksStep
              options={options}
              value={distribution}
              onChange={setDistribution}
              columns={csv?.columns || []}
              mapping={mapping}
              onMapping={setMapping}
            />
          ) : (
          <DistributionStep
            options={options}
            value={distribution}
            onChange={(id) => {
              setDistribution(id);
              setFitOpts({}); // options are per-distribution (params differ)
            }}
            fitOpts={fitOpts}
            onFitOpts={setFitOpts}
            fitMethods={fitMethods}
            mapping={mapping}
            columns={csv?.columns || []}
            usedColumns={new Set([...mappedColumns, ...covariates])}
            group={group}
            onGroup={setGroup}
          />
          )}
          {hasCovariates && distribution === "cox_ph" && (
            <CoxOptions value={coxOpts} onChange={setCoxOpts} columns={coxColumns} />
          )}
        </div>
      )}

      {step === 4 && result && (
        <div className="fit-step" data-wt="fit-result">
          {/* Nothing is kept until it's saved: say so, with the one-click save (#434). */}
          <div className="fit-save-cta">
            <div className="fit-save-cta-text">
              <b>This fit isn't saved yet.</b>
              <span>
                {file
                  ? "Save the model and the data it was fitted to, to come back to them."
                  : "Save the model to come back to it."}
              </span>
            </div>
            <button type="button" onClick={onSave} disabled={!name.trim() || saving}
                    title={name.trim() ? undefined : "Name the model beside Save first"}>
              {saving ? "Saving…" : file ? "Save this model and its data" : "Save this model"}
            </button>
          </div>
          {/* The model page's frame, inside the wizard: the answer line and
              "Use this model" (which saves the fit first) over the tabs. */}
          <ModelFrame
            embedded
            notice={(
              <div className="mf-wizard-head">
                <AnswerLine parts={answerParts(result, { split })} />
                <ModelNextSteps result={result} onUse={saveForUse} variant="primary" />
              </div>
            )}
          >
            <ResultView
              result={result}
              split={split}
              compare={result.kind === "distribution" && !hasCovariates ? compareFit : null}
              onPick={ownOptions ? null : pickFit}
              onUse={saveForUse}
            />
          </ModelFrame>
        </div>
      )}

      {error && <div className="error">{error}</div>}

      <div className="fit-flow-foot">
        {stepper}
        <div className="row" style={{ margin: 0 }}>{nav}</div>
      </div>
    </div>
  );
}
