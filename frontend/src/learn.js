// Learn content layer — evergreen practitioner articles under content/learn/.
// Same build-time inlining as the blog (import.meta.glob, no backend), but
// these are pages, not dated posts: no publish gating, and each one ends with
// a single contextual CTA to the product page it supports.
//
// Frontmatter fields: title, description (meta description), slug (optional),
// cta_text, cta_label, cta_href. A trailing `## Frequently asked questions`
// section with `### question` subheadings is extracted into FAQPage JSON-LD
// at prerender time (the visible content is the same markdown).
import { marked } from "marked";

const files = import.meta.glob("./content/learn/*.md", {
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

// Pull `### question` / answer pairs out of the FAQ section for JSON-LD.
function faqOf(body) {
  const m = /^##\s+Frequently asked questions\s*$/im.exec(body);
  if (!m) return [];
  const section = body.slice(m.index + m[0].length).split(/^##\s/m)[0];
  const pairs = [];
  const parts = section.split(/^###\s+/m).slice(1);
  for (const part of parts) {
    const nl = part.indexOf("\n");
    if (nl === -1) continue;
    const q = part.slice(0, nl).trim();
    const a = part.slice(nl).trim();
    if (q && a) pairs.push({ q, a });
  }
  return pairs;
}

export const articles = Object.entries(files)
  .map(([path, raw]) => {
    const { meta, body } = parseFrontmatter(raw);
    const name = path.split("/").pop().replace(/\.md$/, "");
    return {
      slug: meta.slug || name,
      title: meta.title || "Untitled",
      description: meta.description || "",
      // Index position: lower first (pillar guides on top), default 50.
      order: Number(meta.order) || 50,
      readingMinutes: readingTime(body),
      cta: meta.cta_href
        ? { text: meta.cta_text || "", label: meta.cta_label || "Learn more", href: meta.cta_href }
        : null,
      faq: faqOf(body),
      body,
    };
  })
  .sort((a, b) => a.order - b.order || a.title.localeCompare(b.title));

export function getArticle(slug) {
  return articles.find((a) => a.slug === slug) || null;
}

export function renderMarkdown(body) {
  return marked.parse(body, { breaks: false, gfm: true });
}
