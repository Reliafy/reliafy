// Run with: node --test src/basisMarkdown.test.js
import { test } from "node:test";
import assert from "node:assert/strict";
import { BASIS_ATTRS, BASIS_PURIFY, BASIS_TAGS, BASIS_URI, openLinksApart, plainFirstLine, renderBasisMarkdown } from "./basisMarkdown.js";

// A stand-in for DOMPurify (Node has no DOM): it hands back what it was given
// and keeps the options, so the markup marked makes and the allow-lists can be checked.
const seen = [];
const purify = { isSupported: true, sanitize: (html, options) => { seen.push(options); return html; } };

test("raw HTML in the text is dropped before it is cleaned", () => {
  const out = renderBasisMarkdown("Before <script>alert(1)</script> <img src=x onerror=alert(1)> after\n\n<style>p{}</style>", purify);
  assert.ok(!/<script|<img|<style|onerror/i.test(out), out);
  assert.match(out, /Before/);
  assert.match(out, /after/);
});

test("images keep only their words, and links only http, https and mailto survive", () => {
  const out = renderBasisMarkdown("![a chart](https://x.test/c.png) [bad](javascript:alert(1)) [ok](https://reliafy.com) [mail](mailto:a@b.test)", purify);
  assert.ok(!/<img/.test(out));
  assert.ok(!/javascript:/i.test(out));
  assert.match(out, /a chart/);
  assert.match(out, /<a href="https:\/\/reliafy\.com">ok<\/a>/);
  assert.match(out, /href="mailto:a@b\.test"/);
});

test("headings, lists, tables, code and line breaks render", () => {
  const out = renderBasisMarkdown("## Demand\n\n- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```\n150 g ÷ 35,000 L\n```\n\nline one\nline two", purify);
  for (const tag of ["<h2", "<ul>", "<li>", "<table>", "<th>", "<pre>", "<code>", "<br>"]) assert.ok(out.includes(tag), tag);
});

test("the cleaner is given a short allow-list with no images, styles or data attributes", () => {
  renderBasisMarkdown("x", purify);
  assert.equal(seen.at(-1), BASIS_PURIFY);
  for (const bad of ["img", "script", "style", "svg", "iframe", "form", "input", "math", "video"]) assert.ok(!BASIS_TAGS.includes(bad), bad);
  assert.ok(!BASIS_ATTRS.some((a) => /^on|style|src/.test(a)));
  assert.equal(BASIS_PURIFY.ALLOW_DATA_ATTR, false);
  assert.equal(BASIS_PURIFY.ALLOWED_URI_REGEXP, BASIS_URI);
  assert.ok(!BASIS_URI.test("javascript:alert(1)") && !BASIS_URI.test("data:text/html,x") && BASIS_URI.test("HTTPS://a.test"));
});

test("with no DOM (so no cleaner) nothing is rendered, and empty text gives nothing", () => {
  assert.equal(renderBasisMarkdown("# Hi"), "");
  assert.equal(renderBasisMarkdown("   ", purify), "");
  assert.equal(renderBasisMarkdown(undefined, purify), "");
});

test("the first line, plain", () => {
  assert.equal(plainFirstLine("\n## Chlorine **demand**\n\nmore"), "Chlorine demand");
  assert.equal(plainFirstLine("```\ncode\n```\n[a link](https://x.test) here"), "code");
  assert.equal(plainFirstLine("x".repeat(100), 10), "xxxxxxxxx…");
  assert.equal(plainFirstLine(""), "");
});

test("every surviving link opens apart and passes nothing on", () => {
  const set = {};
  const link = { tagName: "A", hasAttribute: (n) => n === "href", setAttribute: (k, v) => { set[k] = v; } };
  openLinksApart(link);
  assert.deepEqual(set, { target: "_blank", rel: "noopener noreferrer nofollow" });
  const bare = { tagName: "A", hasAttribute: () => false, setAttribute: () => assert.fail("no href, nothing set") };
  openLinksApart(bare);
  openLinksApart({ tagName: "P", hasAttribute: () => true, setAttribute: () => assert.fail("only links") });
});
