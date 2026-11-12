// A fleet forecast's items in bulk, in a pane inside the Items card (not a
// dialog): paste a block from Excel, upload a CSV or Excel file, or take the
// units still running in the model's own data. Columns are mapped by header
// with a preview ("30 items read; 2 rows skipped") before anything is added.
// The reading is fleetItemsImport.js; the page saves the items as usual.
import { useEffect, useMemo, useRef, useState } from "react";
import Select from "./Select.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import ScrollCue from "./ui/ScrollCue.jsx";
import {
  SPREADSHEET_ACCEPT, excelToCsvFile, inspectExcel, isSpreadsheetFile, getFleetRunningUnits,
} from "../api.js";
import { nextSheet } from "../sheetChoice.js";
import { CONVERTIBLE_UNITS } from "../datasetGuess.js";
import {
  MAX_ITEMS, calendarUnit, guessAgeUnit, mergeItems, readBlock, readItems, summary, targets,
} from "../fleetItemsImport.js";
import { formatNumber } from "../format.js";

const PREVIEW_ROWS = 5;

// The button that opens the pane on "the model's data", with its count when known.
export function runningUnitsLabel(units) {
  if (!units || !units.running) return null;
  const n = units.running;
  return units.kind === "systems"
    ? `Use the ${n} system${n === 1 ? "" : "s"} in this model's data`
    : `Use the ${n} still-running unit${n === 1 ? "" : "s"} from this model's data`;
}

export function useRunningUnits(fleetId, enabled) {
  const [units, setUnits] = useState(null);
  useEffect(() => {
    if (!enabled) return undefined;
    let live = true;
    getFleetRunningUnits(fleetId).then((u) => live && setUnits(u)).catch(() => live && setUnits(null));
    return () => { live = false; };
  }, [fleetId, enabled]);
  return units;
}

