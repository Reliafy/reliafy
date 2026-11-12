import SegmentedControl from "./ui/SegmentedControl.jsx";
import { BLANK_LABEL, setStatusMeaning, statusMeaning, statusValues, statusValuesWithBlank } from "../lifeData.js";

// What each value of a status column means, failed or still running: one row
// per value with its count. The fit wizard's Data step and Compare groups
// both read a status column this way, so a sheet of "Failed" / "Removed, OK"
// works in both. ``mapping`` holds ``c_invert`` / ``c_map`` (lifeData.js);
// ``values`` is the column's {value: rows}, ``blanks`` its empty cells (a
// "(blank)" row, so a failure-mode column's blanks can mean still running);
// ``onChange`` gets the new mapping.
const MEANINGS = [
  { value: 0, label: "Failed" },
  { value: 1, label: "Still running" },
];
const FIXED = { "-1": "Found failed (left-censored)", 2: "Failed between the two times (interval)" };

export default function StatusMeanings({ column, values, blanks = 0, mapping, onChange }) {
  const all = statusValuesWithBlank(values, blanks);
  const rows = statusValues(all);
  if (!rows.length) return null;
  return (
    <div className="ds-status" role="group" aria-label={`What each value in ${column} means`}>
      {rows.map((v) => {
        const m = statusMeaning(v.label, mapping);
        return (
          <div className="ds-status-row" key={v.label}>
            <span className="ds-status-value">
              {v.label === "" ? <i>{BLANK_LABEL}</i> : v.label}
              <span className="ds-status-rows">{v.rows.toLocaleString()} {v.rows === 1 ? "row" : "rows"}</span>
            </span>
            {FIXED[m] ? (
              <span className="ds-status-fixed">{FIXED[m]}</span>
            ) : (
              <SegmentedControl
                size="sm"
                label={`${v.label || BLANK_LABEL} means`}
                options={MEANINGS}
                value={m}
                onChange={(meaning) => onChange(setStatusMeaning(mapping, all, v.label, meaning))}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
