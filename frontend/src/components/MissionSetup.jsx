import Field from "./ui/Field.jsx";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import InputGroup, { Addon } from "./ui/InputGroup.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import { setupErrors } from "../missionSetup.js";

// A mission's setup (the Missions tab, 23 Nov 2026), the one set of fields for a new mission and an
// open one: when it starts (now, or a date), its length (a new mission's: its first phase, in
// hours of running or days, months or years through its calendar; after that the phases rule),
// its calendar (the position's duty from Operations, or a simple duty of its own) and the state its
// blocks start in (new, or each at its item's age today). missionSetup.js holds the shape.
//
//   value {start, calendar, from, length?}   onChange(next)   withLength: show Length (a new one)
//   withFrom: show Starting state (a plain life model's mission has its own "Starts at")
//   tried: show errors   disabled

export default function MissionSetup({ value, onChange, withLength = false, withFrom = true, tried = false, disabled = false }) {
  const v = value;
  const set = (patch) => onChange({ ...v, ...patch });
  const errs = setupErrors(v, { withLength });
  const linked = v.calendar?.linked !== false;
  return (
    <div className="mission-setup">
      <Field label="Start" as="fieldset" error={tried ? errs.start : null}
             help={v.start === "now" ? "From today." : "Its dates count from this day."}>
        <div className="mission-setup-row">
          <ChoiceChips label="Start" disabled={disabled} value={v.start === "now" ? "now" : "date"}
                       onChange={(x) => x && set({ start: x === "now" ? "now" : (v.start !== "now" ? v.start : "") })}
                       options={[{ value: "now", label: "Now" }, { value: "date", label: "On a date" }]} />
          {v.start !== "now" && (
            <TextInput type="date" aria-label="Start date" value={v.start || ""} disabled={disabled}
                       onChange={(e) => set({ start: e.target.value })} />
          )}
        </div>
      </Field>
      {withLength && (
        <Field label="Length" error={tried ? errs.length : null}
               help={v.length?.unit === "hours" ? "Hours of running: a 10-hour sortie is 10." : "On the calendar: turned into running time through its calendar."}>
          <InputGroup label="Length">
            <TextInput type="number" inputMode="decimal" min="0" step="any" aria-label="Length" placeholder="e.g. 12" disabled={disabled}
                       value={v.length?.value ?? ""} onChange={(e) => set({ length: { ...(v.length || {}), value: e.target.value } })} />
            <Select aria-label="Length unit" className="sel-embedded" disabled={disabled} value={v.length?.unit || "months"}
                    onChange={(e) => set({ length: { ...(v.length || {}), unit: e.target.value } })}>
              <option value="hours">hours</option>
              <option value="days">days</option>
              <option value="months">months</option>
              <option value="years">years</option>
            </Select>
          </InputGroup>
        </Field>
      )}
      <Field label="Calendar" as="fieldset" error={tried ? errs.calendar : null}
             help={linked ? "Runs as Operations says this position runs (its own duty, or the one from above; all the time with none)." : "Its own duty, for this mission only."}>
        <div className="mission-setup-row">
          <ChoiceChips label="Calendar" disabled={disabled} value={linked ? "linked" : "own"}
                       onChange={(x) => x && set({ calendar: x === "linked" ? { linked: true }
                         : { linked: false, hours_per_day: v.calendar?.hours_per_day ?? 8, days_per_week: v.calendar?.days_per_week ?? 5 } })}
                       options={[{ value: "linked", label: "Linked to Operations" }, { value: "own", label: "Its own duty" }]} />
          {!linked && (
            <>
              <InputGroup label="Hours a day">
                <TextInput type="number" inputMode="decimal" min="0" max="24" step="any" aria-label="Hours a day" disabled={disabled}
                           value={v.calendar.hours_per_day ?? ""} onChange={(e) => set({ calendar: { ...v.calendar, hours_per_day: e.target.value } })} />
                <Addon>h a day</Addon>
              </InputGroup>
              <InputGroup label="Days a week">
                <TextInput type="number" inputMode="numeric" min="1" max="7" step="1" aria-label="Days a week" disabled={disabled}
                           value={v.calendar.days_per_week ?? ""} onChange={(e) => set({ calendar: { ...v.calendar, days_per_week: e.target.value } })} />
                <Addon>days a week</Addon>
              </InputGroup>
            </>
          )}
        </div>
      </Field>
      {withFrom && (
        <Field label="Starting state" as="fieldset"
               help={v.from === "today" ? "Each block starts at its item's age today; a block with no age to read starts new, and the answers say which." : "Every block starts new."}>
          <ChoiceChips label="Starting state" disabled={disabled} value={v.from || "new"} onChange={(x) => x && set({ from: x })}
                       options={[{ value: "new", label: "New" }, { value: "today", label: "As today" }]} />
        </Field>
      )}
    </div>
  );
}
