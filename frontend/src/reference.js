// Model reference — the lookup catalogue behind /reference.
//
// Two halves, deliberately kept separate:
//   * catalogue.json  — GENERATED from the backend registries
//     (backend/scripts/export_reference.py). Ids, parameter names, bounds,
//     support, effect types. Never hand-edited, so it can't go stale.
//   * content/reference/*.md — the human half: what each model is for, the
//     functional form, and what to watch out for. One file per family, split
//     into `## <entry-id>` sections.
//
// A backend test asserts the JSON is current and that every id has prose.
import { marked } from "marked";
import catalogue from "./content/reference/catalogue.json";

const files = import.meta.glob("./content/reference/*.md", {
  query: "?raw",
  import: "default",
  eager: true,
});

function parseFrontmatter(raw) {
  const match = /^---\s*\r?\n([\s\S]*?)\r?\n---\s*\r?\n?([\s\S]*)$/.exec(raw);
  if (!match) return { meta: {}, body: raw };
  const meta = {};
  for (const line of match[1].split(/\r?\n/)) {
    const idx = line.indexOf(":");
    if (idx === -1) continue;
    const key = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).trim().replace(/^["']|["']$/g, "");
    if (key) meta[key] = value;
  }
  return { meta, body: match[2] };
}

// Split a family's markdown into { intro, byId } on `## <id>` headings.
function splitSections(body) {
  const parts = body.split(/^##[ \t]+(?=\S)/m);
  const intro = parts.shift() || "";
  const byId = {};
  for (const part of parts) {
    const nl = part.indexOf("\n");
    const id = (nl === -1 ? part : part.slice(0, nl)).trim();
    byId[id] = (nl === -1 ? "" : part.slice(nl + 1)).trim();
  }
  return { intro: intro.trim(), byId };
}

const prose = {};
for (const [path, raw] of Object.entries(files)) {
  const { meta, body } = parseFrontmatter(raw);
  const id = meta.family || path.split("/").pop().replace(/\.md$/, "");
  prose[id] = { meta, ...splitSections(body) };
}

// Families in catalogue order, each entry merged with its prose (if written).
export const families = catalogue.families.map((f) => {
  const p = prose[f.id] || { meta: {}, intro: "", byId: {} };
  return {
    ...f,
    title: p.meta.title || f.title,
    description: p.meta.description || f.blurb,
    intro: p.intro,
    documented: Object.keys(p.byId).length,
    entries: f.entries.map((e) => ({ ...e, prose: p.byId[e.id] || "" })),
  };
});

export const modifiers = catalogue.modifiers;
export const totalEntries = catalogue.total;

export function getFamily(id) {
  return families.find((f) => f.id === id) || null;
}

// Find one entry by id across every family — used by the contextual "?" links.
export function getEntry(id) {
  for (const f of families) {
    const e = f.entries.find((x) => x.id === id);
    if (e) return { ...e, family: f };
  }
  return null;
}

export function renderMarkdown(body) {
  return marked.parse(body || "", { breaks: false, gfm: true });
}

// "0 < α" / "0 < β" style bound summary for a parameter.
export function boundsLabel(p) {
  const lo = p.min === null || p.min === undefined ? null : p.min;
  const hi = p.max === null || p.max === undefined ? null : p.max;
  if (lo === null && hi === null) return "any real value";
  if (hi === null) return `> ${lo}`;
  if (lo === null) return `< ${hi}`;
  return `${lo} – ${hi}`;
}

export function supportLabel(s) {
  if (!s) return null;
  const lo = s.min === null || s.min === undefined ? "−∞" : s.min;
  const hi = s.max === null || s.max === undefined ? "∞" : s.max;
  return `${lo} to ${hi}`;
}
