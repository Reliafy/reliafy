import Select from "./Select.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { ResultDetails } from "./ui/ResultSummary.jsx";
import { guessUnit } from "../datasetGuess.js";
import { guessStatus, setStatusMeaning, statusMeaning, statusValues } from "../lifeData.js";

// Column mapping in plain words (#291). Encodes SurPyval's input rules:
//   - the time column (x) is mutually exclusive with the interval pair xl/xr,
//     and xl and xr are used together
//   - the status (c), count (n) and truncation (tl/tr) columns are optional
//   - each status value gets a meaning, failed or still running: 0/1 codes are
//     sent as they are or flipped (``c_invert``), words as a map (``c_map``)
// Interval and truncation fields sit under Advanced. ``facts`` (see
// lifeData.columnFacts) gives each column's few values, for the status map.
const COMMON_UNITS = [
  "Hours", "Days", "Weeks", "Months", "Years",
  "Cycles", "Kilometres", "Miles", "Operations", "Rounds",
];

const ADVANCED = [
  { field: "xl", label: "Earliest possible failure time", hint: "Inspection data: the unit failed between this time and the latest. Used instead of a single time." },
  { field: "xr", label: "Latest possible failure time" },
  { field: "tl", label: "Observed from (left truncation)", hint: "Units already in service when records began." },
  { field: "tr", label: "Observed until (right truncation)" },
];

const MEANINGS = [
  { value: 0, label: "Failed" },
  { value: 1, label: "Still running" },
];
const FIXED = { "-1": "Found failed (left-censored)", 2: "Interval" };

// ``failureMode`` offers the failure-mode column (#177: the fit wizard only).
export default function ColumnMapper({ columns, mapping, onChange, unit, onUnitChange, facts = {},
                                      failureMode = false }) {
  const usingInterval = !!mapping.xl || !!mapping.xr;
  const options = (none) => [{ value: "", label: none }, ...columns];

  const setField = (field, value) => {
    const next = { ...mapping, [field]: value };
    // Enforce mutual exclusivity by clearing the conflicting side.
    if (field === "x" && value) {
      next.xl = "";
      next.xr = "";
    } else if ((field === "xl" || field === "xr") && value) {
      next.x = "";
    }
    // A new status column starts from guessed meanings for its values.
    if (field === "c") Object.assign(next, guessStatus(value, facts));
    // A unit guessed from the old time column follows the new one.
    if (field === "x" && onUnitChange && (!unit || unit === guessUnit(mapping.x))) {
      onUnitChange(guessUnit(value));
    }
    onChange(next);
  };

  const values = mapping.c ? statusValues(facts[mapping.c]?.values) : [];

  const field = (key, label, none, hint) => (
    <label className="ds-field" key={key}>
      <span className="ds-label">{label}</span>
      <Select value={mapping[key] || ""} onChange={(v) => setField(key, v)} options={options(none)} />
      {hint && <span className="ds-hint">{hint}</span>}
    </label>
  );

  return (
    <div className="ds-mapper">
      <div className="ds-row">
        {field("x", "Time to failure or removal", usingInterval ? "— using earliest / latest times —" : "— pick a column —")}
        {onUnitChange && (
          <label className="ds-field ds-unit">
            <span className="ds-label">Unit</span>
            <input
              className="units-input"
              type="text"
              list="x-units"
              value={unit || ""}
              placeholder="e.g. Hours"
              onChange={(e) => onUnitChange(e.target.value)}
            />
            <datalist id="x-units">
              {COMMON_UNITS.map((u) => (
                <option value={u} key={u} />
              ))}
            </datalist>
          </label>
        )}
      </div>

      <div className="ds-row">
        {/* The status column, with what each of its values means beneath it. */}
        <div className="ds-field">
          {field("c", "Failed or still running?", "— none: every row failed —")}
          {values.length > 0 && (
            <div className="ds-status" role="group" aria-label={`What each value in ${mapping.c} means`}>
              {values.map((v) => {
                const m = statusMeaning(v.label, mapping);
                return (
                  <div className="ds-status-row" key={v.label}>
                    <span className="ds-status-value">
                      {v.label}
                      <span className="ds-status-rows">{v.rows.toLocaleString()} {v.rows === 1 ? "row" : "rows"}</span>
                    </span>
                    {FIXED[m] ? (
                      <span className="ds-status-fixed">{FIXED[m]}</span>
                    ) : (
                      <SegmentedControl
                        size="sm"
                        label={`${v.label} means`}
                        options={MEANINGS}
                        value={m}
                        onChange={(meaning) => onChange(setStatusMeaning(mapping, facts[mapping.c]?.values, v.label, meaning))}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
        {field("n", "Count (optional)", "— none: one unit per row —")}
        {/* #177: a failure-mode column fits the modes as competing risks. */}
        {failureMode && field("e", "Failure mode (optional)", "— none: all modes together —",
                              mapping.e ? "A blank mode is a unit still running." : null)}
      </div>

      <ResultDetails summary="Advanced: interval and truncated data" open={usingInterval || !!mapping.tl || !!mapping.tr}>
        <div className="ds-row ds-row-4">
          {ADVANCED.map((a) => field(a.field, a.label, "— none —", a.hint))}
        </div>
      </ResultDetails>
    </div>
  );
}
