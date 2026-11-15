import { useEffect, useState } from "react";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import RbdCovariateSchedule from "./RbdCovariateSchedule.jsx";
import { draftFromSpec, initialTable, presetExpression, scheduleSpec } from "../rbdTvc.js";
import { isSchedule } from "../explorerMissions.js";
import "./PhaseCovValue.css";

const MODES = [
  { value: "constant", label: "One value" },
  { value: "schedule", label: "Schedule" },
];

// A covariate's value in one mission phase (#372): one value for the whole phase, or a schedule
// over the phase (an expression in t from the phase's start, or a table), with the same editor as
// a block's schedule in the builder. One component for the Explorer's mission tree and the
// builder's Phased mission window, so both store the same thing (the phase's `values`).
//
//   cov        {name, unit, kind ("number" | "choice"), choices}
//   value      the stored value: a number, a choice's code, a schedule, or "" / null for none
//   onChange   (value) => void: a number (or code), a schedule spec, or "" to clear
//   constant   the one-value input (rendered by the caller, as each place already styles it)
//   unit       the diagram's time unit; duration the phase's length (the presets' window)
export default function PhaseCovValue({ cov, value, onChange, constant, unit, duration, disabled = false }) {
  const scheduled = isSchedule(value);
  const [mode, setMode] = useState(scheduled ? "schedule" : "constant");
  const [draft, setDraft] = useState(() => (scheduled ? draftFromSpec(value) : null));
  useEffect(() => {
    if (isSchedule(value)) {
      setMode("schedule");
      setDraft((d) => (d && JSON.stringify(scheduleSpec(d)) === JSON.stringify(value) ? d : draftFromSpec(value)));
    }
  }, [JSON.stringify(value)]); // eslint-disable-line react-hooks/exhaustive-deps
  const field = {
    name: cov.name,
    unit: cov.unit,
    type: cov.kind === "choice" ? "category" : "number",
    options: (cov.choices || []).map((c) => c.code),
  };
  const choose = (m) => {
    setMode(m);
    if (m === "constant") {
      onChange("");
      return;
    }
    const d = field.type === "number"
      ? { expression: presetExpression("constant", field, { value: Number(value) || 0 }) }
      : { table: initialTable(field, value || field.options[0]), period: "" };
    setDraft(d);
    onChange(scheduleSpec(d) || "");
  };
  const edit = (d) => {
    setDraft(d);
    onChange(scheduleSpec(d) || "");
  };
  return (
    <div className="phase-cov-value">
      <SegmentedControl size="sm" label={`One value or a schedule over the phase for ${cov.name}`} options={MODES}
                        value={mode} onChange={(m) => !disabled && choose(m)} />
      {mode === "constant" ? constant : (
        <RbdCovariateSchedule field={field} draft={draft} onDraft={edit} unit={unit} tMax={Number(duration) || null}
                              value={value} inPhase disabled={disabled} />
      )}
    </div>
  );
}
