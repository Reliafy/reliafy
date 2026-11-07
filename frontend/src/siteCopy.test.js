import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ABOUT, HERO, HOME_DESCRIPTION, HOME_TITLE, homeJsonLd } from "./siteCopy.js";

const shell = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const unescape = (s) => s.replaceAll("&quot;", '"').replaceAll("&lt;", "<").replaceAll("&amp;", "&");

test("the home title and description fit a search result", () => {
  assert.ok(HOME_TITLE.length <= 60, `title is ${HOME_TITLE.length} characters`);
  assert.ok(HOME_DESCRIPTION.length <= 155, `description is ${HOME_DESCRIPTION.length} characters`);
});

test("the positioning leads with the product, not the price", () => {
  for (const text of [HOME_TITLE, HOME_DESCRIPTION, HERO.eyebrow, HERO.h1, HERO.lede, ABOUT]) {
    assert.doesNotMatch(text, /\bfree\b/i, text);
  }
});

test("the description keeps the terms people search for", () => {
  for (const term of ["Weibull", "life data", "RBD", "RCM"]) {
    assert.ok(HOME_DESCRIPTION.includes(term), term);
  }
});

test("the app shell's default head matches siteCopy", () => {
  const block = shell.match(/<!-- head-meta[\s\S]*?<!-- \/head-meta -->/);
  assert.ok(block, "index.html has the head-meta block prerender.mjs replaces");
  const title = block[0].match(/<title>([^<]*)<\/title>/)[1];
  const description = block[0].match(/<meta name="description" content="([^"]*)"/)[1];
  assert.equal(unescape(title), HOME_TITLE);
  assert.equal(unescape(description), HOME_DESCRIPTION);
});

test("the home structured data describes Reliafy and keeps both plans", () => {
  const [org, app] = homeJsonLd();
  assert.equal(org["@type"], "Organization");
  assert.equal(app["@type"], "SoftwareApplication");
  assert.deepEqual(app.offers.map((o) => o.price), ["0", "19"]);
});
