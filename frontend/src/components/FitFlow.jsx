import { useEffect, useMemo, useRef, useState } from "react";
import { ErrorNotice } from "./StorageCap.jsx";
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
import Covariates from "./Covariates.jsx";
import PreviewTable from "./PreviewTable.jsx";
import XRangeWarning from "./XRangeWarning.jsx";
import HeaderNote, { detectHeader } from "./HeaderNote.jsx";
import { useUnsavedFitScope } from "./UnsavedFitReminder.jsx";
import { useAskText } from "./ConfirmProvider.jsx";
import { PASTED_FILE, dataName, defaultFitName } from "../fitName.js";
import { forgetUnsavedFit, rememberUnsavedFit, unsavedFitRecord } from "../unsavedFit.js";
import CoxOptions from "./CoxOptions.jsx";
import DistributionStep from "./DistributionStep.jsx";
import CompetingRisksStep, { CR_OPTIONS } from "./CompetingRisksStep.jsx";
import { frailtyFitOptions, groupProblem, withGroup } from "../moreModels.js";
import DatasetPicker, { DatasetGlance } from "./DatasetPicker.jsx";
import ResultView from "./ResultView.jsx";
import ModelFrame, { AnswerLine } from "./model/ModelFrame.jsx";
import ModelNextSteps from "./ModelNextSteps.jsx";
import { answerParts } from "../modelFrame.js";
import { ResultDetails } from "./ui/ResultSummary.jsx";
import { TvcToggle } from "./TvcColumns.jsx";
import { guessTvc, tvcMapping, tvcProblems, tvcUnit } from "../tvcData.js";
import { isNumeric, timeUnitOf } from "../datasetGuess.js";
import {
  EMPTY_MAPPING, columnFacts, isSimplePaste, startingMapping, statusSummary, summaryParts,
  dataStepProblems, dataStepIssues, dataSplit, parsePastedValues, addMissingFlags, flagsLookSwapped, mappingWords,
  dataQuestions, answerQuestion, unitCounts, keptChoices, dataStepNotes, issueRow,
} from "../lifeData.js";
import { RequiredUnit } from "./Units.jsx";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import { Select } from "./ui/Controls.jsx";
import LibraryRecordPicker from "./LibraryRecordPicker.jsx";
import { useRecordCovariates } from "./LibraryParts.jsx";
import { FitOutcome, PriorFields } from "./PriorFit.jsx";
import { METHOD_CHOICES, METHOD_LINE, initialFit, refusalWords, showsTrust } from "../fitDialog.js";
import {
  DATASET_PRIOR_CHOICES, priorAsksDistribution, priorBlocked, priorProblem, priorRequest,
} from "../priorFit.js";
import { fitDatasetWithPrior, getDataReading, getLibraryRecord, getLibrarySources, listModels } from "../api.js";
import { rowFromDetail } from "../libraryPicker.js";

const STEPS = ["Source", "Data", "Model", "Result"];
// Where the data comes from: a saved dataset first (most users have one), then typed or pasted values, then a file.
const SOURCES = [
  { value: "saved", label: "Saved data" },
  { value: "paste", label: "Paste or type" },
  { value: "upload", label: "Upload a file" },
];
const PASTED = PASTED_FILE;

// A saved dataset's detail in the shape /api/columns gives.
const datasetColumns = (full) => ({
  columns: full.preview_columns || [],
  preview: full.preview || [],
  // Wholly blank rows are skipped by every fit, so they aren't counted.
  n_rows: full.n_rows - (full.blank_rows || 0),
  blank_rows: full.blank_rows || 0,
  n_unique: full.n_unique,
  dtypes: full.dtypes,
  blanks: full.blanks,
  values: full.values,
  whole: full.whole,
  nonpositive: full.nonpositive,
});

// The paste parser lives in lifeData.js (unit-tested there).
export { parsePastedValues };

// Fit flow rendered as a page panel: (1) pick a data source, (2) map columns
// (+ unit, covariates), (3) pick a model and fit, (4) review the fit, then
// name it beside Save and save — with Back to change anything and re-fit before saving. Calls
// ``onSaved`` with the saved model; ``onCancel`` backs out to the list.
// ``initialSource`` opens the source step on "saved" (default: the user's
// datasets and the samples), "paste" or "upload".
// Non-parametric estimators that need exact failure times: inspection data
// (failed between two times) takes Turnbull instead.
const EXACT_TIMES_ONLY = ["kaplan_meier", "nelson_aalen", "fleming_harrington"];

