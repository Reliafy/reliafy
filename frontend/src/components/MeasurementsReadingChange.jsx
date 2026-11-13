import { useState } from "react";
import ColumnMapper from "./ColumnMapper.jsx";
import { ErrorNotice } from "./StorageCap.jsx";

const ROWS = ["i", "x", "m"];
const WORDS = {
  i: "which item each reading belongs to",
  x: "when the reading was taken",
  m: "the measured value",
};

// Change how a dataset's measurements part is read (i, x, m with x's and m's
// units): the shared selectors, kept with the dataset's reading as its
// ``measurements`` (useDatasetReading's keep). ``value``: the part's reading;
// ``columns`` / ``facts``: the part's columns. ``onKeep(next)`` → true once kept.
export default function MeasurementsReadingChange({ name, columns, facts = {}, value, onKeep, onCancel, saving, error, readOnly }) {
  const [draft, setDraft] = useState(() => ({
    i: value?.i || "", x: value?.x || "", m: value?.m || "", unit: value?.unit || "", m_unit: value?.m_unit || "",
  }));
  const picked = ROWS.map((r) => draft[r]).filter(Boolean);
  const waiting = !draft.i || !draft.x || !draft.m ? "Pick i, x and m: which item, when, and the measured value."
    : new Set(picked).size < picked.length ? "i, x and m must be three different columns." : null;
  return (
    <section className="reading-change" aria-label="Change how the measurements are read">
      <h3 className="reading-change-h">Change how the measurements of “{name}” are read</h3>
      <p className="muted-line" style={{ margin: 0 }}>
        {readOnly
          ? "This dataset isn't yours to change, so this reading is used for this fit only."
          : "Kept with the dataset: later models use it. Models already made keep the reading they were fitted with."}
      </p>
      <ColumnMapper
        columns={columns}
        mapping={draft}
        onChange={(next) => setDraft((d) => ({ ...d, i: next.i || "", x: next.x || "", m: next.m || "" }))}
        unit={draft.unit}
        onUnitChange={(u) => setDraft((d) => ({ ...d, unit: u }))}
        mUnit={draft.m_unit}
        onMUnitChange={(u) => setDraft((d) => ({ ...d, m_unit: u }))}
        facts={facts}
        rows={ROWS}
        range={false}
        words={WORDS}
        lifeRules={false}
      />
      <ErrorNotice error={error} />
      <div className="row reading-change-foot" style={{ margin: 0 }}>
        <button type="button" className="secondary" onClick={onCancel} disabled={saving}>Cancel</button>
        {waiting && <span className="hint ds-next-why" role="status" style={{ margin: 0 }}>{waiting}</span>}
        <button type="button" onClick={() => onKeep({ ...draft, source: "saved" })} disabled={!!waiting || saving}>
          {saving ? "Saving…" : readOnly ? "Use this reading" : "Save the reading"}
        </button>
      </div>
    </section>
  );
}
