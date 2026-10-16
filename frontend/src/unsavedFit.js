// A fit left without saving (#434): remembered in this browser so the next
// visit to Modelling can offer to save it. Kept per workspace; the data comes
// along when it is small (an upload or a paste) so one click can save the
// model and its data; a fit of a saved dataset needs only the dataset's id.
// Storage can be missing or throw (a private window): then nothing is kept.

const KEY = "reliafy:unsaved-fit";
// Larger uploads aren't copied into the browser's storage: the reminder then
// offers to fit them again instead.
export const MAX_KEPT_CSV = 256 * 1024;

const store = () => {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
};
const keyFor = (scope) => `${KEY}:${scope || "personal"}`;

// The record kept for a fit: what saveModel needs, the data or the dataset,
// and when. ``csv`` is dropped when it's too large to keep.
export function unsavedFitRecord({ name, distribution, mapping, opts, datasetId, csv, fileName, at }) {
  const keepCsv = !datasetId && typeof csv === "string" && csv.length <= MAX_KEPT_CSV;
  return {
    name, distribution, mapping, opts: opts || {},
    ...(datasetId ? { datasetId } : {}),
    ...(keepCsv ? { csv, fileName: fileName || "data.csv" } : {}),
    at: at || new Date().toISOString(),
  };
}

// Can the reminder save it in one click (it has the data, or the dataset)?
export const canSaveAgain = (rec) => !!(rec && rec.distribution && rec.name && (rec.datasetId || rec.csv));

export function rememberUnsavedFit(scope, record) {
  try {
    store()?.setItem(keyFor(scope), JSON.stringify(record));
  } catch {
    /* full or blocked: the reminder is a nicety */
  }
}

export function loadUnsavedFit(scope) {
  try {
    const raw = store()?.getItem(keyFor(scope));
    const rec = raw ? JSON.parse(raw) : null;
    return rec && typeof rec === "object" && rec.name ? rec : null;
  } catch {
    return null;
  }
}

export function forgetUnsavedFit(scope) {
  try {
    store()?.removeItem(keyFor(scope));
  } catch {
    /* nothing kept */
  }
}
