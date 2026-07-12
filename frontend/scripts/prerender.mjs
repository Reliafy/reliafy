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

const { render, routes, SITE } = await import(entry);

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

console.log(`prerendered ${count} pages + sitemap.xml + robots.txt`);
