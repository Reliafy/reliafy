// Prerender the marketing pages into static HTML for search engines.
//
// Run AFTER `vite build` (which produces dist/) and the SSR bundle build:
//   vite build --config vite.ssr.config.js   -> dist-ssr/prerender-entry.js
//   node scripts/prerender.mjs               -> dist/static/<route>/index.html
//                                               dist/sitemap.xml, dist/robots.txt
//
// The backend serves dist/static/<route>/index.html for those routes (full
// content + per-page meta), while every other route still gets the SPA shell.
// React re-renders into #root on load, so pages stay fully interactive.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");
const entry = pathToFileURL(join(root, "dist-ssr", "prerender-entry.js")).href;

const { render, routes, feeds, SITE } = await import(entry);

const template = readFileSync(join(dist, "index.html"), "utf8");
const escape = (s) =>
  String(s).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;");

let count = 0;
for (const route of routes()) {
  const html = render(route.path);
  const canonical = SITE + (route.path === "/" ? "/" : route.path);
  const head = [
    `<title>${escape(route.title)}</title>`,
    `<meta name="description" content="${escape(route.description)}" />`,
    `<link rel="canonical" href="${canonical}" />`,
    `<meta property="og:title" content="${escape(route.title)}" />`,
    `<meta property="og:description" content="${escape(route.description)}" />`,
    `<meta property="og:url" content="${canonical}" />`,
    `<meta property="og:type" content="website" />`,
    `<meta property="og:site_name" content="Reliafy" />`,
    // Per-route social card (blog posts set route.image) with the site-wide
    // card as the fallback — otherwise every LinkedIn preview looks identical.
    `<meta property="og:image" content="${SITE}${route.image || "/og-card.png"}" />`,
    `<meta property="og:image:width" content="1200" />`,
    `<meta property="og:image:height" content="630" />`,
    `<meta name="twitter:card" content="summary_large_image" />`,
    `<meta name="twitter:title" content="${escape(route.title)}" />`,
    `<meta name="twitter:description" content="${escape(route.description)}" />`,
    `<meta name="twitter:image" content="${SITE}${route.image || "/og-card.png"}" />`,
    // Feed autodiscovery (feed readers, Zapier/Buffer "find feed" helpers).
    `<link rel="alternate" type="application/rss+xml" title="Reliafy — What's new" href="${SITE}/whats-new/feed.xml" />`,
    `<link rel="alternate" type="application/rss+xml" title="Reliafy blog" href="${SITE}/blog/feed.xml" />`,
    // Structured data (SoftwareApplication on product pages, Article/FAQPage
    // on learn pages) — what featured snippets and AI overviews lift.
    ...(route.jsonld || []).map(
      (obj) =>
        `<script type="application/ld+json">${JSON.stringify(obj).replaceAll("</", "<\\/")}</script>`
    ),
  ].join("\n    ");

  let page = template
    // Replace the shell <title> with the per-page head block.
    .replace(/<title>[\s\S]*?<\/title>/, head)
    .replace('<div id="root"></div>', `<div id="root">${html}</div>`);

  const outDir = join(dist, "static", route.path === "/" ? "." : route.path.slice(1));
  mkdirSync(outDir, { recursive: true });
  writeFileSync(join(outDir, "index.html"), page);
  count += 1;
}

// sitemap.xml + robots.txt
const urls = routes()
  .map((r) => {
    const loc = SITE + (r.path === "/" ? "/" : r.path);
    const lastmod = r.lastmod ? `\n    <lastmod>${r.lastmod}</lastmod>` : "";
    return `  <url>\n    <loc>${loc}</loc>${lastmod}\n  </url>`;
  })
  .join("\n");
writeFileSync(
  join(dist, "sitemap.xml"),
  `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`
);
writeFileSync(
  join(dist, "robots.txt"),
  `User-agent: *\nAllow: /\n\nSitemap: ${SITE}/sitemap.xml\n`
);

// RSS 2.0 feeds (What's new + blog). pubDate is RFC 822 at 00:00 UTC of the
// item's date; guid is the permalink so readers/Zapier dedupe on the URL.
const xml = (s) =>
  String(s ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
const rfc822 = (iso) => (iso ? new Date(`${iso}T00:00:00Z`).toUTCString() : "");
let feedCount = 0;
for (const f of feeds()) {
  const items = f.items
    .map((it) => [
      "    <item>",
      `      <title>${xml(it.title)}</title>`,
      `      <link>${xml(it.link)}</link>`,
      `      <guid isPermaLink="true">${xml(it.guid)}</guid>`,
      it.date ? `      <pubDate>${rfc822(it.date)}</pubDate>` : null,
      `      <description>${xml(it.summary)}</description>`,
      "    </item>",
    ].filter(Boolean).join("\n"))
    .join("\n");
  const newest = f.items[0]?.date;
  const body = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
    "  <channel>",
    `    <title>${xml(f.title)}</title>`,
    `    <link>${xml(f.link)}</link>`,
    `    <description>${xml(f.description)}</description>`,
    "    <language>en</language>",
    `    <atom:link href="${SITE}${f.path}" rel="self" type="application/rss+xml" />`,
    newest ? `    <lastBuildDate>${rfc822(newest)}</lastBuildDate>` : null,
    items || null,
    "  </channel>",
    "</rss>",
    "",
  ].filter((l) => l !== null).join("\n");
  const out = join(dist, f.path.slice(1));
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, body);
  feedCount += 1;
}

console.log(`prerendered ${count} pages + sitemap.xml + robots.txt + ${feedCount} RSS feeds`);
