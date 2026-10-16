import { isSpreadsheetFile } from "../api.js";
import { firstRowIsData, withGenericHeader } from "../datasetGuess.js";

// A CSV with no header row (#434): its first row is all numbers, so it's
// data, and reading it as the column names would lose it. The upload wizards
// read a file as it is (columns, fit and save alike), so the file gains a
// header (col 1, col 2, …) before anything else sees it.
//
// ``detectHeader(picked, csv)``: ``picked`` the file the user chose, ``csv``
// it as a CSV (a workbook's sheet had its header row chosen in the sheet
// picker, so it's left alone). Resolves { file, note }: the file to use, and
// the note to show (null when the first row is names). ``keepHeader`` (the
// note's Undo) keeps the first row as the names.
export async function detectHeader(picked, csv, { keepHeader = false } = {}) {
  if (!csv || isSpreadsheetFile(picked)) return { file: csv, note: null };
  const text = await csv.text().catch(() => null);
  if (text == null || !firstRowIsData(text, ",")) return { file: csv, note: null };
  return {
    file: keepHeader ? csv : new File([withGenericHeader(text)], csv.name, { type: "text/csv" }),
    note: { original: csv, kept: keepHeader },
  };
}

// The note, with Undo (read the first row as the names after all) or, once
// undone, the way back. ``onPick(file, { keepHeader })`` loads the file again.
export default function HeaderNote({ note, onPick, disabled = false }) {
  if (!note) return null;
  return (
    <p className="ds-header-note" role="status">
      {note.kept ? (
        <>
          <span>The first row is used as the column names.</span>
          <button type="button" className="link" disabled={disabled}
                  onClick={() => onPick(note.original, { keepHeader: false })}>
            Treat it as data
          </button>
        </>
      ) : (
        <>
          <span>Your first row looks like data, so we've treated it as data.</span>
          <button type="button" className="link" disabled={disabled}
                  onClick={() => onPick(note.original, { keepHeader: true })}>
            Undo
          </button>
        </>
      )}
    </p>
  );
}
