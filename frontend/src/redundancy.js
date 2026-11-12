// Redundancy sets in the Explorer (Derryn, 12 Nov 2026): on a position, which positions inside it
// back each other up. Either any k of them will do, all running ("active"), or a duty and standby
// set where the others wait to take over ("standby": cold, warm or hot, with the chance a waiting
// one starts when it's switched in, and how fast a warm one ages while it waits). Build from
// what's inside wires each set as redundancy (backend rbd_derive): a k-of-n vote, or one standby
// block when the members are identical single positions; never in series.
//
// A set as the API gives it: {id, name, k, n, mode, standby, start_probability, dormancy,
// members: [{id, name}]}. A draft is what the pane edits: {id?, name, members: [ids], mode, k,
// standby, start (percent text), ages (percent text)}.

export const STANDBY_KINDS = [
  { value: "cold", label: "Cold", help: "Off while it waits: it doesn't age until it's started." },
  { value: "warm", label: "Warm", help: "Idling while it waits: it ages more slowly than when it runs." },
  { value: "hot", label: "Hot", help: "Running while it waits: it ages as fast as the duty one." },
];

const pct = (x) => (x == null || x === "" || !Number.isFinite(Number(x)) ? "" : String(Number((Number(x) * 100).toPrecision(6))));

export function blankDraft() {
  return { id: null, name: "", members: [], mode: "active", k: 1, standby: "cold", start: "", ages: "" };
}

export function draftFrom(set) {
  return {
    id: set.id, name: set.name || "", members: (set.members || []).map((m) => m.id), mode: set.mode || "active",
    k: set.k || 1, standby: set.standby || "cold", start: pct(set.start_probability), ages: pct(set.dormancy),
  };
}

// "98" or "98%" -> 0.98; "" -> null (not set); NaN for anything else.
export function parsePercent(text) {
  const t = String(text ?? "").trim().replace(/%$/, "").trim();
  if (!t) return null;
  const x = Number(t);
  return Number.isFinite(x) ? Number((x / 100).toPrecision(12)) : NaN;
}

// What stops a draft being saved, in plain words (the backend checks the same).
export function draftProblems(d) {
  const out = [];
  const n = d.members.length;
  if (n < 2) out.push("Tick at least two positions that back each other up.");
  const k = Number(d.k);
  if (n >= 2 && !(Number.isInteger(k) && k >= 1 && k < n)) {
    out.push(`How many are needed at once is a whole number from 1 to ${n - 1}.`);
  }
  if (d.mode === "standby") {
    const start = parsePercent(d.start);
    if (d.standby === "cold" && start != null && !(start > 0 && start <= 1)) {
      out.push("The chance it starts is a percentage above 0 and at most 100.");
    }
    const ages = parsePercent(d.ages);
    if (d.standby === "warm" && ages != null && !(ages >= 0 && ages <= 1)) {
      out.push("How fast it ages while waiting is a percentage from 0 to 100.");
    }
  }
  return out;
}

// The request body for a draft: a new set's (createRedundancyGroup) or, with `was` (the set as
// saved), the changes to it (updateRedundancyGroup: add / remove members, "" clears a setting).
export function draftBody(d, was = null) {
  const standby = d.mode === "standby";
  const start = standby && d.standby === "cold" ? parsePercent(d.start) : null;
  const ages = standby && d.standby === "warm" ? parsePercent(d.ages) : null;
  const common = { name: d.name.trim(), k: Number(d.k), mode: d.mode, standby: d.standby };
  if (!was) {
    return { ...common, member_ids: d.members, ...(start != null ? { start_probability: start } : {}),
      ...(ages != null ? { dormancy: ages } : {}) };
  }
  const before = (was.members || []).map((m) => m.id);
  const body = { ...common, add: d.members.filter((id) => !before.includes(id)),
    remove: before.filter((id) => !d.members.includes(id)) };
  if (!common.name) delete body.name;
  if ((start ?? null) !== (was.start_probability ?? null)) body.start_probability = start ?? "";
  if ((ages ?? null) !== (was.dormancy ?? null)) body.dormancy = ages ?? "";
  return body;
}

// A set in a line: "Any 1 of 3 needed" or "1 running, 1 on cold standby · starts 98% of the time".
export function setWords(set) {
  const n = set.n ?? (set.members || []).length;
  const k = set.k || 1;
  if (set.mode !== "standby") return `Any ${k} of ${n} needed, all running`;
  const kind = set.standby || "cold";
  const extra = kind === "cold" && set.start_probability != null ? ` · starts ${pct(set.start_probability)}% of the time`
    : kind === "warm" && set.dormancy != null ? ` · ages at ${pct(set.dormancy)}% while waiting` : "";
  return `${k} running, ${n - k} on ${kind} standby${extra}`;
}

// The tree's badge on a member (row.redundancy from the tree read): short, with the set's name in
// its title. "1 of 2" for any-k-of-n; "Standby" for duty and standby.
export function badge(mark) {
  if (!mark) return null;
  const text = mark.mode === "standby" ? "Standby set" : `${mark.k} of ${mark.n}`;
  const title = `In the redundancy set ${mark.name}: ${setWords(mark)}`;
  return { text, title };
}
