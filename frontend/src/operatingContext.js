// A position's operating context (how it's used: the load, the environment,
// the hours it runs): the checks the Summary tab's card makes before saving,
// the same as the server's (trimmed, at most 4,000 characters, "" clears it).
// Pure functions, so node --test covers them.

export const CONTEXT_LIMIT = 4000;
export const CONTEXT_PROMPT = "How is it used? Describe the load, the environment and the hours it runs.";

// What would be saved from the text typed: { value } or { error }.
export function checkContext(raw) {
  const value = String(raw ?? "").trim();
  if (value.length > CONTEXT_LIMIT) {
    return { error: `The operating context is at most ${CONTEXT_LIMIT.toLocaleString("en-AU")} characters; this one is ${value.length.toLocaleString("en-AU")}. Shorten it.` };
  }
  return { value };
}

// Whether saving the draft would change anything.
export function contextChanged(saved, draft) {
  return String(saved ?? "").trim() !== String(draft ?? "").trim();
}

// "N characters left" once the draft is near the limit, else "".
export function charsLeft(draft, near = 200) {
  const left = CONTEXT_LIMIT - String(draft ?? "").length;
  if (left > near) return "";
  if (left < 0) return `${(-left).toLocaleString("en-AU")} characters too many`;
  return `${left.toLocaleString("en-AU")} character${left === 1 ? "" : "s"} left`;
}
