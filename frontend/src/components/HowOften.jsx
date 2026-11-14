import { formatDate } from "../dates.js";
import { MONTH_NAMES, NTH_CHOICES, WEEKDAY_NAMES, isCalendar, patternOf, patternsFor, unitWord } from "../howOften.js";
import "./HowOften.css";

// "How often": one control for a task and for a work package (howOften.js holds the logic).
// It reads as a sentence with pickers, and wraps on a phone:
//
//   Every [1] [month] on [the first] [Saturday]
//   Every [1] [year] on [the first] [Tuesday] of [November]
//   Every [2,000] [operating hours]
//   or every [12] [months], whichever comes first          (withAlso: a task's second limit)
//
// Under it, always, the next dates it gives (`dates`), so a wrong rule is caught before
// saving; `datesNote` says why there are none (a unit of use goes by its meter).
//
//   value / onChange   the form (howOften.js formFromTask / formFromPackage)
//   units              the units offered (packages: the calendar only)
//   withAlso           offer the second limit, whichever comes first
//   patterns           false: no "on …" picker (a package counted from its last visit)
//   label              the group's name for screen readers
export default function HowOften({ value, onChange, units, withAlso = false, patterns = true, dates = null,
  datesNote = "", datesLead = "Next", datesAfter = "", problem = null, disabled = false, label = "How often" }) {
  const set = (key) => (e) => onChange({ ...value, [key]: e.target.value });
  const n = Number(value.every);
  const offered = patterns ? patternsFor(value.unit) : ["none"];
  const pattern = patterns ? patternOf(value) : "none";
  // One "on" picker: nothing, a weekday (weeks), or which one / a date (months and years).
  const onValue = pattern === "nth" ? `nth:${value.nth}` : pattern;
  const setOn = (e) => {
    const v = e.target.value;
    if (v.startsWith("nth:")) onChange({ ...value, pattern: "nth", nth: v.slice(4) });
    else onChange({ ...value, pattern: v });
  };
  return (
    <div className="how-often" role="group" aria-label={label}>
      <div className="ho-line">
        <span className="ho-word">Every</span>
        <input className="ho-num" type="number" inputMode="decimal" min="0" step="any" value={value.every}
               onChange={set("every")} disabled={disabled} aria-label="How many" />
        <select value={value.unit} onChange={set("unit")} disabled={disabled} aria-label="Unit">
          {units.map((u) => <option key={u} value={u}>{unitWord(u, n)}</option>)}
        </select>
        {offered.length > 1 && (
          <>
            <span className="ho-word">on</span>
            {value.unit === "weeks" ? (
              <select value={pattern === "weekday" ? value.weekday : "none"} disabled={disabled} aria-label="Day of the week"
                      onChange={(e) => onChange({ ...value, pattern: e.target.value === "none" ? "none" : "weekday",
                        weekday: e.target.value === "none" ? value.weekday : e.target.value })}>
                <option value="none">any day (counted on)</option>
                {WEEKDAY_NAMES.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            ) : (
              <select value={onValue} onChange={setOn} disabled={disabled} aria-label="Which day">
                <option value="none">{value.unit === "years" ? "the same date" : "the same day of the month"}</option>
                {NTH_CHOICES.map(([v, w]) => <option key={v} value={`nth:${v}`}>{w}</option>)}
                <option value="day">a date</option>
              </select>
            )}
            {pattern === "nth" && (
              <select value={value.weekday} onChange={set("weekday")} disabled={disabled} aria-label="Day of the week">
                {WEEKDAY_NAMES.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            )}
            {pattern === "day" && (
              <label className="ho-inline">day
                <input className="ho-num ho-day" type="number" inputMode="numeric" min="1" max="31" step="1" value={value.day}
                       onChange={set("day")} disabled={disabled} aria-label="Day of the month" />
              </label>
            )}
            {value.unit === "years" && pattern !== "none" && (
              <>
                <span className="ho-word">of</span>
                <select value={value.month} onChange={set("month")} disabled={disabled} aria-label="Month">
                  {MONTH_NAMES.map((mo, i) => <option key={mo} value={String(i + 1)}>{mo}</option>)}
                </select>
              </>
            )}
          </>
        )}
      </div>
      {withAlso && (
        <div className="ho-line ho-also">
          <span className="ho-word">or every</span>
          <input className="ho-num" type="number" inputMode="decimal" min="0" step="any" value={value.also} placeholder="—"
                 onChange={set("also")} disabled={disabled} aria-label="Second limit (optional)" />
          <select value={value.alsoUnit} onChange={set("alsoUnit")} disabled={disabled} aria-label="Second limit's unit">
            {units.map((u) => <option key={u} value={u}>{unitWord(u, Number(value.also) || 2)}</option>)}
          </select>
          <span className="ho-word">whichever comes first <span className="lib-date">(optional)</span></span>
        </div>
      )}
      {problem ? <p className="field-error" role="alert">{problem}</p> : (
        <p className="ho-dates lib-date" aria-live="polite">
          {dates && dates.length > 0
            ? <>{datesLead}: {dates.map((d) => formatDate(d, { weekday: true })).join(" · ")}{datesAfter ? `, ${datesAfter}` : ""}</>
            : datesNote || (isCalendar(value.unit) ? "No dates ahead." : "")}
        </p>
      )}
    </div>
  );
}
