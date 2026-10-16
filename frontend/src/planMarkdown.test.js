// Run with: node --test src/planMarkdown.test.js
import { test } from "node:test";
import assert from "node:assert/strict";
import { marked } from "marked";
import { rewritePlanLinks, sourceRepo, splitMermaid } from "./planMarkdown.js";

const GANTT = "gantt\n    title Example plan\n    dateFormat YYYY-MM-DD\n    Task one :a1, 2026-01-05, 10d\n    Task two :after a1, 7d";

test("prose and mermaid blocks come out in order", () => {
  const md = `# Example plan\n\nIntro.\n\n\`\`\`mermaid\n${GANTT}\n\`\`\`\n\nAfter.\n`;
  assert.deepEqual(splitMermaid(md), [
    { type: "markdown", text: "# Example plan\n\nIntro.\n" },
    { type: "mermaid", code: GANTT },
    { type: "markdown", text: "\nAfter.\n" },
  ]);
});

test("other fenced code stays in the prose", () => {
  const md = "Text\n\n```python\nprint(1)\n```\n";
  assert.deepEqual(splitMermaid(md), [{ type: "markdown", text: md }]);
});

test("tilde fences, longer fences, an info string and indentation", () => {
  const md = "~~~ mermaid\ngraph LR\n  A --> B\n~~~\n  ````Mermaid {theme}\npie\n```\nstill pie\n````";
  assert.deepEqual(splitMermaid(md), [
    { type: "mermaid", code: "graph LR\n  A --> B" },
    { type: "mermaid", code: "pie\n```\nstill pie" },
  ]);
});

test("a mermaid fence inside another fenced block is that block's text", () => {
  const md = "````markdown\n```mermaid\ngantt\n```\n````\n";
  assert.deepEqual(splitMermaid(md), [{ type: "markdown", text: md }]);
});

test("an unclosed mermaid fence runs to the end", () => {
  assert.deepEqual(splitMermaid("Intro\n```mermaid\ngantt\n  Task :a, 2026-01-01, 1d"), [
    { type: "markdown", text: "Intro" },
    { type: "mermaid", code: "gantt\n  Task :a, 2026-01-01, 1d" },
  ]);
});

test("inline backticks and CRLF line endings", () => {
  assert.deepEqual(splitMermaid("Use ```mermaid``` inline."), [{ type: "markdown", text: "Use ```mermaid``` inline." }]);
  assert.deepEqual(splitMermaid("```mermaid\r\ngraph TD\r\n```\r\n"), [{ type: "mermaid", code: "graph TD" }]);
  assert.deepEqual(splitMermaid(""), []);
  assert.deepEqual(splitMermaid(undefined), []);
});

// ---- links -------------------------------------------------------------------------

const SRC = "Example/plans@abc1234";
const html = (md) => marked.parse(md, { gfm: true });

test("the source names a repository and commit", () => {
  assert.deepEqual(sourceRepo("Example/plans@abc1234"), { owner: "Example", repo: "plans", ref: "abc1234" });
  assert.deepEqual(sourceRepo(" Example/plans@release/1.2 "), { owner: "Example", repo: "plans", ref: "release/1.2" });
  for (const s of ["", null, "smoke/seed.js", "plans@abc", "a/b@c d", "a/b@../x", "https://github.com/a/b"]) {
    assert.equal(sourceRepo(s), null, String(s));
  }
});

test("relative links go to the file at that commit, in a new tab", () => {
  const out = rewritePlanLinks(html("See [the backlog](README.md) and [nav](docs/navigation.md#tabs)."), SRC);
  assert.match(out, /<a href="https:\/\/github\.com\/Example\/plans\/blob\/abc1234\/README\.md" target="_blank" rel="noreferrer">the backlog<\/a>/);
  assert.match(out, /<a href="https:\/\/github\.com\/Example\/plans\/blob\/abc1234\/docs\/navigation\.md#tabs" target="_blank" rel="noreferrer">nav<\/a>/);
});

test("./, ../ and a leading / resolve from the repository's root", () => {
  const out = rewritePlanLinks(html("[a](./docs/a.md) [b](docs/x/../b.md) [c](/c.md) [d](../../d.md)"), SRC);
  for (const p of ["docs/a.md", "docs/b.md", "c.md", "d.md"]) {
    assert.ok(out.includes(`href="https://github.com/Example/plans/blob/abc1234/${p}"`), p);
  }
});

test("absolute links, mailto and #anchors are unchanged", () => {
  const before = html("[x](https://example.com/a.md) [y](mailto:a@example.com) [z](#later) [w](//example.com/b)");
  assert.equal(rewritePlanLinks(before, SRC), before);
  assert.equal(rewritePlanLinks(before, ""), before);
});

test("without a repository source, relative links are plain text", () => {
  for (const source of ["", "smoke/seed.js", undefined]) {
    const out = rewritePlanLinks(html("See [the backlog](README.md) now."), source);
    assert.equal(out, '<p>See <span class="plan-link-local">the backlog</span> now.</p>\n');
  }
});

test("a link's inner markup is kept", () => {
  const out = rewritePlanLinks(html("[**bold** `code`](notes.md)"), SRC);
  assert.match(out, />(<strong>bold<\/strong> <code>code<\/code>)<\/a>/);
});
