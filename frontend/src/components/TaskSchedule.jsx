import { useState } from "react";
import { formatDate } from "../dates.js";
import { changeType, isCalendar, moreScheduleSummary, takesAlso, unitWord, withUnit } from "../howOften.js";
import { RuleLine, usePreview } from "./HowOften.jsx";
import Field from "./ui/Field.jsx";
import Fold from "./ui/Fold.jsx";
import QuantityInput from "./ui/QuantityInput.jsx";
import Select from "./Select.jsx";
import "./HowOften.css";

// A task's "How often" in the Explorer's task panel (MaintenanceTask; Derryn, 23 Nov 2026: "way too
// confusing"). One line, "Every [N] [unit]" (a QuantityInput: operating hours, the calendar, and
// cycles, starts or km where the position counts them), the next dates under it, and everything
// else folded under "More scheduling options": the second limit (whichever comes first), set
// calendar dates (a rule: "the first Saturday of every month"), at planned shutdowns, and when the
// item is replaced (`replace`, the caller's field). Folded with something set, its summary line
// says what. The form and what it saves are howOften.js's, as for a work package's HowOften.
//
//   value / onChange   the form (howOften.js formFromTask)
//   units              the units offered (howOften.js taskUnitChoices)
//   shutdowns          offer "At planned shutdowns" (a position's task)
//   replace            { node, value }: the When the item is replaced field and its value ("" = default)
//   preview            howOften.js previewFor: the next dates, from the server
const WHEN = [
  { value: "count", label: "From when it was last done (default)" },
  { value: "rule", label: "On set calendar dates" },
  { value: "shutdowns", label: "At planned shutdowns" },
];

export default function TaskSchedule({ value, onChange, units, shutdowns = false, replace = null, preview = null, problem = null,
  disabled = false, startOpen = false }) {
  const summary = moreScheduleSummary(value, { replace: replace?.value || "" });
  const [open, setOpen] = useState(startOpen);
  const shown = usePreview(problem ? null : preview);
  const n = Number(value.every);
  const set = (key) => (e) => onChange({ ...value, [key]: e.target.value });
  const calUnits = units.filter(isCalendar);
  const when = value.type === "rule" || value.type === "shutdowns" ? value.type : "count";
  const setWhen = (w) => {
    const t = w === "count" ? (isCalendar(value.unit) ? "interval" : "hours") : w;
    onChange(changeType(value, t, units));
  };
  const options = units.map((u) => ({ value: u, label: unitWord(u, n || 2) }));
  const list = preview ? shown.dates : null;
  return (
    <div className="how-often task-schedule" role="group" aria-label="How often">
      {value.type === "rule" ? (
        <RuleLine value={value} onChange={onChange} set={set} disabled={disabled} stepUnit={String(value.step || "").split(":")[0]} />
      ) : value.type === "shutdowns" ? (
        <div className="ho-line">
          <span className="ho-word">At the first planned shutdown</span>
          <QuantityInput label="How long after it was last done" value={value.every} onChange={(v) => onChange({ ...value, every: v })}
                         units={calUnits.map((u) => ({ value: u, label: unitWord(u, n || 2) }))} unit={value.unit}
                         onUnitChange={(u) => onChange({ ...value, unit: u })} unitLabel="Unit" chars={4} inputMode="numeric" disabled={disabled} />
          <span className="ho-word">after it was last done</span>
        </div>
      ) : (
        <div className="ho-line">
          <span className="ho-word">Every</span>
          <QuantityInput label="How many" value={value.every} onChange={(v) => onChange({ ...value, every: v })} units={options}
                         unit={value.unit} onUnitChange={(u) => onChange(withUnit(value, u))} unitLabel="Unit" chars={6} disabled={disabled} />
        </div>
      )}
      {problem ? <p className="field-error" role="alert">{problem}</p> : (
        <p className="ho-dates field-help" aria-live="polite">
          {preview && shown.words && when !== "count" && <>{shown.words[0].toUpperCase() + shown.words.slice(1)}. </>}
          {list && list.length > 0
            ? <>{shown.lead}: {list.map((d) => formatDate(d, { weekday: true })).join(" · ")}{shown.after ? `, ${shown.after}` : ""}</>
            : (preview && shown.busy ? "Working out the dates…" : shown.note || "")}
        </p>
      )}
      <Fold title="More scheduling options" summary={summary} open={open} onToggle={setOpen} className="mt-more-sched">
        <Field label="When it falls due">
          <Select value={when} onChange={setWhen} disabled={disabled} ariaLabel="When it falls due" className="mt-when"
                  options={WHEN.filter((w) => w.value !== "shutdowns" || shutdowns || value.type === "shutdowns")} />
        </Field>
        {takesAlso(value) && (
          <Field label="Or every" optional help="Whichever comes first.">
            <QuantityInput label="Second limit" value={value.also} placeholder="—" onChange={(v) => onChange({ ...value, also: v })}
                           units={units.map((u) => ({ value: u, label: unitWord(u, Number(value.also) || 2) }))} unit={value.alsoUnit}
                           onUnitChange={(u) => onChange({ ...value, alsoUnit: u })} unitLabel="Second limit's unit" chars={6} disabled={disabled} />
          </Field>
        )}
        {replace?.node}
      </Fold>
    </div>
  );
}
