// Checks on the how-to guides (content/guides/*.md), so they can't silently
// fall behind the app:
//
// 1. Dead links: every internal link in a guide (its body, its images and its
//    related_href) goes to a route the router knows (App.jsx, AppShell.jsx,
//    product pages; redirects count), or to a guide, Learn article, blog post,
//    reference family or What's new post that exists and is published. An
//    anchor (#section) must exist on the page it points at. Menu paths written
//    in prose ("Strategy → Test planning") aren't checked.
// 2. Coverage: every main feature page in GUIDE_COVERAGE (guideCoverage.js)
//    is linked from at least one guide.
import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { parseFrontmatter, slugFromPath } from "./frontmatter.js";
import { appRoutes, publicRoutes } from "../smoke/routes.js";
import { API_DOCS_PAGES, legacyApiDocsTarget } from "./apiDocsPages.js";
import { GUIDE_COVERAGE } from "./guideCoverage.js";

const SRC = new URL("./", import.meta.url);
const read = (rel) => readFileSync(new URL(rel, SRC), "utf8");
const mdFiles = (dir) => readdirSync(new URL(`content/${dir}/`, SRC)).filter((f) => f.endsWith(".md"));
const TODAY = new Date().toISOString().slice(0, 10);

// ---- The guides and their links ----------------------------------------------

const GUIDES = mdFiles("guides").map((file) => {
  const { meta, body } = parseFrontmatter(read(`content/guides/${file}`));
  return { file, slug: meta.slug || file.replace(/\.md$/, ""), meta, body, hidden: meta.hidden === "true" };
});

// Every link in a markdown body: inline links and images (the text may run
// over several lines), and raw <a href> / <img src>. Code is skipped.
export function linksIn(body) {
  const text = String(body || "")
    .replace(/```[\s\S]*?```/g, "")
    .replace(/`[^`\n]*`/g, "");
  const out = [];
  for (const m of text.matchAll(/(!?)\[(?:[^\]]|\n)*?\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)/g)) {
    out.push({ href: m[2], image: m[1] === "!" });
  }
  for (const m of text.matchAll(/<(a|img)\b[^>]*?\b(?:href|src)\s*=\s*"([^"]+)"/gi)) {
    out.push({ href: m[2], image: m[1].toLowerCase() === "img" });
  }
  return out;
}

const isInternal = (href) => href.startsWith("/") && !href.startsWith("//");

function guideLinks(g) {
  const links = linksIn(g.body).filter((l) => isInternal(l.href));
  if (g.meta.related_href) links.push({ href: g.meta.related_href, related: true });
  return links;
}

// ---- What the site has --------------------------------------------------------

const ROUTES = [...appRoutes(), ...publicRoutes()];
const routePattern = (path) =>
  new RegExp(`^${path.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\/:\w+/g, "/[^/]+")}/?$`);
const ROUTE_RES = ROUTES.map((r) => ({ ...r, re: routePattern(r.path) }));

// Content collections whose detail route takes a slug: the slugs that exist
// (and, for dated posts, are published by today).
const datedSlugs = (dir) =>
  new Map(mdFiles(dir).map((f) => {
    const { meta } = parseFrontmatter(read(`content/${dir}/${f}`));
    return [meta.slug || slugFromPath(f), { date: meta.date || "", raw: read(`content/${dir}/${f}`) }];
  }));
const COLLECTIONS = {
  guides: new Map(GUIDES.filter((g) => !g.hidden).map((g) => [g.slug, { date: "", raw: g.body }])),
  learn: new Map(mdFiles("learn").map((f) => {
    const raw = read(`content/learn/${f}`);
    return [parseFrontmatter(raw).meta.slug || f.replace(/\.md$/, ""), { date: "", raw }];
  })),
  blog: datedSlugs("blog"),
  "whats-new": datedSlugs("updates"),
  reference: new Map(JSON.parse(read("content/reference/catalogue.json")).families.map((f) => [f.id, { date: "", raw: "" }])),
};

// The ids on each API docs page: the page's component in ApiReference.jsx
// (PageBody maps a slug to it) and the id="..." attributes inside it.
function apiDocsIds() {
  const src = read("components/ApiReference.jsx");
  const component = {};
  for (const m of src.matchAll(/case "([\w-]+)": return <(\w+)/g)) component[m[1]] = m[2];
  const fallback = /default: return <(\w+)/.exec(src)?.[1];
  const ids = {};
  for (const page of API_DOCS_PAGES) {
    const name = component[page.slug] || fallback;
    const start = src.search(new RegExp(`^function ${name}\\b`, "m"));
    const rest = src.slice(start + 1);
    const end = rest.search(/^(function |const |export |\/\/ ----)/m);
    const body = rest.slice(0, end === -1 ? undefined : end);
    ids[page.slug] = new Set([...body.matchAll(/\bid="([\w-]+)"/g)].map((m) => m[1]));
  }
  return ids;
}
const API_IDS = apiDocsIds();

// Why a link is dead, or null when it resolves.
export function deadReason(href) {
  const url = new URL(href, "https://reliafy.test");
  const path = url.pathname.replace(/\/+$/, "") || "/";
  const anchor = decodeURIComponent(url.hash.replace(/^#/, ""));

  if (path.startsWith("/guides/img/")) {
    return existsSync(new URL(`../public${path}`, SRC)) ? null : `no image at public${path}`;
  }

  // Content: /guides/<slug>, /learn/<slug>, /blog/<slug>, ...
  const content = /^\/(guides|learn|blog|whats-new|reference)\/([^/]+)$/.exec(path);
  if (content) {
    const item = COLLECTIONS[content[1]].get(content[2]);
    if (!item) return `no ${content[1]} page "${content[2]}"`;
    if (item.date && item.date > TODAY) return `${content[1]} post "${content[2]}" isn't published until ${item.date}`;
    if (anchor && !item.raw.includes(`id="${anchor}"`)) return `no #${anchor} on ${path} (headings get no ids)`;
    return null;
  }

  const route = ROUTE_RES.find((r) => r.re.test(path));
  if (!route) return `no route for ${path}`;
  if (route.flag === "maintenance") return `${path} is a Maintenance page: Maintenance is operators-only, so guides don't link to it`;

  if (anchor) {
    if (path === "/api-docs") {
      if (legacyApiDocsTarget(anchor) || API_IDS[""].has(anchor)) return null;
      return `no #${anchor} on /api-docs`;
    }
    const api = /^\/api-docs\/([\w-]+)$/.exec(path);
    if (api) return API_IDS[api[1]]?.has(anchor) ? null : `no #${anchor} on ${path}`;
    return `can't check #${anchor} on ${path}: link to the page without an anchor`;
  }
  return null;
}

