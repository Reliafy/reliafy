// The LinkedIn feed (#367): everything meant for the Reliafy LinkedIn page, as
// one RSS feed the Zapier → LinkedIn Zap watches (/social/feed.xml).
//
// * Short posts: content/social/YYYY-MM-DD-<slug>.md — frontmatter `date`,
//   optional `link` (a Reliafy URL or a site path) and `image`; the body is
//   the exact post text. They exist only in this feed, never on the website.
// * An announcement of every blog post and What's new update, on its own
//   date. Its text is the post's `linkedin:` frontmatter, or else its title
//   and summary.
//
// scripts/prerender.mjs writes the feed, future items included, to
// dist/feeds.json; backend/routers/feeds.py serves it date-filtered per
// request and adds the UTM tags (utm_source=linkedin&utm_medium=social&
// utm_campaign=<slug>) to each link. Pure: no import.meta.glob, so
// `node --test` covers it.
import { parseFrontmatter } from "./frontmatter.js";

export const SITE = "https://reliafy.com";

// Announcements start here. Earlier posts were already on LinkedIn through
// the What's new feed, so the switch to this feed must not post them again.
export const LINKEDIN_START = "2026-10-12";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const OWN_HOSTS = new Set(["reliafy.com", "www.reliafy.com"]);

// `value` as an absolute Reliafy URL, or an Error naming `what`.
export function siteUrl(value, what, site = SITE) {
  const v = String(value || "").trim();
  if (v.startsWith("/") && !v.startsWith("//")) return site + v;
  let url;
  try {
    url = new URL(v);
  } catch {
    throw new Error(`${what}: "${v}" is not a Reliafy URL or a site path like /blog/<slug>`);
  }
  if (url.protocol !== "https:" || !OWN_HOSTS.has(url.hostname)) {
    throw new Error(`${what}: "${v}" is not a Reliafy URL (https://reliafy.com/...)`);
  }
  return url.href;
}

// One short post from its file. Throws on anything the feed can't use, so a
// bad file fails the test suite and the build rather than posting badly.
export function socialPost(path, raw, site = SITE) {
  const id = path.split("/").pop().replace(/\.md$/, "");
  const m = /^(\d{4}-\d{2}-\d{2})-([a-z0-9][a-z0-9-]*)$/.exec(id);
  if (!m) throw new Error(`${path}: name short posts YYYY-MM-DD-<slug>.md (lower-case slug)`);
  const { meta, body } = parseFrontmatter(raw);
  const date = String(meta.date || "").trim();
  if (!ISO_DATE.test(date)) throw new Error(`${path}: frontmatter needs date: YYYY-MM-DD`);
  if (date !== m[1]) throw new Error(`${path}: frontmatter date ${date} differs from the filename's ${m[1]}`);
  const text = body.trim();
  if (!text) throw new Error(`${path}: the body (the post text) is empty`);
  return {
    id,
    slug: m[2],
    date,
    link: meta.link ? siteUrl(meta.link, `${path} link`, site) : "",
    image: meta.image ? siteUrl(meta.image, `${path} image`, site) : "",
    text,
  };
}

// A feed item's title: the post's first line, short.
function firstLine(text, max = 100) {
  const line = String(text).trim().split(/\r?\n/)[0].trim();
  return line.length > max ? `${line.slice(0, max - 1).trimEnd()}…` : line;
}

// The announcement text for a blog post or update.
export function announcementText(post) {
  if (post.linkedin && post.linkedin.trim()) return post.linkedin.trim();
  return [post.title, post.summary].filter((s) => s && s.trim()).join("\n\n");
}

// The /social/feed.xml definition for feeds.json. `posts` and `updates` are
// the blog.js / updates.js items (future-dated included); `social` the parsed
// short posts. A short post linking to a blog post or update is held until
// that page is live (`hold_until`), so LinkedIn never links to a 404.
export function linkedinFeed({ posts = [], updates = [], social = [], site = SITE, start = LINKEDIN_START }) {
  const pageDates = new Map();
  for (const p of posts) pageDates.set(`${site}/blog/${p.slug}`, p.date);
  for (const u of updates) pageDates.set(`${site}/whats-new/${u.slug}`, u.date);

  const items = [];
  for (const s of social) {
    const target = s.link ? s.link.split(/[?#]/)[0].replace(/\/$/, "") : "";
    const linked = pageDates.get(target) || "";
    items.push({
      kind: "short",
      title: firstLine(s.text),
      link: s.link || "",
      guid: `${site}/social/${s.id}`,
      permalink: false,
      date: s.date,
      hold_until: linked > s.date ? linked : "",
      summary: s.text,
      campaign: s.slug,
      image: s.image || "",
    });
  }
  const announce = (base, kind) => (p) => {
    if (!p.date || p.date < start) return;
    items.push({
      kind,
      title: p.title,
      link: `${site}${base}/${p.slug}`,
      // Distinct from the page's own URL (the blog / What's new feeds' guid)
      // and from any short post linking to it.
      guid: `${site}${base}/${p.slug}#linkedin`,
      permalink: false,
      date: p.date,
      hold_until: "",
      summary: announcementText(p),
      campaign: p.slug,
      image: p.image ? siteUrl(p.image, `${base}/${p.slug} image`, site) : "",
    });
  };
  posts.forEach(announce("/blog", "blog"));
  updates.forEach(announce("/whats-new", "whats-new"));

  const seen = new Set();
  for (const it of items) {
    if (seen.has(it.guid)) throw new Error(`LinkedIn feed: two items share the guid ${it.guid}`);
    seen.add(it.guid);
  }
  items.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : a.guid < b.guid ? -1 : 1));
  return {
    path: "/social/feed.xml",
    title: "Reliafy on LinkedIn",
    link: site,
    description: "Posts for the Reliafy LinkedIn page: short posts, new articles and What's new.",
    utm: { source: "linkedin", medium: "social" },
    items,
  };
}
