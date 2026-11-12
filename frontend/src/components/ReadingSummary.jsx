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
  const guessed = source !== "saved";
  const used = (key) => !use || use.includes(key) || (key === "range" && use.includes("x"));
  return (
    <div className={"reading-summary" + (guessed ? " guessed" : "")} data-wt="reading-summary">
      <div className="reading-summary-line">
        <span className="reading-summary-lead">{name ? <>How “{name}” is read:</> : "How the columns are read:"}</span>
        <span className="reading-summary-parts">
          {parts.map((p, i) => (
            <span key={p.key} className={"reading-part" + (used(p.key) ? "" : " unused")}>
              {i > 0 && <span className="reading-sep" aria-hidden="true"> · </span>}
              <code>{p.label}</code>{p.list ? ": " : " = "}{p.value}
            </span>
          ))}
        </span>
        {guessed && <span className="reading-badge" role="status">guessed — check it</span>}
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
export function ReadingChange({ name, rd, onDone }) {
  if (!rd.editing) return null;
  const waiting = readingWaiting(rd.draft, rd.facts, rd.nRows);
  const save = async () => {
    if (await rd.keep(rd.draft)) onDone?.();
  };
  return (
    <section className="reading-change" aria-label="Change how the columns are read">
      <h3 className="reading-change-h">Change how “{name}” is read</h3>
      <p className="muted-line" style={{ margin: 0 }}>
        {rd.readOnly
          ? "This dataset isn't yours to change, so this reading is used for this fit only."
          : "Kept with the dataset: later models use it. Models already made keep the reading they were fitted with."}
      </p>
      <ReadingEditor columns={rd.cols.columns} facts={rd.facts} nRows={rd.nRows} reading={rd.draft}
                     onChange={rd.setDraft} disabled={rd.saving} />
      <ErrorNotice error={rd.error} />
      <div className="row reading-change-foot" style={{ margin: 0 }}>
        <button type="button" className="secondary" onClick={rd.cancelChange} disabled={rd.saving}>Cancel</button>
        {waiting && <span className="hint ds-next-why" role="status" style={{ margin: 0 }}>{waiting}</span>}
        <button type="button" onClick={save} disabled={!!waiting || rd.saving}>
          {rd.saving ? "Saving…" : rd.readOnly ? "Use this reading" : "Save the reading"}
        </button>
      </div>
    </section>
  );
}