// ---- The checks --------------------------------------------------------------

test("guides: the link finder sees inline, multi-line, image and HTML links", () => {
  const body = "See [the\nguide](/guides/x) and ![shot](/guides/img/a.png \"t\").\n"
    + "`[not](/code)`\n```\n[nor](/block)\n```\n<a href=\"/rbds\">RBDs</a> [web](https://x.test)";
  assert.deepEqual(linksIn(body).map((l) => l.href), ["/guides/x", "/guides/img/a.png", "https://x.test", "/rbds"]);
});

test("guides: the dead-link check knows routes, redirects, content and anchors", () => {
  assert.equal(deadReason("/strategy/test-planning/accelerated?model=abc"), null);
  assert.equal(deadReason("/strategy/demonstration-test"), null); // a redirect
  assert.equal(deadReason("/modelling/joint/some-id"), null);
  assert.equal(deadReason("/api-docs/cli"), null);
  assert.equal(deadReason("/api-docs#mcp"), null); // an old anchor, redirected
  assert.equal(deadReason("/api-docs/tools#tool-list"), null);
  assert.match(deadReason("/api-docs/tools#nowhere"), /no #nowhere/);
  assert.match(deadReason("/api-docs#nowhere"), /no #nowhere/);
  assert.match(deadReason("/strategy/no-such-page"), /no route/);
  assert.match(deadReason("/guides/no-such-guide"), /no guides page/);
  assert.match(deadReason("/guides/fit-your-first-model#where-next"), /no #where-next/);
  assert.match(deadReason("/maintenance"), /operators-only/);
  assert.match(deadReason("/guides/img/no-such.png"), /no image/);
});

test("guides: every internal link goes somewhere that exists", () => {
  const dead = [];
  for (const g of GUIDES) {
    for (const l of guideLinks(g)) {
      const why = deadReason(l.href);
      if (why) dead.push(`${g.file}: ${l.related ? "related_href " : ""}${l.href} (${why})`);
    }
  }
  assert.deepEqual(dead, [], `Dead links in the guides:\n  ${dead.join("\n  ")}`);
});

test("guides: the coverage list names pages the router knows", () => {
  const bad = GUIDE_COVERAGE.filter((e) => deadReason(e.href)).map((e) => `${e.feature}: ${e.href} (${deadReason(e.href)})`);
  assert.deepEqual(bad, [], `Fix these entries in guideCoverage.js:\n  ${bad.join("\n  ")}`);
});

// A guide link covers an entry when it opens the entry's page or one under
// it (/rbds/b covers /rbds), with at least the entry's query values.
export function covers(entryHref, linkHref) {
  const want = new URL(entryHref, "https://reliafy.test");
  const got = new URL(linkHref, "https://reliafy.test");
  const strip = (p) => p.replace(/\/+$/, "") || "/";
  const page = strip(want.pathname);
  const linked = strip(got.pathname);
  if (linked !== page && !linked.startsWith(`${page === "/" ? "" : page}/`)) return false;
  for (const [k, v] of want.searchParams) if (got.searchParams.get(k) !== v) return false;
  return true;
}

test("guides: a link covers its page, pages under it and a page's mode", () => {
  assert.ok(covers("/rbds", "/rbds/b"));
  assert.ok(covers("/modelling/alt", "/modelling/alt/new"));
  assert.ok(!covers("/modelling/alt", "/modelling/alternative"));
  assert.ok(covers("/strategy/replacement?mode=calendar", "/strategy/replacement?model=x&mode=calendar"));
  assert.ok(!covers("/strategy/replacement?mode=calendar", "/strategy/replacement"));
});

test("guides: every main feature page is linked from a guide", () => {
  const visible = GUIDES.filter((g) => !g.hidden);
  const links = visible.flatMap((g) => guideLinks(g).map((l) => l.href));
  const missing = GUIDE_COVERAGE.filter((e) => !links.some((href) => covers(e.href, href)));
  assert.deepEqual(
    missing.map((e) => `${e.feature} (${e.href})`),
    [],
    "No guide links to these feature pages. Add a guide for each, or update an existing guide to link to it "
      + "(in its text or as its related_href), in frontend/src/content/guides/:\n  "
      + missing.map((e) => `${e.feature}: ${e.href}`).join("\n  "),
  );
});
