// "What's new" content layer — product updates, mirroring the blog exactly.
// Each update is a Markdown file under content/updates/ with frontmatter
// (title, date, summary, optional email_subject). Vite inlines them at build
// time; adding an update = committing a .md file. The same file is the source
// for the monthly product-update email (email_subject overrides its subject).
import { parseFrontmatter, slugFromPath, TODAY } from "./blog.js";

export { renderMarkdown, formatDate } from "./blog.js";

const files = import.meta.glob("./content/updates/*.md", {
  query: "?raw",
  import: "default",
  eager: true,
});

// Same date gate as the blog: future-dated updates are queued — hidden from
// the list, 404 by direct URL, and absent from prerendered HTML and the
// sitemap until the first build on or after their (UTC) date.
export const updates = Object.entries(files)
  .map(([path, raw]) => {
    const { meta, body } = parseFrontmatter(raw);
    return {
      slug: meta.slug || slugFromPath(path),
      title: meta.title || "Untitled",
      date: meta.date || "",
      summary: meta.summary || "",
      emailSubject: meta.email_subject || "",
      body,
    };
  })
  .filter((u) => !u.date || u.date <= TODAY)
  // Newest first (ISO dates sort lexically).
  .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));

export function getUpdate(slug) {
  return updates.find((u) => u.slug === slug) || null;
}
