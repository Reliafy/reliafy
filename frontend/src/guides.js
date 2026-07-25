// Product Guides — task-oriented, screenshot-driven "how do I…" walkthroughs.
// Distinct from the Learn layer (learn.js): Learn is evergreen SEO/concept
// content; Guides show exactly how to do one thing in Reliafy, step by step,
// with a screenshot per step. Same build-time markdown inlining, no backend.
//
// Frontmatter: title, task (one-line "how do I…"), category (index grouping),
// minutes, prerequisites (optional), related_href/related_label (optional
// deep link to the feature), order. Screenshots live in /guides/img/ and are
// referenced from the markdown; they're produced by the capture harness
// (scripts/capture-guides.mjs) so they stay in sync with the UI.
import { marked } from "marked";

const files = import.meta.glob("./content/guides/*.md", {
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

function readingTime(body) {
  const words = body.trim().split(/\s+/).filter(Boolean).length;
  return Math.max(1, Math.round(words / 200));
}

export const guides = Object.entries(files)
  .map(([path, raw]) => {
    const { meta, body } = parseFrontmatter(raw);
    const name = path.split("/").pop().replace(/\.md$/, "");
    return {
      slug: meta.slug || name,
      title: meta.title || "Untitled",
      task: meta.task || "",
      category: meta.category || "General",
      minutes: Number(meta.minutes) || readingTime(body),
      prerequisites: meta.prerequisites || "",
      related: meta.related_href
        ? { href: meta.related_href, label: meta.related_label || "Open in Reliafy" }
        : null,
      order: Number(meta.order) || 50,
      body,
    };
  })
  .sort((a, b) => a.order - b.order || a.title.localeCompare(b.title));

// Guides grouped by category, preserving order.
export function guidesByCategory() {
  const groups = [];
  const index = new Map();
  for (const g of guides) {
    if (!index.has(g.category)) {
      index.set(g.category, { category: g.category, items: [] });
      groups.push(index.get(g.category));
    }
    index.get(g.category).items.push(g);
  }
  return groups;
}

export function getGuide(slug) {
  return guides.find((g) => g.slug === slug) || null;
}

export function renderMarkdown(body) {
  return marked.parse(body, { breaks: false, gfm: true });
}