export default function FitFlow({ onSaved, onCancel, onPerDemand, initialDatasetId, autoFit, initialSource }) {
  const [step, setStep] = useState(1);
  // Source step: "saved" (a saved dataset), "paste" (values typed / pasted in) or "upload" (a file).
  const [source, setSource] = useState(SOURCES.some((o) => o.value === initialSource) ? initialSource : "saved");
  // The saved dataset picked on the source step, before Next: { summary, detail, error }.
  const [picked, setPicked] = useState(null);
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
  // Questions about the first reading already answered "no" (see dataQuestions).
  const [answered, setAnswered] = useState([]);
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
  // The model whose column reading a dataset's fit started from, or null.
  const [keptFrom, setKeptFrom] = useState(null);
  const [distribution, setDistribution] = useState("weibull");
  const [fitOpts, setFitOpts] = useState({});
  const [coxOpts, setCoxOpts] = useState({}); // Cox PH: ties, strata, cluster (#61)
  // A shared-frailty model's Group by column (#179), sent with the mapping.
  const [group, setGroup] = useState("");
  const [datasets, setDatasets] = useState(null); // null while the list loads
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [dragging, setDragging] = useState(false);
  // An Excel workbook becomes a CSV of the chosen sheet before anything else.
  // Part of the source step, not a modal over it.
  const { toCsv, modal: sheetModal } = useSpreadsheet({ inline: true });
  const inputRef = useRef(null);

  // Step 4 (Result): the fit, a name, and the save action.
  const [result, setResult] = useState(null);
  const [split, setSplit] = useState(null);
  const [name, setNameRaw] = useState("");
  // Whether the user has typed a name: until they have, Save asks for one,
  // starting from the default (the distribution and the data's name).
  const [nameTyped, setNameTyped] = useState(false);
  const setName = (value) => { setNameRaw(value); setNameTyped(false); };
  const typeName = (value) => { setNameRaw(value); setNameTyped(true); };
  const askText = useAskText();
  const [saving, setSaving] = useState(false);
  const [fitMethods, setFitMethods] = useState([]);

  // "With a prior" (the Model step's Method): the prior asked for the way the Explorer's "Fit a life
  // model…" asks (PriorFit.jsx, fitDialog.js), fitted through the same prior path on the server
  // (/api/models/fit-with-prior). ``priorResult`` is its answer on the Result step.
  const [method, setMethod] = useState("mle");
  const [prior, setPrior] = useState(() => initialFit({ method: "bayes", priorKind: "model" }));
  const setP = (k, v) => setPrior((s) => ({ ...s, [k]: v }));
  const [priorModels, setPriorModels] = useState(null);
  const [record, setRecord] = useState(null);
  const [pickingRecord, setPickingRecord] = useState(false);
  const pickArea = useRef(null);
  const [priorResult, setPriorResult] = useState(null);
  const [chart, setChart] = useState("sf");
  const libCov = useRecordCovariates(method === "bayes" ? prior.recordId : null);
  const libSig = JSON.stringify([libCov.toSave, libCov.missing.map((i) => i.label)]);
  useEffect(() => {
    setPrior((s) => ({ ...s, libCov: libCov.toSave, libMissing: libCov.missing.map((i) => i.label) }));
  }, [libSig]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (method !== "bayes" || priorModels !== null) return undefined;
    let live = true;
    listModels().then((out) => live && setPriorModels((out.models || []).filter((m) => m.kind === "distribution"
      && /weibull|exponential|lognormal/i.test(m.distribution || ""))), () => live && setPriorModels([]));
    return () => { live = false; };
  }, [method, priorModels]);
  // A library record named by id (picked, or the picker's row): read for the words beside it.
  useEffect(() => {
    if (!prior.recordId || record?.id === prior.recordId) return undefined;
    let live = true;
    Promise.all([getLibraryRecord(prior.recordId), getLibrarySources().catch(() => ({ sources: [] }))])
      .then(([d, src]) => live && setRecord(rowFromDetail(d, src.sources)), () => {});
    return () => { live = false; };
  }, [prior.recordId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    getDistributions()
      .then((d) => { setDistributions(d.distributions); setFitMethods(d.fit_methods || []); })
      .catch(() =>
        setDistributions([{ id: "weibull", name: "Weibull", covariates: false }])
      );
    listDatasets()
      .then((d) => setDatasets(d.datasets || []))
      .catch(() => setDatasets([]));
  }, []);

  // Whether the data implies a proportional-hazards model.
  const hasCovariates = advanced ? formula.trim() !== "" : covariates.length > 0;

  // Model options filtered by the data that was entered. A failure-mode
  // column (#177) fits the modes as competing risks.
  const byMode = !!mapping.e;
  // Covariates over time (#60) take the regressions that can fit them.
  // Inspection data (an earliest and a latest time) takes Turnbull, not the
  // estimators that need exact failure times: those aren't offered.
  const intervalTimes = !!(mapping.xl || mapping.xr);
  const options = useMemo(
    () => (byMode ? CR_OPTIONS : distributions)
      .filter((d) => !!d.covariates === hasCovariates && (!tvc || d.tvc !== false)
        && !(intervalTimes && EXACT_TIMES_ONLY.includes(d.id))),
    [distributions, hasCovariates, byMode, tvc, intervalTimes]
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
  // ``saved``: a dataset's ``last_mapping``, how its newest model read the
  // columns (the status words, the late-entry column): used when it fits.
  // ``previous``: the choices made on the file loaded before; a corrected copy
  // of it (every column they name still there) keeps them.
  const loadColumns = (cols, simplePaste = false, saved = null, previous = null) => {
    const facts = columnFacts(cols);
    const again = simplePaste ? null : keptChoices(previous, cols.columns);
    if (again) {
      setCsv(cols);
      setMapping(again.mapping);
      setTvc(again.tvc);
      setUnit(again.unit);
      setSimple(false);
      setCovariates(again.covariates);
      setKeptFrom("the file you loaded before");
      return { mapping: again.mapping, unit: again.unit };
    }
    // The saved reading when it still reads cleanly, else a fresh guess (startingMapping).
    const g = startingMapping(simplePaste ? null : saved, cols.columns, facts, cols.n_rows);
    const kept = g.from ? g : null;
    const map = simplePaste
      // A pasted flag column is 0 = failed, 1 = still running, as the paste box says.
      ? { ...EMPTY_MAPPING, x: "time", c: cols.columns.includes("censored") ? "censored" : "" }
      : g.mapping;
    setKeptFrom(kept ? `“${kept.from || "the last model"}”, the last model fitted to this dataset` : null);
    // Start and stop rows of items (#60): fit their covariates over time.
    const timeVarying = simplePaste ? null
      : kept ? (kept.mapping.i ? "intervals" : null) : guessTvc(cols.columns, facts, cols.n_rows);
    const tvcMap = timeVarying && !kept && tvcMapping(map, "intervals", cols.columns, facts, cols.n_rows);
    const used = new Set(Object.values(tvcMap || {}).filter((v) => typeof v === "string" && v));
    setCsv(cols);
    setAnswered([]);
    setMapping(tvcMap || map);
    setTvc(timeVarying ? "intervals" : null);
    const guessedUnit = simplePaste ? "" : (timeVarying && tvcUnit(timeVarying)) || g.unit || "";
    setUnit(guessedUnit);
    setSimple(simplePaste);
    setCovariates(timeVarying ? cols.columns.filter((c) => !used.has(c) && isNumeric(facts[c]?.dtype)) : []);
    setGroup("");
    return { mapping: tvcMap || map, unit: guessedUnit };
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
      // A corrected copy of the file loaded before keeps the choices made on it.
      const previous = csv && file && file.name !== PASTED && !simple
        ? { mapping, unit, covariates: advanced ? [] : covariates, tvc } : null;
      loadColumns(cols, isSimplePaste(cols.columns) && use.name === PASTED, null, previous);
      setStep(2);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // A saved dataset picked in the list: read its detail for the pane beside
  // the list (its first rows and how its columns will be read). Nothing in
  // the flow changes until Next.
  const pickSaved = (d) => {
    setError(null);
    setPicked({ summary: d, detail: null, error: null });
    getDataset(d.id).then(
      (full) => setPicked((p) => (p?.summary.id === d.id ? { ...p, detail: full } : p)),
      (err) => setPicked((p) => (p?.summary.id === d.id ? { ...p, error: err.message } : p)),
    );
  };
  // The picked dataset's guessed columns, for the pane (the Data step starts from the same guess).
  const pickedGuess = useMemo(() => {
    if (!picked?.detail) return null;
    const cols = datasetColumns(picked.detail);
    const facts = columnFacts(cols);
    const g = startingMapping(picked.detail.last_mapping, cols.columns, facts, cols.n_rows);
    const status = statusSummary(g.mapping, facts, cols.n_rows);
    // Where the reading is a guess, the pane asks rather than counts.
    const questions = dataQuestions(g.mapping, facts, cols.columns, cols.n_rows);
    return {
      words: mappingWords(g.mapping, facts, g.unit),
      problems: dataStepProblems(g.mapping, facts, cols.n_rows, g.unit),
      summary: status && !questions.length ? summaryParts(status) : [],
      questions,
    };
  }, [picked?.detail]);
  // Next on a picked dataset: its columns into the Data step — no re-upload needed.
  const useSaved = () => {
    const full = picked?.detail;
    if (!full) return;
    setFile(null);
    setHeaderNote(null);
    setDatasetId(full.id);
    setSourceName(full.name);
    setError(null);
    loadColumns(datasetColumns(full), false, full.last_mapping);
    setStep(2);
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
        const { mapping: map, unit: guessedUnit } = loadColumns(datasetColumns(full), false, full.last_mapping);
        if (autoFit && map.x) {
          const res = await fitModel("weibull", null, map, { datasetId: initialDatasetId, unit: guessedUnit });
          setSplit(null);
          setResult(res);
          setName(defaultFitName(res.distribution, { sourceName: full.name }));
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
  // Each with the column it comes from, shown beside the selector it concerns.
  const issues = useMemo(
    () => (!csv ? [] : tvc ? tvcProblems(mapping, facts, tvc, hasCovariates ? 1 : 0).map((text) => ({ col: null, text }))
      : dataStepIssues(mapping, facts, csv.n_rows, unit)),
    [csv, mapping, facts, tvc, hasCovariates, unit]
  );
  const problems = useMemo(() => issues.map((i) => i.text), [issues]);
  // Covariates over time on or off, or the rows' layout changed (#60).
  const changeTvc = (layout) => {
    setTvc(layout);
    setMapping((m) => tvcMapping(m, layout, csv.columns, facts, csv.n_rows));
  };
  // Where the first reading is a guess (a blank failure mode, a status-like
  // column left unused), the step asks before it counts or fits.
  const questions = useMemo(
    () => (csv && !tvc && !simple ? dataQuestions(mapping, facts, csv.columns, csv.n_rows, answered) : []),
    [csv, tvc, simple, mapping, facts, answered]
  );
  const answer = (q, yes) => {
    const next = answerQuestion(mapping, q, yes, facts, answered);
    if (yes && q.field === "u" && !timeUnitOf(unit)) {
      const counts = unitCounts(q.column, facts) || {};
      const common = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0];
      if (common) setUnit(common);
    }
    setMapping(next.mapping);
    setAnswered(next.answered);
  };
  // A range (xl to xr, with or without x) is read row by row, so its count
  // comes from the server, as the fit will read it: { failed, running, left,
  // interval, notes, x_and_range_rows } or { error }.
  const [reading, setReading] = useState(null);
  const inspection = !!(csv && !tvc && mapping.xl && mapping.xr);
  // A tr column is checked row by row on the server too (a value above it).
  const readRows = inspection || !!(csv && !tvc && mapping.tr);
  useEffect(() => {
    setReading(null);
    if (!readRows || problems.length > 0 || (!file && !datasetId)) return undefined;
    let live = true;
    getDataReading(file, mapping, datasetId).then(
      (r) => live && setReading(r),
      (err) => live && setReading({ error: err.message }),
    );
    return () => { live = false; };
  }, [readRows, problems.length, file, datasetId, mapping]);
  const mappingValid = problems.length === 0 && questions.length === 0 && !reading?.error && !reading?.tr_problem;
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
  const summary = !csv || tvc || questions.length ? null
    : inspection ? (reading && !reading.error ? reading : null)
    : statusSummary(mapping, facts, csv.n_rows) || fileSplit;
  // Most units still running often means the sheet's flags are 1 = failed:
  // say so on the Data step, with the same flip the column mapper uses.
  const swapped = flagsLookSwapped(mapping, summary);
  const swapFlags = () => {
    if (mapping.c) setAnswered((a) => [...a, `flags:${mapping.c}`]);
    setMapping((m) => ({ ...m, c_invert: !m.c_invert }));
  };
  const swappedNotice = swapped && (
    <div className="ds-flag-notice" role="status">
      <span>
        Most units are marked as still running ({swapped.code}).
        If {swapped.code} means failed in your sheet, swap the flags.
      </span>
      <button type="button" className="secondary" onClick={swapFlags}>Swap the flags</button>
    </div>
  );

  // Questions, and the flags notice, sit beside the selector they concern.
  const asides = { x: [], c: [], e: [], tr: [] };
  if (problems.length === 0) {
    for (const q of questions) {
      const row = q.field === "u" ? "x" : q.field === "e" ? "e" : "c";
      asides[row].push(
        <div className="ds-flag-notice" role="group" aria-label="A question about this column" key={q.id}>
          <span>{q.text}</span>
          <button type="button" className="secondary" onClick={() => answer(q, true)}>{q.yes}</button>
          <button type="button" className="secondary" onClick={() => answer(q, false)}>{q.no}</button>
        </div>,
      );
    }
    if (swapped && mapping.c) asides.c.push(<div key="swapped">{swappedNotice}</div>);
    if (reading?.error) asides.x.push(<p className="xcn-issue" role="status" key="reading">{reading.error}</p>);
    if (reading?.tr_problem) asides.tr.push(<p className="xcn-issue" role="status" key="tr">{reading.tr_problem.text}</p>);
    for (const note of reading?.notes || []) {
      asides.x.push(<p className="ds-flag-notice" role="status" key={note}><span>{note}</span></p>);
    }
  }
  // Next is never greyed without the reason beside it.
  const rowNames = { x: "x", c: "c", n: "n", tl: "tl", tr: "tr", e: "failure mode" };
  const flaggedRows = [...new Set([...issues.map((i) => issueRow(i, mapping)),
    ...(problems.length === 0 && reading?.tr_problem ? ["tr"] : []),
    ...(problems.length === 0 ? questions.map((q) => (q.field === "u" ? "x" : q.field === "e" ? "e" : "c")) : [])])];
  const waitingFor = mappingValid ? null
    : simple && problems.length ? problems[0]
    : flaggedRows.length ? `First settle the note${flaggedRows.length === 1 ? "" : "s"} beside ${flaggedRows.map((r) => rowNames[r]).join(", ")}.`
    : reading?.error ? "First settle the note beside x."
    : "Waiting for the rows to be read…";

  // Cox PH's own options travel with a Cox fit only.
  const familyOpts = frailtyFitOptions(options.find((d) => d.id === distribution), fitOpts);
  const coxFit = distribution === "cox_ph" ? { fitOptions: { cox: coxOpts } }
    : familyOpts ? { fitOptions: familyOpts } : {};
  const coxColumns = (csv?.columns || []).filter(
    (c) => !mappedColumns.has(c) && !(advanced ? false : covariates.includes(c)));

  // Whether this data can take a prior, and what the prior still needs.
  const priorBlock = csv ? priorBlocked(mapping, { hasCovariates, tvc }) : null;
  const bayes = method === "bayes" && !priorBlock;
  const priorWanting = bayes ? priorProblem(prior, unit) : null;
  useEffect(() => {
    if (priorBlock && method === "bayes") setMethod("mle");
  }, [priorBlock, method]);
  const priorSource = async () => (datasetId ? { datasetId } : { content: await file.text() });
  const askPrior = async (extra = {}) =>
    fitDatasetWithPrior(priorRequest(prior, mapping, unit, await priorSource(), extra));
  const onFitPrior = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await askPrior();
      if (res.refused) {
        setError(refusalWords(res.refused));
        return;
      }
      setPriorResult(res);
      setResult(null);
      setName(defaultFitName(res.distribution_label || res.distribution,
                             { fileName: file?.name, sourceName }, { prior: true }));
      setStep(4);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };
  // The age asked about on the Result step: asked again a moment after it's typed.
  const priorAge = prior.age;
  const priorNeed = prior.need;
  useEffect(() => {
    if (step !== 4 || !priorResult) return undefined;
    let live = true;
    const t = setTimeout(() => {
      askPrior().then((res) => live && !res.refused && setPriorResult(res), () => {});
    }, 400);
    return () => { live = false; clearTimeout(t); };
  }, [priorAge, priorNeed]); // eslint-disable-line react-hooks/exhaustive-deps

  const onFit = async () => {
    if (!file && !datasetId) return;
    if (bayes) return onFitPrior();
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
      setSplit((await dataSplit(file, mapping).catch(() => null)) || res.split || null);
      setResult(res);
      setName(defaultFitName(res.distribution, { fileName: file?.name, sourceName }));
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
      setName(defaultFitName(res.distribution, { fileName: file?.name, sourceName }));
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
  const persist = async (as = name) => {
    // Pasted values are saved as a dataset named for them and the day, not "pasted-values".
    const upload = file?.name === PASTED
      ? new File([file], `${dataName({ fileName: PASTED })}.csv`, { type: file.type || "text/csv" })
      : file;
    const model = await saveModel(as.trim(), distribution, upload, fitMapping, {
      ...saveOpts, datasetId: datasetId || undefined,
    });
    forgetUnsavedFit(fitScope);
    return model;
  };

  useEffect(() => {
    if (step !== 4 || !result || priorResult || !name.trim()) return;
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
    // Not named yet: ask, starting from the default, so a model never ends up
    // called "pasted-values" by accident (it's what goes in a report).
    let as = name.trim();
    if (!nameTyped) {
      const answer = await askText({
        title: "Name this model",
        body: "Give it a name you'll recognise later, in lists and reports. You can rename it any time.",
        label: "Model name",
        value: as,
        confirmLabel: file ? "Save model and data" : "Save model",
      });
      if (answer == null || !String(answer).trim()) return;
      as = String(answer).trim();
      typeName(as);
    }
    remembered.current += 1; // a remember still reading the file is stale now
    setSaving(true);
    setError(null);
    try {
      if (priorResult) {
        // Saved as a Bayesian model: its prior (what it was, how far it was trusted) kept with it.
        const saved = await askPrior({ save: true, name: as });
        if (saved.refused) throw new Error(refusalWords(saved.refused));
        onSaved?.(saved);
        return;
      }
      onSaved?.(await persist(as));
    } catch (err) {
      setError(err);
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
    if (step === 4) setPriorResult(null);
    setStep((s) => s - 1);
  };

  const stepper = (
    <div className="steps">
      {STEPS.map((label, i) => {
        const n = i + 1;
        return (
          <span className="step-wrap" key={label}>
            {i > 0 && <span className="sep" />}
            <span className={`step${step === n ? " active" : ""}`} aria-current={step === n ? "step" : undefined}>
              <span className="dot">{n}</span>
              <span className="step-label">{label}</span>
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
        {source === "saved" ? (
          <button data-wt="fit-source-next" onClick={useSaved} disabled={!picked?.detail || loading}
                  title={picked ? undefined : "Pick a dataset first"}>
            Next
          </button>
        ) : (
          <span className="hint" style={{ margin: 0 }}>
            {source === "paste" ? "Paste your values to continue" : "Upload a CSV or Excel file to continue"}
          </span>
        )}
      </>
    );
  } else if (step === 2) {
    // Next is never greyed without the reason beside it.
    nav = (
      <>
        <button className="secondary" onClick={goBack} disabled={loading}>Back</button>
        {!mappingValid && <span className="hint ds-next-why" role="status" style={{ margin: 0 }}>{waitingFor}</span>}
        <button data-wt="fit-next" onClick={() => setStep(3)} disabled={!mappingValid}>Next</button>
      </>
    );
  } else if (step === 3) {
    nav = (
      <>
        <button className="secondary" onClick={goBack} disabled={loading}>Back</button>
        {bayes ? (
          <button data-wt="fit-run" onClick={onFit} disabled={loading || !!priorWanting} title={priorWanting || undefined}>
            {loading ? "Fitting: about 10 seconds…" : "Fit with the prior"}
          </button>
        ) : (
          <button data-wt="fit-run" onClick={onFit} disabled={!distribution || loading || !!groupProblem(selectedOpt, group)}
                  title={groupProblem(selectedOpt, group) || undefined}>
            {loading ? "Fitting…" : `Fit ${distName}`}
          </button>
        )}
      </>
    );
  } else {
    // The name and Save sit in the "isn't saved yet" banner above (#311).
    nav = <button className="secondary" onClick={goBack} disabled={saving}>Back</button>;
  }

  return (
    <div className="card fit-flow">
      <div className="fit-flow-head">{stepper}</div>
      {step === 1 && (
        <>
          <div className="source-toggle" role="tablist" aria-label="Where the data comes from">
            {SOURCES.map((o) => (
              <button
                key={o.value}
                type="button"
                role="tab"
                aria-selected={source === o.value}
                className={`source-tab${source === o.value ? " active" : ""}`}
                onClick={() => { setSource(o.value); setError(null); }}
              >
                {o.label}
              </button>
            ))}
          </div>

          {source === "saved" && (
            <DatasetPicker kind="life" datasets={datasets} value={picked?.summary.id} onPick={pickSaved} disabled={loading}>
              {picked && (
                <DatasetGlance summary={picked.summary} detail={picked.detail} error={picked.error}>
                  {pickedGuess && (
                    <>
                      <div className="dsp-quiet">How its columns will be read (change them on the next step):</div>
                      <dl className="dsp-reads">
                        {pickedGuess.words.map((w) => (
                          <div key={w.label} style={{ display: "contents" }}>
                            <dt>{w.label}</dt>
                            <dd>{w.value}</dd>
                          </div>
                        ))}
                      </dl>
                      {pickedGuess.problems.length > 0 ? (
                        <ul className="ds-problems" role="status">
                          {pickedGuess.problems.map((p) => <li key={p}>{p}</li>)}
                        </ul>
                      ) : pickedGuess.questions.length > 0 ? (
                        <p className="ds-flag-notice" role="status">
                          <span>{pickedGuess.questions[0].text} The next step asks.</span>
                        </p>
                      ) : pickedGuess.summary.length > 0 ? (
                        <p className="ds-summary" role="status">
                          {pickedGuess.summary.map((part, i) => {
                            const [num, ...rest] = part.split(" ");
                            return <span key={part}>{i > 0 && ", "}<b>{num}</b> {rest.join(" ")}</span>;
                          })}
                        </p>
                      ) : null}
                    </>
                  )}
                </DatasetGlance>
              )}
            </DatasetPicker>
          )}

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

          {source === "upload" && !sheetModal && (
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
            {sourceName === PASTED ? "Pasted values" : sourceName} · {csv.n_rows.toLocaleString()} rows
          </p>
          <HeaderNote note={headerNote} onPick={pickFile} disabled={loading} />
          {keptFrom && (
            <p className="muted-line" role="status">Columns read as for {keptFrom}.</p>
          )}
          {simple ? (
            <>
              <div className="ds-row">
                <RequiredUnit label="Unit of these values" value={unit} onChange={setUnit} listId="paste-units" autoFocus />
              </div>
              {problems.length > 0 && (
                <ul className="ds-problems" role="status">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
              )}
              {problems.length === 0 && mapping.c && mapping.c_invert && !swapped && (
                <p className="ds-flag-notice" role="status">
                  <span>Flags swapped: 1 = failed, 0 = still running.</span>
                  <button type="button" className="link" onClick={swapFlags}>Swap back</button>
                </p>
              )}
              {problems.length === 0 && swapped && swappedNotice}
              <button type="button" className="link ds-change" onClick={() => setSimple(false)}>
                Change columns
              </button>
            </>
          ) : (
            <>
              <PreviewTable columns={csv.columns} rows={csv.preview} />
              <ColumnMapper
                columns={csv.columns}
                mapping={mapping}
                onChange={(next, how) => {
                  // Meanings set by hand answer the which-way-round question.
                  if (how?.meanings && mapping.c) setAnswered((a) => [...a, `flags:${mapping.c}`]);
                  setMapping(next);
                }}
                unit={unit}
                onUnitChange={setUnit}
                facts={facts}
                timeVarying={tvc}
                failureMode
                issues={issues}
                notes={tvc ? [] : dataStepNotes(mapping, facts)}
                asides={asides}
                warning={<XRangeWarning reading={reading} />}
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
        </div>
      )}

      {step === 3 && (
        <div className="fit-step">
          <div className="fit-method" role="group" aria-label="Method">
            <span className="fit-method-l">Method</span>
            <ChoiceChips
              label="Method"
              className="sm"
              value={bayes ? "bayes" : "mle"}
              onChange={(v) => v && !(v === "bayes" && priorBlock) && setMethod(v)}
              options={METHOD_CHOICES.map((o) => (o.value === "bayes" && priorBlock
                ? { ...o, disabled: true, title: priorBlock } : o))}
            />
            <span className="fit-method-note">{priorBlock && method !== "bayes" ? priorBlock : METHOD_LINE[bayes ? "bayes" : "mle"]}</span>
          </div>
          {bayes ? (
            <div className="fit-prior rw-sg rw-steps-first fit2-grid">
              <div className="rw-sl">Prior</div>
              <div className="rw-sc">
                <PriorFields
                  state={prior}
                  set={setP}
                  kind={prior.priorKind}
                  kinds={DATASET_PRIOR_CHOICES}
                  onKind={(k) => {
                    setP("priorKind", k);
                    if (k === "library" && !prior.recordId) setPickingRecord(true);
                  }}
                  trust={showsTrust(prior.priorKind)}
                  models={priorModels}
                  record={record}
                  libCov={libCov}
                  onPickRecord={() => setPickingRecord(true)}
                  pickArea={pickArea}
                  unit={unit ? unit.toLowerCase() : null}
                />
              </div>
              {priorAsksDistribution(prior.priorKind) && (
                <>
                  <div className="rw-sl">Distribution</div>
                  <div className="rw-sc">
                    <Select aria-label="Distribution" value={prior.distribution === "best" ? "weibull" : prior.distribution}
                            onChange={(e) => setP("distribution", e.target.value)}>
                      <option value="weibull">Weibull</option><option value="exponential">Exponential</option><option value="lognormal">Lognormal</option>
                    </Select>
                  </div>
                </>
              )}
              {priorWanting && <p className="hint fit-prior-wanting" role="status">{priorWanting}</p>}
            </div>
          ) : (
          <>
          <p className="muted-line">
            {byMode
              ? hasCovariates
                ? `Failure modes from “${mapping.e}”, with covariates — choose a regression by mode.`
                : `Failure modes from “${mapping.e}” — they are fitted as competing risks. To fit every failure as one, set “${mapping.e}” to Ignore on the Data step.`
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
          </>
          )}
          {pickingRecord && (
            <LibraryRecordPicker use="prior" selectedId={prior.recordId}
                                 onClose={() => setPickingRecord(false)}
                                 onPick={(r) => { setP("recordId", r.id); setRecord(r); setPickingRecord(false); }} />
          )}
        </div>
      )}

      {step === 4 && (result || priorResult) && (
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
            {/* The one primary action on the Result step: name it, save it. */}
            <div className="fit-save-cta-actions">
              <input
                className="fit-save-name"
                type="text"
                aria-label="Model name"
                title="Model name"
                value={name}
                placeholder="Model name"
                onChange={(e) => typeName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && onSave()}
              />
              <button type="button" onClick={onSave} disabled={!name.trim() || saving}
                      title={name.trim() ? undefined : "Name the model beside Save first"}>
                {saving ? "Saving…" : file ? "Save this model and its data" : "Save this model"}
              </button>
            </div>
          </div>
          {priorResult ? (
            // A fit with a prior: the prior's curve dashed under the fitted one with its credible
            // band, as the Explorer shows it (PriorFit.jsx).
            <div className="fit2-out fit-prior-out">
              <FitOutcome d={priorResult} priorKind={prior.priorKind} unit={(priorResult.unit || "").toLowerCase()}
                          chart={chart} onChart={setChart} download={name || "Life model"}
                          age={prior.age} onAge={(v) => setP("age", v)}
                          need={prior.need} onNeed={(v) => setP("need", v)}
                          dataWords={file?.name === PASTED ? "the pasted values" : `“${(file?.name || sourceName || "the data").replace(/\.csv$/i, "")}”`} />
            </div>
          ) : (
          <>
          {/* The model page's frame, inside the wizard: the answer line and
              "Use this model" (which saves the fit first) over the tabs. */}
          <ModelFrame
            embedded
            notice={(
              <div className="mf-wizard-head">
                <AnswerLine parts={answerParts(result, { split })} />
                <ModelNextSteps result={result} onUse={saveForUse} />
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
          </>
          )}
        </div>
      )}

      <ErrorNotice error={error} />

      <div className="fit-flow-foot">
        <div className="row" style={{ margin: 0 }}>{nav}</div>
      </div>
    </div>
  );
}
