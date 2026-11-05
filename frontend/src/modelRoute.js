// Where each kind of saved model opens. A model page that's given another
// kind's id (an old link, a hand-typed address, a feed row) sends it to that
// model's own page; an id no list knows says so, with links back.

// The model pages, in the order an unknown id is looked up. ``key`` matches
// allModels.js's row types.
export const MODEL_PAGES = [
  { key: "life", label: "non-repairable", base: "/models/m/", list: "/models/life", listLabel: "Non-repairable models" },
  { key: "recurrent", label: "repairable", base: "/models/recurrent/", list: "/models/recurrent", listLabel: "Repairable models" },
  { key: "alt", label: "accelerated life", base: "/models/alt/", list: "/models/alt", listLabel: "Accelerated life models" },
  { key: "degradation", label: "degradation", base: "/models/degradation/", list: "/models/degradation", listLabel: "Degradation models" },
  { key: "joint", label: "condition and life", base: "/models/joint/", list: "/models/joint", listLabel: "Condition and life models" },
];

export const modelPage = (key) => MODEL_PAGES.find((p) => p.key === key) || null;

// Kinds stored with the non-repairable models (``/api/models``) that have a
// page of their own.
const KIND_PAGE = { joint: "joint" };

// The page for a model fetched from /api/models/:id, or null when the
// non-repairable page is the right one.
export function otherModelPage(model) {
  const page = model && modelPage(KIND_PAGE[model.kind]);
  return page ? { label: page.label, to: page.base + model.id } : null;
}

// The pages to try for an id the ``current`` page couldn't find.
export const otherPages = (current) => MODEL_PAGES.filter((p) => p.key !== current);

// Given the settled lookups (same order as ``pages``), the first page that
// found the id, or null.
export function firstFound(id, pages, settled) {
  const i = (settled || []).findIndex((s) => s && s.status === "fulfilled" && s.value);
  return i < 0 ? null : { label: pages[i].label, to: pages[i].base + id };
}
