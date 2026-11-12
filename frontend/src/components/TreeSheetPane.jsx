import { useRef, useState } from "react";
import { downloadTreeSheet, importTreeSheet } from "../api.js";
import { saveErrorText } from "../confirm.js";
import {
  ACCEPT, doneText, exportChoices, importBlocker, notInFileText, previewLines, roomText, sortedByRow, whereText,
} from "../treeSheet.js";
import TablePane from "./TablePane.jsx";
import "../views/Maintenance.css";
import "./TreeSheetPane.css";

// The asset tree in a spreadsheet, in the Explorer's table area beside the tree (no modal):
// Import from Excel (pick a file, see what it would change and any problems by row, then Import:
// all of it or nothing) and Export (the whole tree, or the branch it was opened from, as Excel or
// CSV). One file format both ways, so an export edited in Excel imports back
// (backend/maintenance/hierarchy.py; its Read me sheet explains the columns).
//
//   start      "import" or "export": which part comes first
//   branch     {id, name}: the branch "Export this branch…" opened it on (else null)
//   onChanged(text)  an import went in (the tree is read again)
//   readOnly   the reason the workspace can't be changed (view only), or null
//   phone, headingRef, onClose: TablePane's

export default function TreeSheetPane({ start = "import", branch = null, phone = false, headingRef = null, onClose,
  onChanged, readOnly = null }) {
  const [file, setFile] = useState(null);
  const [report, setReport] = useState(null);
  const [checking, setChecking] = useState(false);
  const [importing, setImporting] = useState(false);
  const [failed, setFailed] = useState(null);
  const [done, setDone] = useState(null);
  const [scope, setScope] = useState(branch ? "branch" : "all");
  const [downloading, setDownloading] = useState(null);
  const [exportFailed, setExportFailed] = useState(null);
  const input = useRef(null);

  const pick = async (f) => {
    setFile(f || null);
    setReport(null);
    setDone(null);
    setFailed(null);
    if (!f) return;
    setChecking(true);
    try {
      setReport(await importTreeSheet(f, true));
    } catch (e) {
      setFailed(saveErrorText(e, { what: "check the file", offline: navigator.onLine === false }));
    } finally {
      setChecking(false);
    }
  };
  const run = async () => {
    setImporting(true);
    setFailed(null);
    try {
      const out = await importTreeSheet(file, false);
      setDone(out);
      setReport(null);
      setFile(null);
      if (input.current) input.current.value = "";
      onChanged?.(doneText(out));
    } catch (e) {
      setFailed(saveErrorText(e, { what: "import it", offline: navigator.onLine === false }));
    } finally {
      setImporting(false);
    }
  };
  const download = async (format) => {
    setDownloading(format);
    setExportFailed(null);
    try {
      await downloadTreeSheet({ positionId: scope === "branch" ? branch?.id : null, format });
    } catch (e) {
      setExportFailed(e.message || "The download didn't start.");
    } finally {
      setDownloading(null);
    }
  };

  const blocked = importBlocker(report, { viewOnly: readOnly });
  const problems = sortedByRow(report?.problems);
  const notes = sortedByRow((report || done)?.notes);
  const more = (report?.problem_count || 0) - problems.length;

  const importPart = (
    <section className="ts-part" aria-labelledby="ts-import">
      <h3 id="ts-import" className="ts-title">Import from Excel</h3>
      <p className="rim-tquiet ts-intro">
        One row per position: its Path (Plant 1 &gt; Unit 2 &gt; Feed pump A), and if you like its tag, class, location
        and the item fitted there. Start from an export to get the columns. Rows match by ID, else Path: matches are
        updated, new rows added, and nothing is deleted. You see what will change before anything is written.
      </p>
      {readOnly && <p className="rim-tquiet" role="note">{readOnly}</p>}
      <label className="ts-file">
        <span className="ts-label">Excel or CSV file</span>
        <input ref={input} type="file" accept={ACCEPT} disabled={!!readOnly || checking || importing}
               onChange={(e) => pick(e.target.files?.[0])} />
      </label>
      {checking && <p className="rim-tquiet" role="status">Checking every row…</p>}
      {failed && <p className="field-error" role="alert">{failed}</p>}
      {done && (
        <div className="ts-done" role="status">
          <p><strong>Imported.</strong> {done.summary}</p>
          <ul className="ts-lines">{previewLines(done).map((l) => <li key={l.key}>{l.text}</li>)}</ul>
        </div>
      )}
      {report && (
        <div className="ts-preview">
          <p className="ts-summary"><strong>{report.summary}</strong></p>
          <ul className="ts-lines">{previewLines(report).map((l) => <li key={l.key}>{l.text}</li>)}</ul>
          {report.moves?.length > 0 && (
            <details className="ts-moves">
              <summary>{report.moves.length === 1 ? "The move" : `The ${report.moves.length} moves`}</summary>
              <ul>{report.moves.map((mv) => <li key={mv.row}>Row {mv.row}: {mv.from} → {mv.to}</li>)}</ul>
            </details>
          )}
          {notInFileText(report) && <p className="rim-tquiet">{notInFileText(report)}</p>}
          {roomText(report) && <p className="rim-tquiet">{roomText(report)}</p>}
          {problems.length > 0 && (
            <>
              <h4 className="ts-sub">{report.problem_count === 1 ? "1 problem to fix in the file" : `${report.problem_count} problems to fix in the file`}</h4>
              <div className="maint-scroll">
                <table className="ts-table">
                  <thead><tr><th scope="col">Where</th><th scope="col">What to fix</th></tr></thead>
                  <tbody>
                    {problems.map((p, i) => (
                      <tr key={i}><td className="ts-where">{whereText(p)}</td><td>{p.text}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {more > 0 && <p className="rim-tquiet">And {more} more: fix these and check it again.</p>}
            </>
          )}
        </div>
      )}
      {notes.length > 0 && (
        <details className="ts-notes" open={notes.length <= 5}>
          <summary>{notes.length === 1 ? "1 thing left as it is" : `${notes.length} things left as they are`}</summary>
          <ul>{notes.map((p, i) => <li key={i}>{whereText(p)}: {p.text}</li>)}</ul>
        </details>
      )}
      {report && (
        <div className="ts-actions">
          <button type="button" onClick={run} disabled={!!blocked || importing}>
            {importing ? "Importing…" : "Import"}
          </button>
          <button type="button" className="secondary" onClick={() => pick(file)} disabled={!file || checking || importing}>
            Check again
          </button>
          {blocked && <span className="rim-tquiet">{blocked}</span>}
        </div>
      )}
    </section>
  );

  const exportPart = (
    <section className="ts-part" aria-labelledby="ts-export">
      <h3 id="ts-export" className="ts-title">Export</h3>
      <p className="rim-tquiet ts-intro">
        The positions with their tags, classes, locations and the items fitted now, plus a Read me sheet on each column.
        Edit it in Excel and import it again: nothing is duplicated. CSV holds the Hierarchy sheet alone.
      </p>
      {branch && (
        <fieldset className="ts-scope">
          <legend className="ts-label">What to export</legend>
          {exportChoices(branch).map((c) => (
            <label key={c.id} className="ts-choice">
              <input type="radio" name="ts-scope" value={c.id} checked={scope === c.id} onChange={() => setScope(c.id)} />
              {c.label}
            </label>
          ))}
        </fieldset>
      )}
      <div className="ts-actions">
        <button type="button" onClick={() => download("xlsx")} disabled={!!downloading}>
          {downloading === "xlsx" ? "Preparing…" : "Download Excel"}
        </button>
        <button type="button" className="secondary" onClick={() => download("csv")} disabled={!!downloading}>
          {downloading === "csv" ? "Preparing…" : "Download CSV"}
        </button>
      </div>
      {exportFailed && <p className="field-error" role="alert">{exportFailed}</p>}
    </section>
  );

  return (
    <TablePane title="Excel import and export" subject={branch?.name || "Asset tree"} phone={phone}
               busy={importing} headingRef={headingRef} onClose={onClose} className="tree-sheet-pane">
      <div className="tree-sheet">
        {start === "export" ? <>{exportPart}{importPart}</> : <>{importPart}{exportPart}</>}
      </div>
    </TablePane>
  );
}
