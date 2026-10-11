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
