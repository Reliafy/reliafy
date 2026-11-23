import { useEffect, useState } from "react";
import { scheduleDates } from "../api.js";
import { formatDate } from "../dates.js";
import {
  MONTH_NAMES, MONTH_STEPS, NTH_CHOICES, WEEKDAY_NAMES, changeType, isCalendar, stepChoices, takesAlso, typesFor, unitWord,
} from "../howOften.js";
import "./HowOften.css";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import { Select } from "./ui/Controls.jsx";

// "How often": one control for a task and for a work package (howOften.js holds the logic). Pick the
// type (ChoiceChips), then a short sentence with pickers that wraps on a phone:
//
//   Running hours           Every [2,000] [operating hours]
//   Days, weeks or months   Every [3] [months]
//   Calendar rule           On [the first] [Saturday] of [every month]
//                           On [the 1st] of [every 6 months], from [March]
//   At shutdowns            At the first planned shutdown [12] [months] after it was last done
//   or every [12] [months], whichever comes first           (withAlso: the first two types)
//
// Under it, always, the rule in words and its next five dates, worked out on the server by
// RePyability as you type (`preview`: howOften.js previewFor), so a wrong rule is caught before
// saving. `dates` / `datesNote` show given dates or a note instead (a package by operating hours).
//
//   value / onChange   the form (howOften.js formFromTask / formFromPackage)
//   units              the units offered (packages: the calendar, or hours)
//   withAlso           offer the second limit, whichever comes first
//   patterns           false: no calendar rule (a package counted from its last visit)
//   shutdowns          offer "At shutdowns" (a position's task)
//   label              the group's name for screen readers
export default function HowOften({ value, onChange, units, withAlso = false, patterns = true, shutdowns = false, preview = null,
  dates = null, datesNote = "", datesLead = "Next", datesAfter = "", problem = null, disabled = false, label = "How often" }) {
  const set = (key) => (e) => onChange({ ...value, [key]: e.target.value });
  const types = typesFor(units, { patterns, shutdowns });
  const type = types.some((t) => t.value === value.type) ? value.type : types[0]?.value;
  const setType = (t) => {
    if (!t || t === type) return;
    onChange(changeType({ ...value, type }, t, units));
  };
  const shown = usePreview(problem ? null : preview);
  const n = Number(value.every);
  const useUnits = units.filter((u) => !isCalendar(u));
  const calUnits = units.filter(isCalendar).length ? units.filter(isCalendar) : ["days", "weeks", "months", "years"];
  const stepUnit = String(value.step || "").split(":")[0];
  const lead = preview ? shown.lead : datesLead;
  const list = preview ? shown.dates : dates;
  const note = preview ? shown.note : datesNote;
  const tail = preview ? shown.after : datesAfter;
  return (
    <div className="how-often" role="group" aria-label={label}>
      {types.length > 1 && (
        <ChoiceChips label="Type of schedule" options={types} value={type} onChange={setType} disabled={disabled} />
      )}
      {(type === "hours" || type === "interval") && (
        <div className="ho-line">
          <span className="ho-keep">
            <span className="ho-word">Every</span>
            <input className="ctl ho-num" type="number" inputMode="decimal" min="0" step="any" value={value.every}
                   onChange={set("every")} disabled={disabled} aria-label="How many" />
            <Select value={value.unit} onChange={set("unit")} disabled={disabled} aria-label="Unit">
              {(type === "hours" ? useUnits : calUnits).map((u) => <option key={u} value={u}>{unitWord(u, n)}</option>)}
            </Select>
          </span>
          {type === "interval" && <span className="ho-word">after it was last done</span>}
        </div>
      )}
      {type === "rule" && <RuleLine value={value} onChange={onChange} set={set} disabled={disabled} stepUnit={stepUnit} />}
      {type === "shutdowns" && (
        <div className="ho-line">
          <span className="ho-word">At the first planned shutdown</span>
          <span className="ho-keep">
            <input className="ctl ho-num" type="number" inputMode="numeric" min="1" step="1" value={value.every}
                   onChange={set("every")} disabled={disabled} aria-label="How long after it was last done" />
            <Select value={value.unit} onChange={set("unit")} disabled={disabled} aria-label="Unit">
              {calUnits.map((u) => <option key={u} value={u}>{unitWord(u, n)}</option>)}
            </Select>
          </span>
          <span className="ho-word">after it was last done</span>
        </div>
      )}
      {withAlso && takesAlso({ type }) && (
        <div className="ho-line ho-also">
          <span className="ho-keep">
            <span className="ho-word">or every</span>
            <input className="ctl ho-num" type="number" inputMode="decimal" min="0" step="any" value={value.also} placeholder="—"
                   onChange={set("also")} disabled={disabled} aria-label="Second limit (optional)" />
            <Select value={value.alsoUnit} onChange={set("alsoUnit")} disabled={disabled} aria-label="Second limit's unit">
              {units.map((u) => <option key={u} value={u}>{unitWord(u, Number(value.also) || 2)}</option>)}
            </Select>
          </span>
          <span className="ho-word">whichever comes first <span className="ho-opt">optional</span></span>
        </div>
      )}
      {problem ? <p className="field-error" role="alert">{problem}</p> : (
        <p className="ho-dates field-help" aria-live="polite">
          {preview && shown.words && (type === "rule" || type === "shutdowns") && <>{shown.words[0].toUpperCase() + shown.words.slice(1)}. </>}
          {list && list.length > 0
            ? <>{lead}: {list.map((d) => formatDate(d, { weekday: true })).join(" · ")}{tail ? `, ${tail}` : ""}</>
            : (preview && shown.busy ? "Working out the dates…" : note || (preview?.request || isCalendar(value.unit) ? "No dates ahead." : ""))}
        </p>
      )}
    </div>
  );
}

