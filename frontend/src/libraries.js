// Libraries (Derryn, 13 Nov 2026): a user's own libraries of datasets and models (snapshots),
// kept private, shared with other workspaces by their IDs, or published, beside the built-in
// handbooks. The words, the grouping and the filtering behind the pages (views/Libraries.jsx,
// views/PublicLibraryPage.jsx and components/LibraryEntries.jsx).

export const LIBRARIES_PATH = "/libraries";
export const libraryPath = (id) => `${LIBRARIES_PATH}/${encodeURIComponent(id)}`;
// An entry's place on its library's page: the row's anchor.
export const entryAnchor = (entryId) => `entry-${String(entryId).replace(/[^A-Za-z0-9_-]/g, "-")}`;
export const entryPath = (libraryId, entryId) => `${libraryPath(libraryId)}#${entryAnchor(entryId)}`;

// The addresses under /libraries that are pages of their own, not a library.
const STATIC = new Set(["data", "models"]);

// The library a signed-out visitor (or "Preview as public") may open: /libraries/<id> only.
export function publicLibraryId(pathname) {
  const m = /^\/libraries\/([^/]+)\/?$/.exec(pathname || "");
  if (!m || STATIC.has(m[1])) return null;
  try {
    return decodeURIComponent(m[1]);
  } catch {
    return null;
  }
}

// Whether App.jsx shows the standalone public page instead of the app: nobody signed in, or the
// owner's "Preview as public" (?as=public), on a library's own address.
export function showsPublicLibrary(pathname, search, signedIn) {
  if (!publicLibraryId(pathname)) return false;
  if (!signedIn) return true;
  return new URLSearchParams(search || "").get("as") === "public";
}

export const VISIBILITY_LABEL = { private: "Private", workspaces: "Shared", public: "Public" };
export const VISIBILITY_WORDS = {
  private: "Private: your workspace only.",
  workspaces: "Shared with the workspaces you name. They can view and copy; only you can change it.",
  public: "Public: anyone, signed out too, can view it; anyone signed in can copy from it.",
};

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

// "3 datasets · 2 models"; a handbook's records are its models.
export function countsText(card) {
  const c = card?.counts || {};
  if (card?.builtin) return plural(c.model || c.total || 0, "record");
  return `${plural(c.data || 0, "dataset")} · ${plural(c.model || 0, "model")}`;
}

// The libraries page's three sections, in the server's order within each.
export function groupLibraries(cards = []) {
  const out = { yours: [], shared: [], public: [] };
  for (const c of cards || []) (out[c.relation] || out.public).push(c);
  return out;
}

const norm = (s) => String(s ?? "").toLowerCase();

// A card matches a search by its name, purpose, source or citation.
export function libraryMatches(card, q) {
  const t = norm(q).trim();
  if (!t) return true;
  return [card.name, card.description, card.source, card.citation, card.licence?.name].some((x) => norm(x).includes(t));
}

// Every tag the entries carry, sorted, once each.
export function entryTags(entries = []) {
  return [...new Set((entries || []).flatMap((e) => e.tags || []))].sort((a, b) => a.localeCompare(b));
}

// What a search reads on an entry: its name, tags, and the words shown with it.
function entryText(e) {
  return [e.name, ...(e.tags || []), e.data?.reading_summary, e.model?.distribution, e.model?.headline?.text,
    e.model?.basis_text, e.model?.kind_label, e.library?.name].map(norm).join(" ");
}

// The entries a library's page shows: kind "" | "data" | "model", a tag, and words.
export function filterEntries(entries = [], { kind = "", tag = "", q = "" } = {}) {
  const t = norm(q).trim();
  return (entries || []).filter((e) => (!kind || e.type === kind)
    && (!tag || (e.tags || []).includes(tag))
    && (!t || entryText(e).includes(t)));
}

// A model entry's headline: the server's sentence (a B-life with its bound), or its
// distribution and unit when it has none.
export function modelHeadline(model) {
  if (!model) return "";
  if (model.headline?.text) return model.headline.text;
  return [model.distribution, model.unit && `in ${model.unit}`].filter(Boolean).join(", ");
}

// Where a model came from, said once: "fitted on ↑ <dataset>" when that dataset is in the library
// (a link to it), else the server's words ("From parameters", "From MIL-HDBK-217F"...).
export function modelBasis(model) {
  if (!model) return null;
  if (model.fitted_on?.entry_id) return { fittedOn: model.fitted_on };
  return model.basis_text ? { text: model.basis_text } : null;
}

// A data entry's line: its columns read as, and its size.
export function dataLine(data) {
  if (!data) return "";
  const rows = data.n_rows == null ? null : plural(data.n_rows, "row");
  return [data.reading_summary, rows].filter(Boolean).join(" · ");
}

// The Sharing panel's choice to save: what's still missing, in words (none: ready).
export function sharingProblems({ visibility, workspaces = [], licence = "", citation = "", rights = false }) {
  const out = [];
  if (visibility === "workspaces" && !workspaces.length) out.push("Add at least one workspace ID.");
  if (visibility === "public") {
    if (!licence) out.push("Choose a licence.");
    if (!String(citation).trim()) out.push("Give the source or citation.");
    if (!rights) out.push("Tick that you have the right to publish it.");
  }
  return out;
}

// A workspace ID added to the list: trimmed, once.
export function addWorkspaceId(list = [], id = "") {
  const t = String(id).trim();
  if (!t || list.includes(t)) return list;
  return [...list, t];
}

// The body PUT /api/libraries/:id/visibility takes for the panel's choice.
export function visibilityBody({ visibility, workspaces = [], licence = "", source = "", citation = "", rights = false }) {
  if (visibility === "workspaces") return { visibility, workspaces };
  if (visibility === "public") {
    return { visibility, licence, source: String(source).trim(), citation: String(citation).trim(), rights_confirmed: !!rights };
  }
  return { visibility: "private" };
}

// After "Use this data" / "Use this model": what was made, as links.
export function usedLinks(result) {
  const out = [];
  if (result?.model) out.push({ label: result.model.name || "the model", to: result.model.url, what: "model" });
  if (result?.dataset) {
    out.push({ label: result.dataset.name || "the data", to: result.dataset.url, what: "dataset", reused: !!result.dataset.reused });
  }
  return out;
}

// New dataset's "Also add to library": {libraryId, newName}. Ready unless New library… has no name yet.
export const libraryChoiceReady = (value) => value?.libraryId !== "new" || !!String(value?.newName || "").trim();

// The words after an upload that also went into a library (the answer's ``library``): what was added and
// what was in it already.
export function addedToLibraryWords(library) {
  const n = library?.added?.length || 0;
  const already = library?.already?.length || 0;
  const lead = n === 0 ? "Already in" : n === 1 ? "Added it to" : `Added all ${n} to`;
  const tail = n > 0 && already > 0 ? ` ${already} ${already === 1 ? "was" : "were"} in it already.` : "";
  return { lead, tail };
}

// Where Data's New dataset sends you after one dataset is saved: its page, told whether the data was
// already yours (reused) and which library it went into.
export function createdState(ds, typedName = null) {
  const state = {
    ...(ds?.reused ? { reused: true, name: typedName || null } : {}),
    ...(ds?.library ? { library: ds.library } : {}),
  };
  return Object.keys(state).length ? { state } : undefined;
}
