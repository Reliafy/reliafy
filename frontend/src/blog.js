// Blog content layer. Posts are plain Markdown files under content/blog/ with a
// small YAML-ish frontmatter block; Vite inlines them at build time via
// import.meta.glob, so there's no backend, database, or runtime fetch involved.
// Adding a post = committing a .md file.
import { marked } from "marked";
// The frontmatter parser and slug rule live in frontmatter.js (pure, so the
// build-time feeds and `node --test` share them); re-exported for the other
// content layers.
import { parseFrontmatter, slugFromPath } from "./frontmatter.js";

export { parseFrontmatter, slugFromPath };

const files = import.meta.glob("./content/blog/*.md", {
  query: "?raw",
  import: "default",
  eager: true,
});

function readingTime(body) {
  const words = body.trim().split(/\s+/).filter(Boolean).length;
  return Math.max(1, Math.round(words / 200));
}

// Posts dated in the future are queued, not published: they're invisible in
// the list and 404 by direct URL until their date arrives. Write a batch,
// date them out, deploy once — the blog releases them on schedule. (UTC-date
// comparison: 00:00 UTC is 10:00 in Brisbane.) The prerender renders queued
// posts too, and the server holds each page — and its sitemap entry — back
// until its date (backend/services/content_gate.py), so search engines can
// read a post on its day with no rebuild.
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
      // Optional exact LinkedIn announcement text (a `linkedin: |` block); the
      // LinkedIn feed falls back to title + summary. Never shown on the site.
      linkedin: meta.linkedin || "",
      // Optional calendar type (technical, commentary or tutorial) for the
      // admin page's publishing calendar; absent, it takes its slot's.
      type: meta.type || "",
      readingMinutes: readingTime(body),
      body,
    };
  })
  // Newest first (ISO dates sort lexically).
  .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));

export const posts = allPosts.filter((p) => !p.date || p.date <= TODAY);

// `includeFuture` is for the build-time prerender only (see above).
export function getPost(slug, { includeFuture = false } = {}) {
  return (includeFuture ? allPosts : posts).find((p) => p.slug === slug) || null;
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
