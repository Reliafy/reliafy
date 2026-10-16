// Run with: node --test src/planMarkdown.test.js
import { test } from "node:test";
import assert from "node:assert/strict";
import { splitMermaid } from "./planMarkdown.js";

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
