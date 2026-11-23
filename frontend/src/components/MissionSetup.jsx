import Field from "./ui/Field.jsx";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import InputGroup, { Addon } from "./ui/InputGroup.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import { CLOCKS, setupErrors, unitsFor, withClock } from "../missionSetup.js";

// A mission's setup (the Missions tab, 23 Nov 2026), the one set of fields for a new mission and an
// open one: when it starts (now, or a date), its length (a new mission's: its first phase, in
// hours of running or days, months or years through its calendar; after that the phases rule),
// its calendar (the position's duty from Operations, or a simple duty of its own) and the state its
// blocks start in (new, or each at its item's age today). missionSetup.js holds the shape.
// Start and Calendar are the way in to the fields under them (a date; hours and days), so they're
// a SegmentedControl, exactly one shown chosen; the starting state is a plain saved value (ChoiceChips).
//
// At the top, its clock (Derryn, 23 Nov 2026): Operating time (a 10-flight-hour sortie: its length and
// phases in operating units, called what the user calls them; no calendar needed, so Start and
// Calendar fold under "On the calendar (optional)") or Calendar time (a start date, days to years,
// through its calendar, the conversion said in the answers).
//
//   value {clock, label, start, calendar, from, length?}   onChange(next)   withLength: show Length (a new one)
//   conversion: the answers' words for the calendar's conversion ("12 months ≈ 2,087 operating hours at …")
//   withFrom: show Starting state (a plain life model's mission has its own "Starts at")
//   tried: show errors   disabled

export default function MissionSetup({ value, onChange, withLength = false, withFrom = true, tried = false, disabled = false, conversion = "" }) {
  const v = value;
  const set = (patch) => onChange({ ...v, ...patch });
  const errs = setupErrors(v, { withLength });
  const linked = v.calendar?.linked !== false;
  const calendar = v.clock === "calendar";
  const opWord = String(v.label || "").trim() || "operating hours";
  const startField = (
    <Field label="Start" as="fieldset" error={tried ? errs.start : null}
           help={calendar ? (v.start === "now" ? "From today." : "Its dates count from this day.") : "Only needed to put it on the calendar."}>
      <div className="mission-setup-row">
        <SegmentedControl label="Start" value={v.start === "now" ? "now" : "date"}
                          onChange={(x) => !disabled && set({ start: x === "now" ? "now" : (v.start !== "now" ? v.start : "") })}
                          options={[{ value: "now", label: "Now", disabled }, { value: "date", label: "On a date", disabled }]} />
        {v.start !== "now" && (
          <TextInput type="date" aria-label="Start date" value={v.start || ""} disabled={disabled}
                     onChange={(e) => set({ start: e.target.value })} />
        )}
      </div>
    </Field>
  );
  const calendarField = (
    <Field label="Calendar" as="fieldset" error={tried ? errs.calendar : null}
           help={conversion || (linked ? "Runs as Operations says this position runs (its own duty, or the one from above; all the time with none)." : "Its own duty, for this mission only.")}>
      <div className="mission-setup-row">
        <SegmentedControl label="Calendar" value={linked ? "linked" : "own"}
                          onChange={(x) => !disabled && set({ calendar: x === "linked" ? { linked: true }
                            : { linked: false, hours_per_day: v.calendar?.hours_per_day ?? 8, days_per_week: v.calendar?.days_per_week ?? 5 } })}
                          options={[{ value: "linked", label: "Linked to Operations", disabled }, { value: "own", label: "Its own duty", disabled }]} />
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
  );
  const unitLabel = (u) => (u === "hours" ? opWord : u);
  return (
    <div className="mission-setup">
      <Field label="Clock" as="fieldset"
             help={calendar ? "A start date and a length on the calendar, turned into operating time through its calendar."
               : "Its length and phases in operating time (a 10-flight-hour sortie): no calendar needed."}>
        <SegmentedControl label="Clock" value={calendar ? "calendar" : "operating"}
                          onChange={(x) => !disabled && onChange(withClock(v, x))}
                          options={CLOCKS.map((c) => ({ ...c, disabled }))} />
      </Field>
      {!calendar && (
        <Field label="Its operating hours are called" optional help="Shown with every figure (flight hours, running hours); nothing is converted.">
          <TextInput value={v.label || ""} maxLength={40} placeholder="operating hours" disabled={disabled}
                     onChange={(e) => set({ label: e.target.value })} />
        </Field>
      )}
      {calendar && startField}
      {withLength && (
        <Field label="Length" error={tried ? errs.length : null}
               help={calendar ? "On the calendar: turned into operating time through its calendar." : `In ${opWord}: a 10-hour sortie is 10. Cycles or km need models that count in them, or a rate.`}>
          <InputGroup label="Length">
            <TextInput type="number" inputMode="decimal" min="0" step="any" aria-label="Length" placeholder={calendar ? "e.g. 12" : "e.g. 10"} disabled={disabled}
                       value={v.length?.value ?? ""} onChange={(e) => set({ length: { ...(v.length || {}), value: e.target.value } })} />
            <Select aria-label="Length unit" className="sel-embedded" disabled={disabled} value={v.length?.unit || unitsFor(v.clock)[0]}
                    onChange={(e) => set({ length: { ...(v.length || {}), unit: e.target.value } })}>
              {unitsFor(v.clock).map((u) => <option key={u} value={u}>{unitLabel(u)}</option>)}
            </Select>
          </InputGroup>
        </Field>
      )}
      {calendar && calendarField}
      {!calendar && (
        <details className="mission-setup-cal" open={v.start !== "now" || !linked || undefined}>
          <summary>On the calendar (optional)</summary>
          {startField}
          {calendarField}
        </details>
      )}
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
