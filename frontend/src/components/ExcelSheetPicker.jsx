import { useCallback, useEffect, useRef, useState } from "react";
import Modal from "./Modal.jsx";
import Select from "./Select.jsx";
import { excelToCsvFile, inspectExcel, isSpreadsheetFile } from "../api.js";

// Choose a sheet of an Excel workbook and the row holding its column headers.
// ``inspection`` is the /api/excel/inspect response; ``value`` = { sheet,
// headerRow } (headerRow is the sheet's row number, 0 = no header row).
// Click a preview row to make it the header. Shared by every spreadsheet
// import (life data, RCM worksheets, RBD templates).
export default function ExcelSheetPicker({ inspection, value, onChange, sheetLabel = "Sheet" }) {
  const sheets = inspection?.sheets || [];
  const current = sheets.find((s) => s.name === value?.sheet) || sheets[0];
  if (!current) return null;
  const header = value?.headerRow ?? current.guessed_header_row;
  const setSheet = (name) => {
    const s = sheets.find((x) => x.name === name);
    onChange({ sheet: name, headerRow: s?.guessed_header_row ?? 1 });
  };
  const setHeader = (row) => onChange({ sheet: current.name, headerRow: row });
  const width = Math.min(current.cols || 0, 12);

  const rowOptions = [
    ...current.row_numbers
      .map((n, i) => ({ n, cells: current.preview[i] || [] }))
      .filter(({ cells }) => cells.some((c) => c !== ""))
      .map(({ n, cells }) => ({
        value: String(n),
        label: `Row ${n} — ${cells.filter(Boolean).slice(0, 3).join(" · ").slice(0, 60)}`,
      })),
    { value: "0", label: "No header row (name columns col 1, col 2, …)" },
  ];

  return (
    <div className="xl-picker">
      <div className="xl-picker-bar">
        {sheets.length > 1 ? (
          <label className="xl-inline">
            <span>{sheetLabel}</span>
            <Select
              value={current.name}
              onChange={setSheet}
              options={sheets.map((s) => ({
                value: s.name,
                label: s.name,
                hint: s.rows ? `${s.rows.toLocaleString()} rows × ${s.cols} cols` : "empty",
              }))}
            />
          </label>
        ) : (
          <span className="xl-sheet-name">
            {sheetLabel}: <b>{current.name}</b>
          </span>
        )}
        <label className="xl-inline">
          <span>Header row</span>
          <Select value={String(header)} onChange={(v) => setHeader(Number(v))} options={rowOptions} />
        </label>
        <span className="xl-dim">
          {current.rows.toLocaleString()} non-blank row{current.rows === 1 ? "" : "s"} · {current.cols} column{current.cols === 1 ? "" : "s"}
        </span>
      </div>

      {current.rows === 0 ? (
        <p className="hint">This sheet is empty — pick another.</p>
      ) : (
        <div className="xl-preview">
          <table className="preview-table">
            <thead>
              <tr>
                <th className="xl-rn" />
                {Array.from({ length: width }, (_, i) => (
                  <th key={i}>{colLetter(i)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {current.preview.map((cells, i) => {
                const n = current.row_numbers[i];
                const cls = n === header ? "xl-head" : header && n < header ? "xl-above" : "";
                return (
                  <tr
                    key={n}
                    className={cls}
                    onClick={() => setHeader(n)}
                    title={n === header ? "Header row" : "Click to use this row as the header"}
                  >
                    <td className="xl-rn">{n}</td>
                    {cells.slice(0, width).map((c, j) => (
                      <td key={j}>{c}</td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="hint" style={{ margin: 0 }}>
        {header
          ? <>Row {header} holds the column names{header > 1 ? "; rows above it are skipped" : ""}. Click another row to change it.</>
          : <>No header row — every row is data.</>}
        {current.cols > width && ` Showing the first ${width} of ${current.cols} columns.`}
      </p>
      {current.notes?.map((n, i) => (
        <p key={i} className="xl-note">{n}</p>
      ))}
    </div>
  );
}

function colLetter(i) {
  let s = "";
  for (let n = i + 1; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
  return s;
}

// Loads a workbook's sheets for the picker. Returns { inspection, error, loading }.
export function useExcelInspection(file) {
  const [state, setState] = useState({ inspection: null, error: null, loading: !!file });
  useEffect(() => {
    if (!file) return undefined;
    let live = true;
    setState({ inspection: null, error: null, loading: true });
    inspectExcel(file)
      .then((inspection) => live && setState({ inspection, error: null, loading: false }))
      .catch((e) => live && setState({ inspection: null, error: e.message, loading: false }));
    return () => { live = false; };
  }, [file]);
  return state;
}

// A modal around the picker: resolves the chosen { sheet, headerRow }.
function SheetModal({ file, confirmLabel, onDone, convert }) {
  const { inspection, error, loading } = useExcelInspection(file);
  const [value, setValue] = useState(null);
  const [busy, setBusy] = useState(false);
  const [convError, setConvError] = useState(null);
  useEffect(() => {
    const first = inspection?.sheets?.find((s) => s.rows > 0) || inspection?.sheets?.[0];
    if (first) setValue({ sheet: first.name, headerRow: first.guessed_header_row });
  }, [inspection]);

  const confirm = async () => {
    if (!convert) return onDone(value);
    setBusy(true);
    setConvError(null);
    try {
      onDone(await excelToCsvFile(file, value.sheet, value.headerRow));
    } catch (e) {
      setConvError(e.message);
      setBusy(false);
    }
  };
  const current = inspection?.sheets?.find((s) => s.name === value?.sheet);
  return (
    <Modal
      title={`Import from ${file.name}`}
      className="modal-xl"
      locked={busy}
      onClose={() => onDone(null)}
      footer={
        <>
          <button className="secondary" onClick={() => onDone(null)} disabled={busy}>Cancel</button>
          <button onClick={confirm} disabled={busy || !value || !current?.rows}>
            {busy ? "Reading…" : confirmLabel}
          </button>
        </>
      }
    >
      {loading && <p className="hint">Reading the workbook…</p>}
      {error && <div className="error" style={{ marginTop: 0 }}>{error}</div>}
      {inspection && value && (
        <ExcelSheetPicker inspection={inspection} value={value} onChange={setValue} />
      )}
      {convError && <div className="error">{convError}</div>}
    </Modal>
  );
}

// For CSV upload paths: ``toCsv(file)`` passes a CSV straight through, and for
// an Excel workbook asks which sheet (and header row) to use, then converts it
// to a CSV File server-side — so everything downstream (column mapping,
// censoring, the fit) behaves exactly as for a CSV. Resolves null on cancel.
// ``chooseSheet(file)`` resolves just the { sheet, headerRow } choice.
// Render ``modal`` somewhere in the component.
export function useSpreadsheet() {
  const [pending, setPending] = useState(null); // { file, convert, resolve }
  const resolver = useRef(null);
  const ask = useCallback((file, convert) => new Promise((resolve) => {
    resolver.current = resolve;
    setPending({ file, convert });
  }), []);
  const toCsv = useCallback((file) => (file && isSpreadsheetFile(file) ? ask(file, true) : Promise.resolve(file)), [ask]);
  const chooseSheet = useCallback((file) => ask(file, false), [ask]);
  const modal = pending ? (
    <SheetModal
      file={pending.file}
      convert={pending.convert}
      confirmLabel={pending.convert ? "Use this sheet" : "Continue"}
      onDone={(result) => {
        setPending(null);
        resolver.current?.(result);
        resolver.current = null;
      }}
    />
  ) : null;
  return { toCsv, chooseSheet, modal };
}
