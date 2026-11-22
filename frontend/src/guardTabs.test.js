import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

// Tab rows come from the shared Tabs (components/ui/Tabs.jsx) and switches
// between a few views from SegmentedControl: never a hand-rolled role="tab"
// or role="tablist" (docs/design-system/components/Tabs.md).
const ROOT = new URL(".", import.meta.url).pathname;
const ALLOWED = new Set([join(ROOT, "components/ui/Tabs.jsx")]);

function* files(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) yield* files(p);
    else if (/\.jsx?$/.test(name) && !/\.test\.js$/.test(name)) yield p;
  }
}

test("no hand-rolled tab rows: use the shared Tabs or SegmentedControl", () => {
  const found = [];
  for (const p of files(ROOT)) {
    if (ALLOWED.has(p)) continue;
    readFileSync(p, "utf8").split("\n").forEach((line, i) => {
      if (/role[=:]\s*\{?\s*["'`]tab(list)?["'`]/.test(line)) found.push(`${p.slice(ROOT.length)}:${i + 1}`);
    });
  }
  assert.deepEqual(found, [], `Use components/ui/Tabs.jsx (or SegmentedControl) instead of role="tab":\n${found.join("\n")}`);
});
