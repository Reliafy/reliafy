// A task's trigger in its Edit… form (RcmModeTasks): "Every interval" (as
// always) or "When an event happens": a reading on a measuring point past a
// limit (120 mm on POOL-RAIN), or an event someone logs on the position by
// name (Lightning strike). With "Keep the interval too" both raise it.
//
// The form's state is plain: {mode: "interval" | "event", by: "reading" |
// "name", pointId, side: "above" | "below", limit (as typed), eventType, note,
// withInterval}. `triggerBody` turns it into the PATCH body's `trigger`
// (null: none), `triggerWhy` says what's missing ("" when it can be saved).

export function triggerState(task) {
  const t = task?.trigger || null;
  return {
    mode: t ? "event" : "interval",
    by: t?.kind === "event" ? "name" : "reading",
    pointId: t?.point_id || "",
    side: t?.below != null ? "below" : "above",
    limit: t?.kind === "reading" ? String(t.above ?? t.below ?? "") : "",
    eventType: t?.event_type || "",
    note: t?.note || "",
    withInterval: !!t?.with_interval,
  };
}

// Whether the interval fields are asked for: every interval, or kept beside the event.
export const asksInterval = (st) => st.mode === "interval" || st.withInterval;

export function triggerWhy(st) {
  if (st.mode !== "event") return "";
  if (st.by === "reading") {
    if (!st.pointId) return "Pick the measuring point to watch.";
    if (String(st.limit).trim() === "" || !Number.isFinite(Number(st.limit))) return "Enter the limit: a number.";
    return "";
  }
  return st.eventType.trim() ? "" : "Name the event, e.g. Lightning strike.";
}

export function triggerBody(st) {
  if (st.mode !== "event") return null;
  const keep = st.withInterval ? { with_interval: true } : {};
  if (st.by === "reading") return { kind: "reading", point_id: st.pointId, [st.side]: Number(st.limit), ...keep };
  const note = st.note.trim();
  return { kind: "event", event_type: st.eventType.trim().replace(/\s+/g, " "), ...(note ? { note } : {}), ...keep };
}

// A measuring point as the picker lists it: "POOL-RAIN (mm) · on Aquatic centre".
export function pointLabel(p) {
  return `${p.name}${p.unit ? ` (${p.unit})` : ""}${p.on?.name ? ` · on ${p.on.name}` : ""}`;
}

// A task's line in a list (the Explorer's Summary, Work): when it's next due,
// or, raised by an event, what it waits for ("Waiting for the event: 120 mm on
// POOL-RAIN"). `fmt` formats a date; `note` is said when there's neither.
export function taskDueText(t, fmt, note = null) {
  if (t.next_due) return `Next due ${fmt(t.next_due)}`;
  if (t.on_event) {
    return t.open_work_order ? "Raised: its work order is open" : `Waiting for the event${t.trigger?.text ? `: ${t.trigger.text}` : ""}`;
  }
  return note || "No due date";
}
