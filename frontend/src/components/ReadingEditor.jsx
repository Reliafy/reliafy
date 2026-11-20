import ColumnMapper from "./ColumnMapper.jsx";
import { dataStepNotes } from "../lifeData.js";
import { ROLES, lifeMapping, readingIssues, setRole, toggleZ, withZ, zLine, notUsedReason } from "../datasetReading.js";
import { READING_MAIN, READING_MORE } from "../datasetReading.js";
import { defaultSecondUnit } from "../twoClocks.js";

// How a dataset's columns are read for modelling (datasetReading.js): the
// shared Data-step selectors (ColumnMapper) for x (with its range xl to xr),
// c (with what each value means) and n, then under "More columns" tl, tr, i, m,
// the failure mode, the state and the second clock (with its unit), then
// Z, the covariates: every column not given a role, less the ones guarded as
// "not used" (an id, a date, free text, one value), each one tap to include.
// Used by New dataset (Data) and by every fit flow's Change.
//
//   <ReadingEditor columns={cols} facts={facts} nRows={n} reading={r} onChange={setR} />
//
// ``onChange`` is a state setter: it is given an updater (cur => next), as
// the selectors can change the unit and the role in one go.
// x and c are required (c: a column, or "every row failed" ticked; a range or
// a table of readings needs none): readingIssues says why beside the selector.
export default function ReadingEditor({ columns, facts, nRows, reading, onChange, disabled = false }) {
  const issues = readingIssues(reading, facts, nRows);
  // A 0 in x, named (a failure there can't be fitted). Readings (m) start at 0 as a matter of course.
  const notes = reading.x && !reading.m ? dataStepNotes(lifeMapping(reading), facts) : [];
  const update = (fn) => onChange((cur) => fn(cur || reading));
  const range = !!(reading.xl || reading.xr);
  const cMissing = !reading.c && !range && !reading.m;

  const failedTick = (cMissing || reading.all_failed) && (
    <label className="xcn-tick" key="all-failed">
      <input type="checkbox" checked={!!reading.all_failed} disabled={disabled}
             onChange={(e) => { const on = e.target.checked; update((cur) => ({ ...cur, all_failed: on })); }} />
      No status column: every row failed
    </label>
  );

  const zCols = reading.z || [];
  const off = reading.not_used || [];
  return (
    <div className="reading-editor" aria-disabled={disabled || undefined}>
      <ColumnMapper
        columns={columns}
        mapping={reading}
        onChange={(next) => update((cur) => {
          // What the selector changed, put over the reading as it now is
          // (the unit may have moved with x in the same click).
          let r = { ...cur };
          for (const k of [...ROLES, "c_invert", "c_map"]) if (next[k] !== reading[k]) r[k] = next[k];
          // A role picked takes its column out of Z and any other role.
          const changed = ROLES.find((k) => next[k] !== reading[k] && next[k]);
          if (changed) r = setRole(r, changed, next[changed], facts, nRows);
          // The second clock's unit follows its column, unless the user typed their own.
          if (next.x2 !== cur.x2 && (!cur.x2_unit || cur.x2_unit === defaultSecondUnit(cur.x2))) {
            r.x2_unit = next.x2 ? defaultSecondUnit(next.x2) : "";
          }
          return withZ(r, cur, facts, nRows);
        })}
        unit={reading.unit}
        onUnitChange={(u) => update((cur) => ({ ...cur, unit: u }))}
        mUnit={reading.m_unit}
        onMUnitChange={(u) => update((cur) => ({ ...cur, m_unit: u }))}
        x2Unit={reading.x2_unit}
        onX2UnitChange={(u) => update((cur) => ({ ...cur, x2_unit: u }))}
        facts={facts}
        rows={READING_MAIN}
        more={READING_MORE}
        lifeRules
        words={{
          i: "optional: which item (unit, pump, tag) each row belongs to",
          m: "optional: a measured value, for readings",
          e: "optional: each failure's mode (the state entered)",
          s: "optional: the state the unit was in during this row (multi-state data)",
          x2: "optional: a second measure of use, e.g. starts, cycles, landings, shots, km",
        }}
        none={{
          x: "— pick a column —", c: range ? "— none: read from the values —" : "— pick a column —",
          i: "— none —", m: "— none —", e: "— none —", s: "— none —", x2: "— none —",
        }}
        issues={issues}
        notes={notes}
        asides={{ c: failedTick ? [failedTick] : [] }}
      />
      <section className="reading-z" aria-label="Covariates (Z)">
        <div className="reading-z-head">
          <code>Z</code>
          <span className="xcn-words">covariates: every column not used above. A plain life model ignores them; a regression offers them.</span>
        </div>
        {zCols.length + off.length === 0 ? (
          <p className="xcn-words" style={{ margin: 0 }}>Every column has a role.</p>
        ) : (
          <ul className="reading-z-list">
            {zCols.map((c) => (
              <li key={c} className="reading-z-item">
                <label className="reading-z-pick">
                  <input type="checkbox" checked disabled={disabled} onChange={() => update((cur) => toggleZ(cur, c))} />
                  <span>{c}</span>
                </label>
                <input className="units-input reading-z-unit" type="text" aria-label={`Unit of ${c}`} disabled={disabled}
                       placeholder="unit (optional)" value={reading.z_units?.[c] || ""}
                       onChange={(e) => { const u = e.target.value; update((cur) => ({ ...cur, z_units: { ...(cur.z_units || {}), [c]: u } })); }} />
              </li>
            ))}
            {off.map((c) => (
              <li key={c} className="reading-z-item off">
                <label className="reading-z-pick" title="Not used: tick to include it as a covariate">
                  <input type="checkbox" checked={false} disabled={disabled} onChange={() => update((cur) => toggleZ(cur, c))} />
                  <span>{c}</span>
                </label>
                <span className="xcn-words">not used: {notUsedReason(c, facts[c], nRows) || "left out"}</span>
              </li>
            ))}
          </ul>
        )}
        <p className="reading-z-line" role="status">{zLine(reading)}</p>
      </section>
    </div>
  );
}

// Why Save waits, in one line, or null when the reading is complete.
export function readingWaiting(reading, facts, nRows) {
  const issues = readingIssues(reading, facts, nRows);
  if (!issues.length) return null;
  const rows = [...new Set(issues.map((i) => (i.row === "xl" || i.row === "xr" ? "x" : i.row || "x")))];
  return `First settle the note${issues.length === 1 ? "" : "s"} beside ${rows.map((r) => (r === "e" ? "failure mode" : r === "x2" ? "second clock" : r)).join(", ")}.`;
}
