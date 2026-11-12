// Strategy › Compare two models, a side from raw data: the CSV's time and
// status columns, read the way the fit's Data step reads them. Pure, so
// node --test covers it.
import { guessStatusMeaning } from "./datasetGuess.js";

// Minimal CSV parse: pull a numeric column (and an optional status column).
// A status cell is read as the fit's Data step reads it (datasetGuess's
// guessStatusMeaning): 0/1 codes by the column's name, and words such as
// Failed / Running / F / S. A value it can't place stops the comparison and
// says which, never read as a failure.
export function parseColumn(text, col, censorCol) {
  const lines = text.replace(/\r/g, "").split("\n").filter((l) => l.trim());
  const headers = lines[0].split(",").map((s) => s.trim());
  const xi = headers.indexOf(col);
  const ci = censorCol ? headers.indexOf(censorCol) : -1;
  const x = [];
  const c = [];
  const unknown = new Set();
  for (let i = 1; i < lines.length; i++) {
    const cells = lines[i].split(",");
    const v = Number(cells[xi]);
    if (!Number.isFinite(v)) continue;
    x.push(v);
    if (ci >= 0) {
      const raw = String(cells[ci] ?? "").trim();
      const meaning = raw === "" ? 0 : guessStatusMeaning(raw, censorCol);
      if (meaning === null) unknown.add(raw);
      c.push(meaning ?? 0);
    }
  }
  if (unknown.size) {
    const shown = [...unknown].slice(0, 3).map((u) => `“${u}”`).join(", ");
    throw new Error(`The status column has values it can't read as failed or still running: ${shown}. Use 0 `
      + "(failed) and 1 (still running), or words such as Failed and Running.");
  }
  return ci >= 0 ? { x, c } : { x };
}

// "26 failed, 19 still running": how a status column reads, from its few values.
export function statusReading(values, col) {
  if (!values || !col) return null;
  let failed = 0, running = 0, other = 0;
  for (const [v, rows] of Object.entries(values)) {
    const m = guessStatusMeaning(v, col);
    if (m === 0) failed += rows; else if (m === 1) running += rows; else other += rows;
  }
  const parts = [`${failed} failed`, `${running} still running`];
  if (other) parts.push(`${other} not read`);
  return parts.join(", ");
}
