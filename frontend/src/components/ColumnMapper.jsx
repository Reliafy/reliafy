import Select from "./Select.jsx";
import StatusMeanings from "./StatusMeanings.jsx";
import { COMMON_UNITS } from "./Units.jsx";
import { guessUnit } from "../datasetGuess.js";
import {
  UNITLESS, countProblem, isUnitless, issueRow, lateEntryWords, setMappingField, statusCodesOnly, unitColumnWords,
} from "../lifeData.js";
import { TVC_STATUS } from "./TvcColumns.jsx";

// The Data step's selectors: one per SurPyval input, each with its label (x,
// c, n, xl, xr, tl) and a few plain words. The words never assume time: x is
// the value when a unit failed or was removed, in hours, cycles, km, volts…
//
//   x   [column]                                   unit [hours]
//       where x is blank, a range: xl [column] to xr [column]
//   c   [column]  0 = failed, 1 = running   [ ] my column uses 1 = failed
//   n   [column]
//   tl  [column]  (late entry)
//   failure mode [column]
//
// x and the range are read per row: x filled is an exact value, x blank its
// range (only a range, with no x, is inspection data). ``issues`` / ``notes``:
// [{ col, text }] (lifeData.dataStepIssues / dataStepNotes), each shown by
// the selector it concerns (lifeData.issueRow). ``asides``: { row: [node] },
// a question to answer there; ``warning``: a node shown loud on the x row.
// ``timeVarying`` ("intervals" | "timeline", #60): an item column and each
// row's times take x's place, with no count or late entry.
export default function ColumnMapper({
  columns, mapping, onChange, unit, onUnitChange, facts = {}, timeVarying = null, failureMode = false,
  issues = [], notes = [], asides = {}, warning = null,
}) {
  const options = (none) => [{ value: "", label: none }, ...columns];
  const range = !!(mapping.xl || mapping.xr);

  const setField = (field, value) => {
    const next = setMappingField(mapping, field, value, facts);
    // A unit guessed from the old value column follows the new one.
    const first = field === "x" || (field === "xl" && !mapping.x);
    if (first && onUnitChange && (!unit || unit === guessUnit(mapping[field]))) onUnitChange(guessUnit(value));
    onChange(next);
  };

  // A count holds whole numbers (#434): a column of text or decimals is
  // shown, but can't be picked, with the reason beside it.
  const countOptions = (none) => [
    { value: "", label: none },
    ...columns.map((col) => {
      const why = countProblem(facts[col]);
      return why ? { value: col, label: col, hint: why === "text" ? "text" : "has decimals", disabled: col !== mapping.n } : col;
    }),
  ];

  const pick = (key, none, label) => (
    <Select value={mapping[key] || ""} onChange={(v) => setField(key, v)} ariaLabel={label}
            className="xcn-pick" options={key === "n" ? countOptions(none) : options(none)} />
  );

  // What a row says beneath it: problems (stop the fit), notes, questions.
  const below = (row) => {
    const out = [];
    for (const i of issues.filter((x) => issueRow(x, mapping) === row)) {
      out.push(<p key={`i${i.text}`} className="xcn-issue" role="status">{i.text}</p>);
    }
    for (const n of notes.filter((x) => issueRow(x, mapping) === row)) {
      out.push(<p key={`n${n.text}`} className="xcn-issue xcn-note" role="status">{n.text}</p>);
    }
    for (const a of asides[row] || []) out.push(a);
    return out.length ? <div className="xcn-below">{out}</div> : null;
  };

  const unitBox = onUnitChange && (
    <span className="xcn-unit">
      <span className="xcn-words">unit</span>
      <input className="units-input" type="text" list="xcn-units" aria-label="Unit of the values"
             value={isUnitless(unit) ? "" : unit || ""} disabled={isUnitless(unit)}
             placeholder={isUnitless(unit) ? "No unit" : "hours, cycles, km…"}
             onChange={(e) => onUnitChange(e.target.value)} />
      <datalist id="xcn-units">{COMMON_UNITS.map((u) => <option value={u} key={u} />)}</datalist>
      <label className="ds-unitless">
        <input type="checkbox" checked={isUnitless(unit)} onChange={(e) => onUnitChange(e.target.checked ? UNITLESS : "")} />
        no unit
      </label>
    </span>
  );
  // A column of per-row units (hrs / days), guessed or picked from a question.
  const perRow = !timeVarying && mapping.u ? unitColumnWords(mapping, facts, unit) : null;

  const key = (k, words) => (
    <span className="xcn-key">
      <code>{k}</code>
      {words && <span className="xcn-words">{words}</span>}
    </span>
  );

  if (timeVarying) {
    // Covariates that change over time (#60): the item, each row's times, the status.
    return (
      <div className="xcn">
        <div className="xcn-row">
          {key("item", "the pump, motor or unit each row belongs to")}
          <div className="xcn-fields">{pick("i", "— pick a column —", "Item")}{unitBox}</div>
          {below("x")}
        </div>
        <div className="xcn-row">
          {timeVarying === "intervals" ? (
            <>
              {key("xl", "where the row starts")}
              <div className="xcn-fields">
                {pick("xl", "— pick a column —", "Start of the row")}
                <code>xr</code><span className="xcn-words">where it ends</span>
                {pick("xr", "— pick a column —", "End of the row")}
              </div>
            </>
          ) : (
            <>
              {key("x", "when the row's values take effect")}
              <div className="xcn-fields">{pick("x", "— pick a column —", "Value of the row")}</div>
            </>
          )}
        </div>
        <div className="xcn-row">
          {key("c", TVC_STATUS[timeVarying])}
          <div className="xcn-fields">{pick("c", "— none: every item failed —", "c")}{codes()}</div>
          {meanings()}
          {below("c")}
        </div>
      </div>
    );
  }

  // c: 0 = failed, 1 = still running, with the flip for a 1 = failed column.
  function codes() {
    if (!mapping.c || !statusCodesOnly(facts[mapping.c]?.values)) {
      return mapping.c ? null : <span className="xcn-words">0 = failed, 1 = running</span>;
    }
    return (
      <>
        <span className="xcn-words">0 = failed, 1 = running</span>
        <label className="xcn-tick">
          <input type="checkbox" checked={!!mapping.c_invert}
                 onChange={(e) => onChange({ ...mapping, c_invert: e.target.checked, c_map: null }, { meanings: true })} />
          my column uses 1 = failed
        </label>
      </>
    );
  }
  // A status column of words: how each was read, one short line.
  function meanings() {
    if (!mapping.c || statusCodesOnly(facts[mapping.c]?.values)) return null;
    return (
      <div className="xcn-sub">
        <span className="xcn-words">0 = failed, 1 = running. Read as:</span>
        <StatusMeanings compact column={mapping.c} values={facts[mapping.c]?.values} blanks={facts[mapping.c]?.blanks || 0}
                        mapping={mapping} onChange={(m) => onChange(m, { meanings: true })} />
      </div>
    );
  }

  return (
    <div className="xcn">
      <div className="xcn-row">
        {key("x", "the value when it failed or was removed")}
        <div className="xcn-fields">
          {pick("x", range ? "— none: every row is a range —" : "— pick a column —", "x")}
          {unitBox}
        </div>
        <div className="xcn-sub xcn-range">
          <span className="xcn-words">where x is blank, a range:</span>
          <span className="xcn-pair">
            <code>xl</code>{pick("xl", "— none —", "xl, the last value it was seen working")}
            <span className="xcn-words">to</span>
            <code>xr</code>{pick("xr", "— none —", "xr, the value it was found failed")}
          </span>
          <span className="xcn-words xcn-hint">xl: last seen working · xr: found failed (blank: still running)</span>
        </div>
        {perRow?.note && (
          <p className="xcn-note-line">
            {perRow.note}{" "}
            <button type="button" className="link" onClick={() => onChange({ ...mapping, u: "" })}>Don't convert</button>
          </p>
        )}
        {warning}
        {below("x")}
      </div>

      <div className="xcn-row">
        {key("c", "failed or still running")}
        <div className="xcn-fields">
          {pick("c", range ? "— none: read from the values —" : "— none: every row failed —", "c")}
          {codes()}
        </div>
        {meanings()}
        {below("c")}
      </div>

      <div className="xcn-row">
        {key("n", "how many units the row stands for")}
        <div className="xcn-fields">{pick("n", "— none —", "n")}</div>
        {below("n")}
      </div>

      <div className="xcn-row">
        {key("tl", "late entry: the value it was first seen at")}
        <div className="xcn-fields">
          {pick("tl", "— none —", "tl")}
          {mapping.tl && <span className="xcn-words">{lateEntryWords(mapping.tl, facts)}</span>}
        </div>
        {below("tl")}
      </div>

      {failureMode && (
        <div className="xcn-row">
          {key("failure mode", "optional, competing risks")}
          <div className="xcn-fields">
            {pick("e", "— none —", "Failure mode")}
            {mapping.e && facts[mapping.e]?.blanks > 0 && (
              <span className="xcn-words">a blank mode is a unit still running</span>
            )}
          </div>
          {below("e")}
        </div>
      )}
    </div>
  );
}
