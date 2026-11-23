import { useEffect, useState } from "react";
import { getTaskTriggerPoints } from "../api.js";
import { pointLabel } from "../taskTrigger.js";
import Field from "./ui/Field.jsx";
import InputGroup from "./ui/InputGroup.jsx";
import { Checkbox, Select, TextInput } from "./ui/Controls.jsx";

// What raises a task besides (or instead of) its interval: a reading past a limit on a
// measuring point, or an event someone logs by name (taskTrigger.js). `onBack` leaves it.
export default function TriggerFields({ task, trig, setTrig, busy, onBack, backLabel = "Back to every interval" }) {
  const setT = (k) => (e) => setTrig((x) => ({ ...x, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  const [points, setPoints] = useState(null);
  useEffect(() => {
    if (trig.mode !== "event" || trig.by !== "reading" || points || !task?.id) return undefined;
    let on = true;
    getTaskTriggerPoints(task.id).then((out) => { if (on) setPoints(out.points || []); }, () => { if (on) setPoints([]); });
    return () => { on = false; };
  }, [trig.mode, trig.by, points, task?.id]);
  return (
    <fieldset className="rim-trigger">
      <legend>Raised by an event · <button type="button" className="link" disabled={busy}
              onClick={onBack}>{backLabel}</button></legend>
      <Field label="What happens">
        <Select value={trig.by} disabled={busy} onChange={setT("by")}>
          <option value="reading">A reading passes a limit</option>
          <option value="name">Someone logs an event</option>
        </Select>
      </Field>
      {trig.by === "reading" ? (
        <div className="rim-trow">
          <Field label="Measuring point">
            <Select value={trig.pointId} disabled={busy || points === null} onChange={setT("pointId")}>
              <option value="">{points === null ? "Reading the points…" : points.length ? "Choose a point…" : "No condition points nearby"}</option>
              {(points || []).map((p) => <option key={p.id} value={p.id}>{pointLabel(p)}</option>)}
            </Select>
          </Field>
          <Field label="Limit" as="fieldset">
            <InputGroup label="Limit">
              <Select value={trig.side} disabled={busy} aria-label="Above or below" onChange={setT("side")}>
                <option value="above">At or above</option>
                <option value="below">At or below</option>
              </Select>
              <TextInput type="number" inputMode="decimal" step="any" value={trig.limit} readOnly={busy}
                         aria-label="Limit" placeholder="e.g. 120" onChange={setT("limit")} />
            </InputGroup>
          </Field>
        </div>
      ) : (
        <Field label="Event name" help="Logged on this position, or one above it, from its ⋯ menu: Log an event…">
          <TextInput value={trig.eventType} readOnly={busy} placeholder="e.g. Lightning strike" onChange={setT("eventType")} />
        </Field>
      )}
      <Checkbox className="rim-check" checked={trig.withInterval} disabled={busy} onChange={setT("withInterval")}
                label="Keep the interval too (whichever comes first)" />
      {!trig.withInterval && <p className="rw-fhelp">It waits for the event: never overdue, and each event raises one work order.</p>}
    </fieldset>
  );
}

