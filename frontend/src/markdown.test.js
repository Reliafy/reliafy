// Run with: node --test src/markdown.test.js
import { test } from "node:test";
import assert from "node:assert/strict";
import { marked } from "marked";
import { renderMarkdown } from "./markdown.js";

const BODY = "## Heading\n\nSome *text* with a [link](https://reliafy.com) and `code`.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n";

test("with a DOM, the HTML goes through the sanitizer with the HTML profile", () => {
  const calls = [];
  const purify = {
    isSupported: true,
    sanitize: (html, options) => {
      calls.push([html, options]);
      return "clean";
    },
  };
  assert.equal(renderMarkdown(BODY, purify), "clean");
  assert.deepEqual(calls, [[marked.parse(BODY, { breaks: false, gfm: true }), { USE_PROFILES: { html: true } }]]);
});

test("without a DOM (the build-time prerender) the markdown renders as before", () => {
  // Node has no DOM, so DOMPurify reports itself unsupported.
  assert.equal(renderMarkdown(BODY), marked.parse(BODY, { breaks: false, gfm: true }));
  assert.equal(renderMarkdown(undefined), "");
});
