// Help links name what they do: "Take the tour" (a walkthrough) or "Read the guide"
// (a how-to), never a generic "Show me how" (design system, HelpLink).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

// A label, not a comment: JSX text (>Show me how), a string given as a label or default.
const LABEL = /(>\s*|label:\s*|=\s*|\|\|\s*|\?\s*|:\s*)["'`]?Show me how/i;

test("no help link says \"Show me how\"", () => {
  const offenders = [];
  const walk = (dir) => {
    for (const f of readdirSync(dir)) {
      const p = join(dir, f);
      if (statSync(p).isDirectory()) walk(p);
      else if (/\.(jsx?|mjs)$/.test(f) && !/\.test\.[jt]s$/.test(f)) {
        readFileSync(p, "utf8").split("\n").forEach((line, i) => {
          const code = line.trim();
          if (code.startsWith("//") || code.startsWith("*") || code.startsWith("{/*")) return;
          if (LABEL.test(code) || /^Show me how/i.test(code)) offenders.push(`${p}:${i + 1}`);
        });
      }
    }
  };
  walk(new URL(".", import.meta.url).pathname);
  assert.deepEqual(offenders, []);
});
