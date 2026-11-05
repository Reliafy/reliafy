import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  API_DOCS_PAGES, apiDocsNeighbours, apiDocsPage, apiDocsPath, legacyApiDocsTarget,
} from "./apiDocsPages.js";

const src = (file) => readFileSync(new URL(`./${file}`, import.meta.url), "utf8");

test("paths", () => {
  assert.equal(apiDocsPath(""), "/api-docs");
  assert.equal(apiDocsPath("cli"), "/api-docs/cli");
  assert.equal(apiDocsPage("nope").slug, "");
  assert.equal(apiDocsPage("tools").label, "Tools API");
});

test("previous and next", () => {
  assert.deepEqual(
    [apiDocsNeighbours("").prev, apiDocsNeighbours("").next.slug],
    [null, "authentication"],
  );
  const last = API_DOCS_PAGES[API_DOCS_PAGES.length - 1].slug;
  assert.equal(apiDocsNeighbours(last).next, null);
  assert.equal(apiDocsNeighbours("cli").prev.slug, "examples");
});

test("old anchors go to their page", () => {
  assert.equal(legacyApiDocsTarget("#mcp"), "/api-docs/mcp");
  assert.equal(legacyApiDocsTarget("cli"), "/api-docs/cli");
  assert.equal(legacyApiDocsTarget("#tool-list"), "/api-docs/tools#tool-list");
  assert.equal(legacyApiDocsTarget("#getting-started"), "/api-docs/authentication");
  assert.equal(legacyApiDocsTarget(""), null);
  assert.equal(legacyApiDocsTarget("#constructor"), null);
});

test("every page has a route in each router and the prerender", () => {
  for (const file of ["App.jsx", "AppShell.jsx", "prerender-entry.jsx"]) {
    const text = src(file);
    for (const p of API_DOCS_PAGES) {
      assert.ok(text.includes(`path="${apiDocsPath(p.slug)}"`), `${file} has no route for ${apiDocsPath(p.slug)}`);
    }
  }
});

test("titles and descriptions are filled and distinct", () => {
  const titles = new Set(API_DOCS_PAGES.map((p) => p.title));
  assert.equal(titles.size, API_DOCS_PAGES.length);
  for (const p of API_DOCS_PAGES) {
    assert.ok(p.description.length > 60 && p.description.length < 260, p.slug);
    assert.ok(!/maint\b/i.test(p.description), p.slug);
  }
});