export default function FleetItemsImport({
  mode, onMode, existing, onApply, unit, fields = [], repairable = false, warranty = false, defaultRate,
  periodLabel, runningUnits,
}) {
  const [text, setText] = useState("");
  const [fileNote, setFileNote] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [mapping, setMapping] = useState(null);
  const [ageUnit, setAgeUnit] = useState(null);
  const [workbook, setWorkbook] = useState(null); // { file, sheets, sheet }
  const fileRef = useRef(null);
  const opts = { fields, repairable, warranty };
  const modelCal = calendarUnit(unit);

  const block = useMemo(() => (mode === "model" ? null : readBlock(text, opts)),
    // opts is rebuilt each render from these
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [text, mode, fields, repairable, warranty]);
  const map = mapping && block && mapping.length === block.headers.length ? mapping : block?.mapping || [];
  const ageCol = map.indexOf("current_use");
  const guessedUnit = block && ageCol >= 0
    ? guessAgeUnit(block.headers[ageCol], block.rows.slice(0, 20).map((r) => r[ageCol])) : "";
  const fromUnit = ageUnit ?? (CONVERTIBLE_UNITS.includes(guessedUnit) ? guessedUnit : "");

  const result = useMemo(() => {
    if (mode === "model") {
      return runningUnits ? { items: runningUnits.items || [], skipped: (runningUnits.skipped || []).map((why) => ({ why })),
                               notes: [] } : null;
    }
    if (!block || !block.rows.length) return null;
    return readItems(block.rows, map, {
      modelUnit: unit, ageUnit: modelCal ? fromUnit : "", defaultRate, periodLabel, fields, firstRow: block.firstRow,
    });
  }, [mode, runningUnits, block, map, unit, modelCal, fromUnit, defaultRate, periodLabel, fields]);

  const reset = () => { setText(""); setMapping(null); setAgeUnit(null); setError(null); setFileNote(null); setWorkbook(null); };
  const close = () => { reset(); onMode(null); };

  const readSheet = async (file, sheet) => {
    setBusy(true);
    setError(null);
    try {
      const csv = await excelToCsvFile(file, sheet.name, sheet.guessed_header_row);
      setMapping(null);
      setText(await csv.text());
      setFileNote(`${file.name} › ${sheet.name}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const onFile = async (file) => {
    if (!file) return;
    reset();
    if (isSpreadsheetFile(file)) {
      setBusy(true);
      try {
        const info = await inspectExcel(file);
        const sheets = (info.sheets || []).filter((s) => s.rows > 0);
        const first = nextSheet(sheets);
        if (!first) throw new Error("That workbook has no rows to read.");
        setWorkbook({ file, sheets, sheet: first.name });
        await readSheet(file, first);
      } catch (err) {
        setError(err.message);
        setBusy(false);
      }
      return;
    }
    try {
      setText(await file.text());
      setFileNote(file.name);
    } catch {
      setError("Couldn't read that file. Save it as .csv or .xlsx and try again.");
    }
  };

  const apply = (replace) => {
    if (!result?.items?.length) return;
    onApply(mergeItems(existing, result.items, replace));
    close();
  };

  if (!mode) return null;
  const options = targets(opts);
  const room = MAX_ITEMS - existing.length;
  const n = result?.items?.length || 0;
  const u = unit ? ` (${unit})` : "";

  return (
    <section className="fleet-import" aria-label="Add items in bulk" data-testid="fleet-import">
      <div className="fleet-import-head">
        <SegmentedControl size="sm" label="Add items from" value={mode} onChange={(m) => { reset(); onMode(m); }}
                          options={[
                            { value: "paste", label: "Paste" },
                            { value: "file", label: "Upload file" },
                            ...(runningUnits?.running ? [{ value: "model", label: "Model's data" }] : []),
                          ]} />
        <button className="secondary sm" onClick={close}>Close</button>
      </div>

      {mode === "paste" && (
        <label className="login-field fleet-import-paste">
          <span>Paste rows from Excel or a CSV: a name and the current use{u} for each item, a header row optional</span>
          <textarea rows={6} value={text} spellCheck={false} autoFocus
                    placeholder={"Pump\tHours\nPU-01\t12500\nPU-02\t8300"}
                    onChange={(e) => { setText(e.target.value); setMapping(null); }} />
        </label>
      )}
      {mode === "file" && (
        <div className="fleet-import-file">
          <div className="dropzone fleet-import-drop" role="button" tabIndex={0}
               onClick={() => fileRef.current?.click()}
               onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), fileRef.current?.click())}
               onDragOver={(e) => e.preventDefault()}
               onDrop={(e) => { e.preventDefault(); onFile(e.dataTransfer.files?.[0]); }}>
            <span className="dz-big">
              {busy ? "Reading…" : fileNote ? <>Read {fileNote}. Drop another or <strong>browse</strong></>
                : <>Drop a CSV or Excel file here or <strong>click to browse</strong></>}
            </span>
            <span className="dz-hint">.csv or .xlsx, one row per item</span>
            <input ref={fileRef} type="file" hidden accept={`.csv,.tsv,.txt,text/csv,${SPREADSHEET_ACCEPT}`}
                   aria-label="Items file" onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ""; }} />
          </div>
          {workbook && workbook.sheets.length > 1 && (
            <label className="login-field" style={{ width: 220 }}>
              <span>Sheet</span>
              <Select value={workbook.sheet}
                      options={workbook.sheets.map((s) => ({ value: s.name, label: s.name, hint: `${s.rows} rows` }))}
                      onChange={(name) => {
                        setWorkbook((w) => ({ ...w, sheet: name }));
                        readSheet(workbook.file, workbook.sheets.find((s) => s.name === name));
                      }} />
            </label>
          )}
        </div>
      )}
      {mode === "model" && runningUnits && (
        <p className="muted-line" style={{ marginTop: 0 }}>
          {runningUnits.kind === "systems"
            ? "Each system in the model's data, at its age at the end of its record. An item named as a system uses that system's own history."
            : `The units the model's data records as still running (not failed), each at the age it had reached${runningUnits.name_column ? `, named from the “${runningUnits.name_column}” column` : ""}.`}
          {runningUnits.reason ? ` ${runningUnits.reason}` : ""}
        </p>
      )}
      {error && <div className="card error">{error}</div>}

      {block && block.rows.length > 0 && mode !== "model" && (
        <div className="fleet-import-map">
          <h3 className="fleet-assume-h">Columns</h3>
          <div className="alt-map">
            {block.headers.map((h, j) => (
              <div className="alt-map-row" key={`${h}-${j}`}>
                <span className="alt-map-k" title={h}>{h}</span>
                <Select value={map[j] || ""} ariaLabel={`Column ${h}`}
                        onChange={(v) => setMapping(map.map((m, k) => (k === j ? v : m === v && v ? "" : m)))}
                        options={[{ value: "", label: "Leave out" }, ...options.map((t) => ({ value: t.key, label: t.label }))]} />
              </div>
            ))}
          </div>
          {ageCol >= 0 && modelCal && (
            <label className="login-field" style={{ width: 220, marginTop: "0.6rem" }}>
              <span>Ages in the file are in</span>
              <Select value={fromUnit || modelCal} onChange={setAgeUnit}
                      options={CONVERTIBLE_UNITS.map((x) => ({ value: x, label: x, hint: x === modelCal ? "the model's unit" : undefined }))} />
            </label>
          )}
          {ageCol >= 0 && !modelCal && unit && (
            <p className="muted-line">Ages are read in the model's unit ({unit}).</p>
          )}
        </div>
      )}

      {result && (n > 0 || result.skipped.length > 0) && (
        <div className="fleet-import-preview" data-testid="fleet-import-preview">
          <p className="fleet-import-sum" role="status"><b>{summary(result, existing.length)}</b>
            {result.skipped.length > 0 && ":"}</p>
          {result.skipped.length > 0 && (
            <ul className="fleet-import-skipped">
              {result.skipped.slice(0, 5).map((s, k) => (
                <li key={k}>{s.row ? `Row ${s.row}: ` : ""}{s.why}</li>
              ))}
              {result.skipped.length > 5 && <li>and {result.skipped.length - 5} more</li>}
            </ul>
          )}
          {result.notes.map((t) => <p key={t} className="muted-line">{t}</p>)}
          {n > 0 && (
            <ScrollCue className="table-scroll">
              <table className="mini-table">
                <thead>
                  <tr>
                    <th>Item</th>
                    <th className="num">Current use{u}</th>
                    {fields.map((f) => <th key={f.name}>{f.label || f.name}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {result.items.slice(0, PREVIEW_ROWS).map((it, k) => (
                    <tr key={k}>
                      <td>{it.name}</td>
                      <td className="num">{formatNumber(it.current_use, { sig: 4 })}</td>
                      {fields.map((f) => <td key={f.name}>{it.covariates?.[f.name] ?? "—"}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollCue>
          )}
          {n > PREVIEW_ROWS && <p className="muted-line">and {n - PREVIEW_ROWS} more.</p>}
          <div className="fleet-import-acts">
            <button onClick={() => apply(existing.length === 0)} disabled={n === 0 || room <= 0}>
              Add {Math.min(n, Math.max(room, 0))} item{Math.min(n, room) === 1 ? "" : "s"}
            </button>
            {existing.length > 0 && (
              <button className="secondary" onClick={() => apply(true)} disabled={n === 0}>
                Replace the {existing.length} item{existing.length === 1 ? "" : "s"}
              </button>
            )}
            <span className="muted-line">Then Save &amp; forecast.</span>
          </div>
        </div>
      )}
    </section>
  );
}
