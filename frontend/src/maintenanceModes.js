// Naming a failure mode where something fails (a removal, a work order, a past
// fitment): one of the position's modes, one seen at a like position, or one
// typed in. The picker's value is { choice, typed }: choice "" (none),
// "id:<mode id>", "text:<words>" or "new" (typed in).

// The choice as request fields: the mode's id, or its words (the server reuses
// the position's mode of that name, or adds an ad-hoc one).
export function failureModeBody(value) {
  const choice = value?.choice || "";
  if (choice.startsWith("id:")) return { failure_mode_id: choice.slice(3), failure_mode_text: null };
  const words = choice.startsWith("text:") ? choice.slice(5) : choice === "new" ? value.typed || "" : "";
  return { failure_mode_id: null, failure_mode_text: words.trim() || null };
}

// Whether the choice is complete: "something else" needs the words.
export function failureModeReady(value) {
  return value?.choice !== "new" || !!(value.typed || "").trim();
}

// Whether a mode is named at all.
export function failureModeNamed(value) {
  const body = failureModeBody(value);
  return !!(body.failure_mode_id || body.failure_mode_text);
}