// "On [the first] [Saturday] of [every month]" / "On [Tuesday], [every 2 weeks]" / "… from [March]".
export function RuleLine({ value, onChange, set, disabled, stepUnit }) {
  const weeks = stepUnit === "weeks";
  const which = value.pattern === "nth" ? `nth:${value.nth}` : value.pattern;
  const setWhich = (e) => {
    const v = e.target.value;
    if (v.startsWith("nth:")) onChange({ ...value, pattern: "nth", nth: v.slice(4) });
    else onChange({ ...value, pattern: v });
  };
  const setStep = (e) => {
    const step = e.target.value;
    const toWeeks = step.startsWith("weeks:");
    // A weekly rule names a weekday; a monthly or yearly one which day in the month.
    let pattern = value.pattern;
    if (toWeeks) pattern = "weekday";
    else if (pattern === "weekday") pattern = "nth";
    onChange({ ...value, step, pattern });
  };
  return (
    <div className="ho-line">
      <span className="ho-word">On</span>
      {!weeks && (
        <Select value={which} onChange={setWhich} disabled={disabled} aria-label="Which day">
          {NTH_CHOICES.map(([v, w]) => <option key={v} value={`nth:${v}`}>{w}</option>)}
          <option value="day">a date</option>
          <option value="lastday">the last day</option>
        </Select>
      )}
      {(weeks || value.pattern === "nth") && (
        <Select value={value.weekday} onChange={set("weekday")} disabled={disabled} aria-label="Day of the week">
          {WEEKDAY_NAMES.map((d) => <option key={d} value={d}>{d}</option>)}
        </Select>
      )}
      {!weeks && value.pattern === "day" && (
        <label className="ho-inline">day
          <input className="ctl ho-num ho-day" type="number" inputMode="numeric" min="1" max="31" step="1" value={value.day}
                 onChange={set("day")} disabled={disabled} aria-label="Day of the month" />
        </label>
      )}
      {stepUnit === "years" && (
        <>
          <span className="ho-word">of</span>
          <Select value={value.month} onChange={set("month")} disabled={disabled} aria-label="Month">
            {MONTH_NAMES.map((mo, i) => <option key={mo} value={String(i + 1)}>{mo}</option>)}
          </Select>
        </>
      )}
      {stepUnit === "months" && <span className="ho-word">of</span>}
      <Select value={value.step} onChange={setStep} disabled={disabled} aria-label="How often it repeats">
        {stepChoices(value.step).map(([v, w]) => <option key={v} value={v}>{w}</option>)}
      </Select>
      {MONTH_STEPS.includes(value.step) && (
        <>
          <span className="ho-word">from</span>
          <Select value={value.startMonth} onChange={set("startMonth")} disabled={disabled} aria-label="The month it starts in">
            {MONTH_NAMES.map((mo, i) => <option key={mo} value={String(i + 1)}>{mo}</option>)}
          </Select>
        </>
      )}
    </div>
  );
}

// The next dates for `preview` (howOften.js previewFor), from the server, a moment after the last change.
export function usePreview(preview) {
  const key = preview?.request ? JSON.stringify(preview.request) : null;
  const [got, setGot] = useState({ key: null, dates: null, words: "", note: "" });
  useEffect(() => {
    if (!key) return undefined;
    let live = true;
    const t = setTimeout(() => {
      scheduleDates(JSON.parse(key)).then(
        (out) => live && setGot({ key, dates: out.dates || [], words: out.words || "", note: out.note || "" }),
        (err) => live && setGot({ key, dates: [], words: "", note: err?.message || "Couldn't work out the dates." }));
    }, 250);
    return () => { live = false; clearTimeout(t); };
  }, [key]);
  if (!preview) return { dates: null, words: "", note: "", lead: "Next", after: "", busy: false };
  if (!key) return { dates: null, words: "", note: preview.note, lead: preview.lead, after: "", busy: false };
  const ready = got.key === key;
  return { dates: ready ? got.dates : null, words: ready ? got.words : "", note: ready ? got.note : "", lead: preview.lead,
    after: preview.after, busy: !ready };
}
