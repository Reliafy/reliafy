// Rules use the design system v2 roles (tokens.css). The names before v2 no
// longer exist, so a var(--acc) written on an older branch would silently
// draw nothing: this fails instead, naming the file and the replacement.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const OLD = {
  bg: "bg-canvas", surf: "bg-surface", "surf-2": "bg-subtle", line: "border", line2: "border-subtle",
  ink: "text", muted: "text-secondary", subtle: "text-tertiary", faint: "text-disabled", "on-fill": "text-on-fill",
  acc: "accent (accent-text for text)", "acc-d": "accent-hover", "acc-t": "accent-subtle", "acc-hover": "accent-wash",
  "acc-line": "accent-border", ok: "success (success-text for text)", "ok-bg": "success-bg", "ok-line": "success-border",
  warn: "warning (warning-text for text)", "warn-bg": "warning-bg", "warn-line": "warning-border", "danger-line": "danger-border",
  "cat-teal-t": "cat-teal-bg", "cat-teal-line": "cat-teal-border", "cat-amber": "cat-pink", "cat-amber-t": "cat-pink-bg",
  "cat-amber-line": "cat-pink-border", "cat-violet-t": "cat-violet-bg", "cat-violet-line": "cat-violet-border",
  std: "icon-standard", axis: "chart-axis", "fs-28": "fs-24", "fs-42": "fs-40",
  "sp-1": "space-1", "sp-2": "space-2", "sp-3": "space-3", "sp-4": "space-4", "sp-5": "space-6", "sp-6": "space-8", "sp-7": "space-12",
  "r-sm": "radius-md", r: "radius-lg", "ctl-h": "control-md", "ctl-h-sm": "control-sm",
  "shadow-card": "shadow-sm", "shadow-overlay": "shadow-lg", focus: "focus-ring", "ring-sel": "ring-selected",
};
const src = fileURLToPath(new URL(".", import.meta.url));
const files = (dir) => readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
  e.isDirectory() ? files(join(dir, e.name)) : /\.(css|jsx?)$/.test(e.name) && !e.name.endsWith(".test.js") ? [join(dir, e.name)] : []);

test("no rule uses a token name from before design system v2", () => {
  const found = [];
  for (const f of files(src)) {
    for (const m of readFileSync(f, "utf8").matchAll(/var\(--([a-z0-9-]+)\s*[,)]/g)) {
      if (Object.hasOwn(OLD, m[1])) found.push(`${f.slice(src.length)}: --${m[1]} → --${OLD[m[1]]}`);
    }
  }
  assert.deepEqual(found, []);
});
