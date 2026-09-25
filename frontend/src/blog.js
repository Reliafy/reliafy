// Blog content layer. Posts are plain Markdown files under content/blog/ with a
// small YAML-ish frontmatter block; Vite inlines them at build time via
// import.meta.glob, so there's no backend, database, or runtime fetch involved.
// Adding a post = committing a .md file.
import { marked } from "marked";

const files = import.meta.glob("./content/blog/*.md", {
  query: "?raw",
  import: "default",
  eager: true,
});

// Minimal frontmatter parser: a leading `--- ... ---` block of `key: value`
// lines (values may be quoted). Enough for our fixed set of fields; we control
// the files, so we don't need a full YAML engine.
export function parseFrontmatter(raw) {
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

// URL slug from the filename, dropping any leading YYYY-MM-DD- / YYYY-MM- date.
export function slugFromPath(path) {
  const name = path.split("/").pop().replace(/\.md$/, "");
  return name.replace(/^\d{4}-\d{2}(-\d{2})?-/, "");
}

function readingTime(body) {
  const words = body.trim().split(/\s+/).filter(Boolean).length;
  return Math.max(1, Math.round(words / 200));
}

// Posts dated in the future are queued, not published: they're invisible in
// the list and 404 by direct URL until their date arrives. Write a batch,
// date them out, deploy once — the blog releases them on schedule. (UTC-date
// comparison; prerender excludes them from static HTML and the sitemap too,
// so SEO for a post starts at the first deploy after its date.)
export const TODAY = new Date().toISOString().slice(0, 10);

// Every item, including future-dated ones — the server's RSS route filters
// by date at request time (scripts/prerender.mjs writes these to feeds.json).
export const allPosts = Object.entries(files)
  .map(([path, raw]) => {
    const { meta, body } = parseFrontmatter(raw);
    return {
      slug: meta.slug || slugFromPath(path),
      title: meta.title || "Untitled",
      date: meta.date || "",
      author: meta.author || "",
      summary: meta.summary || "",
      // Optional per-post social card (og:image), e.g. /blog/my-post-card.png
      // under public/. Absent -> the site-wide /og-card.png.
      image: meta.image || "",
      readingMinutes: readingTime(body),
      body,
    };
  })
  // Newest first (ISO dates sort lexically).
  .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));

export const posts = allPosts.filter((p) => !p.date || p.date <= TODAY);

export function getPost(slug) {
  return posts.find((p) => p.slug === slug) || null;
}

// Render a post body to HTML. Content is authored by us (trusted repo files),
// so the output is rendered as-is.
export function renderMarkdown(body) {
  return marked.parse(body, { breaks: false, gfm: true });
}

export function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}
