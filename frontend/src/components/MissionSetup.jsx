import Field from "./ui/Field.jsx";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import Section from "./ui/Section.jsx";
import QuantityInput from "./ui/QuantityInput.jsx";
import { TextInput } from "./ui/Controls.jsx";
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
//   sections: group the fields under two modest headings (a new mission's form): "Clock and length"
//     (clock, length and what its hours are called, then its calendar) and "What it runs on"
//     (starting state, then `runsOn`, the form's Runs on field). The open mission's Set-up is one
//     list in the same order.
// Every number with a unit is the shared QuantityInput: one box, one focus ring, no spinners.

export default function MissionSetup({ value, onChange, withLength = false, withFrom = true, tried = false, disabled = false, conversion = "",
  sections = false, runsOn = null }) {
  const v = value;
  const set = (patch) => onChange({ ...v, ...patch });
  const errs = setupErrors(v, { withLength });
  const linked = v.calendar?.linked !== false;
  const calendar = v.clock === "calendar";
  const opWord = String(v.label || "").trim() || "operating hours";
  const lengthUnit = v.length?.unit || unitsFor(v.clock)[0];
  const startField = (
    <Field label="Start" as="fieldset" error={tried ? errs.start : null}
           help={calendar ? (v.start === "now" ? "From today." : "Its dates count from this day.") : "Only to put it on the calendar."}>
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
           help={conversion || (linked ? "As Operations says this position runs; all the time if it has no duty." : "Its own duty, for this mission only.")}>
      <SegmentedControl label="Calendar" value={linked ? "linked" : "own"}
                        onChange={(x) => !disabled && set({ calendar: x === "linked" ? { linked: true }
                          : { linked: false, hours_per_day: v.calendar?.hours_per_day ?? 8, days_per_week: v.calendar?.days_per_week ?? 5 } })}
                        options={[{ value: "linked", label: "Linked to Operations", disabled }, { value: "own", label: "Its own duty", disabled }]} />
      {!linked && (
        <div className="mission-setup-row">
          <QuantityInput label="Hours a day" suffix="h a day" chars={4} min="0" max="24" disabled={disabled}
                         value={v.calendar.hours_per_day} onChange={(x) => set({ calendar: { ...v.calendar, hours_per_day: x } })} />
          <QuantityInput label="Days a week" suffix="days a week" chars={3} min="1" max="7" step="1" inputMode="numeric" disabled={disabled}
                         value={v.calendar.days_per_week} onChange={(x) => set({ calendar: { ...v.calendar, days_per_week: x } })} />
        </div>
      )}
    </Field>
  );
  const lengthHelp = calendar ? "Turned into operating hours by its calendar."
    : lengthUnit === "hours" ? `In ${opWord}. Cycles or km need a rate per hour.` : `Needs models in ${lengthUnit}, or a rate per hour.`;
  const clock = (
    <Field label="Clock" as="fieldset"
           help={calendar ? "Length in days to years, turned into operating hours by its calendar."
             : "Length and phases in operating hours. No calendar needed."}>
      <SegmentedControl label="Clock" value={calendar ? "calendar" : "operating"}
                        onChange={(x) => !disabled && onChange(withClock(v, x))}
                        options={CLOCKS.map((c) => ({ ...c, disabled }))} />
    </Field>
  );
  const lengthRow = (withLength || !calendar) && (
    <div className="mission-setup-grid">
      {withLength && (
        <Field label="Length" error={tried ? errs.length : null} help={lengthHelp}>
          <QuantityInput label="Length" placeholder={calendar ? "e.g. 12" : "e.g. 10"} disabled={disabled}
                         value={v.length?.value} onChange={(x) => set({ length: { ...(v.length || {}), value: x } })}
                         units={unitsFor(v.clock).map((u) => ({ value: u, label: u === "hours" ? opWord : u }))} unitLabel="Length unit"
                         unit={lengthUnit} onUnitChange={(u) => set({ length: { ...(v.length || {}), unit: u } })} />
        </Field>
      )}
      {!calendar && (
        <Field label="Its operating hours are called" optional help="Shown with every figure. Nothing is converted.">
          <TextInput value={v.label || ""} maxLength={40} placeholder="e.g. flight hours" disabled={disabled}
                     onChange={(e) => set({ label: e.target.value })} />
        </Field>
      )}
    </div>
  );
  const calendarPart = calendar ? <>{startField}{calendarField}</> : (
    <details className="mission-setup-cal" open={v.start !== "now" || !linked || undefined}>
      <summary>On the calendar (optional)</summary>
      {startField}
      {calendarField}
    </details>
  );
  const from = withFrom && (
    <Field label="Starting state" as="fieldset"
           help={v.from === "today" ? "Each block starts at its item's age today, or new where there's no age to read." : "Every block starts new."}>
      <ChoiceChips label="Starting state" disabled={disabled} value={v.from || "new"} onChange={(x) => x && set({ from: x })}
                   options={[{ value: "new", label: "New" }, { value: "today", label: "As today" }]} />
    </Field>
  );
  if (sections) {
    return (
      <div className="mission-setup">
        <Section title="Clock and length" className="mission-setup-sec">
          {clock}
          {lengthRow}
          {calendarPart}
        </Section>
        <Section title="What it runs on" className="mission-setup-sec">
          {from}
          {runsOn}
        </Section>
      </div>
    );
  }
  return (
    <div className="mission-setup">
      {clock}
      {lengthRow}
      {calendarPart}
      {from}
      {runsOn}
    </div>
  );
}
