import { readingParts } from "../datasetReading.js";
import ReadingEditor, { readingWaiting } from "./ReadingEditor.jsx";
import { ErrorNotice } from "./StorageCap.jsx";

// A fit flow's one line for a saved dataset's reading, in place of the column
// questions: "x = Age (hours) · c = Status · i = Tag · failure mode = Mode ·
// Z: Load, Site", with Change (edit the dataset's reading). A reading the app
// guessed (a dataset saved before readings) says "guessed — check it" with
// "Looks right", which keeps it (the user's own action), until it's confirmed.
//
// ``use``: what this model takes from it, [role] (e.g. ["x", "c", "z"]): the
// other roles are shown quieter. ``note``: a line under it (what this model
// does with the reading, e.g. one life per item). ``readOnly``: a sample or a
// view-only share — Change then edits a copy used for this fit only.
export default function ReadingSummary({
  name, reading, source = "saved", use = null, note = null, onChange, onConfirm, confirming = false, readOnly = false,
}) {
  const parts = readingParts(reading);
  // "once": changed for this fit only (the dataset keeps its own reading).
  const once = source === "once";
  const guessed = source !== "saved" && !once;
  const used = (key) => !use || use.includes(key) || (key === "range" && use.includes("x"));
  return (
    <div className={"reading-summary" + (guessed ? " guessed" : "")} data-wt="reading-summary">
      <div className="reading-summary-line">
        <span className="reading-summary-lead">{name ? <>How “{name}” is read:</> : "How the columns are read:"}</span>
        <span className="reading-summary-parts">
          {parts.map((p, i) => (
            <span key={p.key} className={"reading-part" + (used(p.key) ? "" : " unused")}>
              {i > 0 && <span className="reading-sep" aria-hidden="true"> · </span>}
              {/* A role's letter (x, c, i, Z) in mono; a word ("failure mode", "range") as plain text. */}
              {/^[A-Za-z]{1,2}$/.test(p.label) ? <code>{p.label}</code> : <span className="reading-word">{p.label}</span>}
              {p.list ? ": " : " = "}{p.value}
            </span>
          ))}
        </span>
        {guessed && (
          <span className="reading-badge" role="status"
                title="Read from the column names and values, not set by anyone yet: check each role, then press Looks right (or Change)">
            guessed — check it
          </span>
        )}
        {once && <span className="reading-badge" role="status">this fit only</span>}
        <span className="reading-summary-actions">
          {guessed && onConfirm && !readOnly && (
            <button type="button" className="secondary sm" onClick={onConfirm} disabled={confirming}>
              {confirming ? "Saving…" : "Looks right"}
            </button>
          )}
          {onChange && <button type="button" className="link" onClick={onChange}>Change</button>}
        </span>
      </div>
      {note && <p className="reading-summary-note">{note}</p>}
    </div>
  );
}

// Change: the dataset's reading edited with the upload's selectors, kept for
// the dataset (later fits use it; models already made keep the reading they
// were fitted with). ``rd``: useDatasetReading. A sample or view-only share
// can't keep one: the change is used for this fit only, and says so.
// ``fit``: false on the dataset's own page (no fit to use it for only).
export function ReadingChange({ name, rd, onDone, fit = true }) {
  if (!rd.editing) return null;
  const waiting = readingWaiting(rd.draft, rd.facts, rd.nRows);
  const save = async () => {
    if (await rd.keep(rd.draft)) onDone?.();
  };
  return (
    <section className="reading-change" aria-label="Change how the columns are read">
      <h3 className="reading-change-h">Change how “{name}” is read</h3>
      <p className="muted-line m-0">
        {rd.readOnly
          ? "This dataset isn't yours to change, so this reading is used for this fit only."
          : `Save keeps it with the dataset: later models use it (models already made keep the reading they were fitted with). The rows themselves never change.${fit ? " Use for this fit only leaves the dataset as it is." : ""}`}
      </p>
      <ReadingEditor columns={rd.cols.columns} facts={rd.facts} nRows={rd.nRows} reading={rd.draft}
                     onChange={rd.setDraft} disabled={rd.saving} />
      <ErrorNotice error={rd.error} />
      <div className="row reading-change-foot m-0">
        <button type="button" className="secondary" onClick={rd.cancelChange} disabled={rd.saving}>Cancel</button>
        {waiting && <span className="hint ds-next-why m-0" role="status">{waiting}</span>}
        {!rd.readOnly && fit && (
          <button type="button" className="secondary" onClick={() => { rd.useOnce(rd.draft); onDone?.(); }}
                  disabled={!!waiting || rd.saving}
                  title="Fit with this reading without changing the dataset's (one clock of two, or no failure mode, say)">
            Use for this fit only
          </button>
        )}
        <button type="button" onClick={save} disabled={!!waiting || rd.saving}>
          {rd.saving ? "Saving…" : rd.readOnly ? "Use this reading" : "Save the reading"}
        </button>
      </div>
    </section>
  );
}
