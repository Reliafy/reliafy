// The report composer's state changes (#30, #41), kept free of React so they
// can be tested: sections are [{ collection, artifact_id, name, kind, note }].

export const MAX_SECTIONS = 12;

export const sameItem = (a, b) => a.collection === b.collection && a.artifact_id === b.artifact_id;

// Add an item at the end, once; unchanged when it's already there or full.
export function addSection(sections, item) {
  if (!item || sections.some((s) => sameItem(s, item)) || sections.length >= MAX_SECTIONS) return sections;
  const { collection, artifact_id, name, kind } = item;
  return [...sections, { collection, artifact_id, name, kind, note: item.note || "" }];
}

export function removeSection(sections, index) {
  return sections.filter((_, i) => i !== index);
}

// Move the section at `index` by `delta` (-1 up, +1 down); unchanged at the ends.
export function moveSection(sections, index, delta) {
  const to = index + delta;
  if (to < 0 || to >= sections.length) return sections;
  const out = [...sections];
  [out[index], out[to]] = [out[to], out[index]];
  return out;
}

export function setNote(sections, index, note) {
  return sections.map((s, i) => (i === index ? { ...s, note } : s));
}

// A draft from the assistant fills the introduction and every note (a
// section the draft says nothing about keeps its note).
export function applyDraft(introduction, sections, draft) {
  const notes = draft?.notes || [];
  return {
    introduction: (draft?.introduction || "").trim() || introduction,
    sections: sections.map((s, i) => ((notes[i] || "").trim() ? { ...s, note: notes[i].trim() } : s)),
  };
}

// The body the API takes.
export function reportBody({ title, author, introduction, sections }) {
  return {
    title: (title || "").trim(),
    author: (author || "").trim(),
    introduction: introduction || "",
    sections: sections.map(({ collection, artifact_id, note }) => ({ collection, artifact_id, note: note || "" })),
  };
}

// The picker's options: the user's own items by kind, then the samples;
// items already in the report are left out.
export function pickerGroups(items, sections) {
  const groups = new Map();
  for (const it of items || []) {
    if (sections.some((s) => sameItem(s, it))) continue;
    const label = it.is_sample ? "Samples" : it.kind;
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(it);
  }
  const own = [...groups.entries()].filter(([label]) => label !== "Samples");
  const samples = groups.has("Samples") ? [["Samples", groups.get("Samples")]] : [];
  return [...own, ...samples];
}

// ---- The item picker: search, a kind filter, and each item's kind and date ----

const norm = (text) => String(text || "").toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "");

// The kinds there are to filter by, in the order the server lists them.
export function pickerKinds(items) {
  const out = [];
  for (const it of items || []) if (it.kind && !out.includes(it.kind)) out.push(it.kind);
  return out;
}

// The items the picker shows: not already in the report, of the chosen kind
// ("" for all), whose name or kind holds every word typed; the workspace's
// own first (newest first, as the server sends them), then the samples.
export function pickerRows(items, sections, { query = "", kind = "" } = {}) {
  const words = norm(query).split(/\s+/).filter(Boolean);
  const rows = (items || []).filter((it) => {
    if (sections.some((s) => sameItem(s, it))) return false;
    if (kind && it.kind !== kind) return false;
    const text = norm(`${it.name} ${it.kind}`);
    return words.every((w) => text.includes(w));
  });
  return [...rows.filter((r) => !r.is_sample), ...rows.filter((r) => r.is_sample)];
}

// Items whose name another item shares: the picker then says when each was
// saved, so two "Weibull — pasted values" can be told apart.
export function duplicateNames(items) {
  const seen = new Map();
  for (const it of items || []) seen.set(norm(it.name), (seen.get(norm(it.name)) || 0) + 1);
  return new Set([...seen.entries()].filter(([, n]) => n > 1).map(([name]) => name));
}
export const isDuplicate = (dupes, item) => dupes.has(norm(item.name));

// A renamed item, everywhere the composer shows it.
export function renameItem(list, item, name) {
  return (list || []).map((x) => (sameItem(x, item) ? { ...x, name } : x));
}

// Collections a report's items come from that can be renamed from the picker.
export const RENAMABLE = new Set([
  "models", "recurrent_models", "alt_models", "degradation_models", "rbds", "fault_trees",
  "reliability_predictions", "strategy_analyses", "fleets", "datasets",
]);

// Reports' address for one report (#30): ``?open=<id>`` shows it as readers
// see it; ``&edit=1`` opens its editor; ``?new=1`` starts a new one, with
// ``&add=<collection>:<id>`` (an item's Share › Add to a report…) in it.
export function reportHref({ open = "", edit = false, add = null } = {}) {
  const q = new URLSearchParams();
  if (open) {
    q.set("open", open);
    if (edit) q.set("edit", "1");
  } else {
    q.set("new", "1");
    if (add?.collection && add?.artifact_id) q.set("add", `${add.collection}:${add.artifact_id}`);
  }
  return `/reports?${q.toString()}`;
}

// ``?add=models:abc`` → { collection: "models", artifact_id: "abc" }, or null.
export function parseAdd(value) {
  const m = /^([a-z_]{1,40}):([\w.:-]{1,200})$/.exec(String(value || ""));
  return m ? { collection: m[1], artifact_id: m[2] } : null;
}
