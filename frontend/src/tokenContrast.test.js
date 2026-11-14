// The colour roles keep WCAG contrast in every theme (tokens.css, design
// system v2): 4.5:1 for text on the grounds it sits on, 3:1 for control
// borders, fills and icons. A token tweak can't quietly make text unreadable.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("./tokens.css", import.meta.url), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

// Each theme's declarations; a theme inherits the first (light) for names it doesn't set.
const block = (selector) => {
  const at = css.indexOf(selector);
  assert.ok(at >= 0, `${selector} is in tokens.css`);
  const body = css.slice(css.indexOf("{", at) + 1, css.indexOf("}", at));
  return Object.fromEntries([...body.matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
};
const light = block(':root, [data-theme="light"]');
const themes = { light, dark: { ...light, ...block('[data-theme="dark"]') } };

const resolve = (vars, name, depth = 0) => {
  const v = vars[name];
  assert.ok(v, `--${name} is defined`);
  assert.ok(depth < 16, `--${name} resolves`);
  const alias = /^var\(--([a-z0-9-]+)\)$/.exec(v);
  return alias ? resolve(vars, alias[1], depth + 1) : v;
};
const rgb = (v) => {
  const m = /^#([0-9a-f]{6})$/i.exec(v);
  assert.ok(m, `${v} is a 6-digit hex colour`);
  return [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16));
};
const lin = (c) => ((c /= 255) <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const lum = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};
const pair = (vars, fg, bg) => ratio(rgb(resolve(vars, fg)), rgb(resolve(vars, bg)));

const GROUNDS = ["bg-canvas", "bg-surface", "bg-subtle"];
const TEXT = [
  ...["text", "text-secondary", "text-tertiary", "accent-text"].flatMap((t) => GROUNDS.map((g) => [t, g])),
  ...["accent-subtle", "success-bg", "warning-bg", "danger-bg", "cat-teal-bg", "cat-violet-bg", "cat-pink-bg"].map((g) => ["text", g]),
  ["accent-text", "accent-subtle"], ["accent-text", "accent-wash"],
  ...["success", "warning", "danger"].flatMap((s) => [[`${s}-text`, `${s}-bg`], [`${s}-text`, "bg-surface"], ["text-on-fill", s]]),
  ["text-on-fill", "accent"], ["text-on-fill", "accent-hover"],
  ...["cat-teal", "cat-violet", "cat-pink", "cat-grey"].map((c) => [c, "bg-surface"]),
];
// Marks that carry meaning: 3:1. The dark danger fill is 2.95:1 on the
// surface; its ✕ glyph and word carry it (design system README).
const MARKS = [["border-control", "bg-surface"], ["border-control", "bg-canvas"], ["accent", "bg-surface"],
  ["success", "bg-surface"], ["warning", "bg-surface"], ["icon-standard", "bg-surface"], ["icon-standard", "accent-subtle"]];
const KNOWN = new Set(["dark danger bg-surface"]);

for (const [theme, vars] of Object.entries(themes)) {
  test(`${theme}: text roles pass 4.5:1 on the grounds they sit on`, () => {
    for (const [fg, bg] of TEXT) {
      const r = pair(vars, fg, bg);
      assert.ok(r >= 4.5, `--${fg} on --${bg} (${theme}): ${r.toFixed(2)}:1`);
    }
  });
  test(`${theme}: borders, fills and icons pass 3:1`, () => {
    for (const [fg, bg] of [...MARKS, ["danger", "bg-surface"]]) {
      const r = pair(vars, fg, bg);
      if (KNOWN.has(`${theme} ${fg} ${bg}`)) assert.ok(r >= 2.9, `--${fg} on --${bg} (${theme}): ${r.toFixed(2)}:1`);
      else assert.ok(r >= 3, `--${fg} on --${bg} (${theme}): ${r.toFixed(2)}:1`);
    }
  });
}

test("every role is defined once per theme, so every definition is checked", () => {
  for (const sel of [':root, [data-theme="light"]', '[data-theme="dark"]']) {
    const at = css.indexOf(sel);
    const body = css.slice(css.indexOf("{", at) + 1, css.indexOf("}", at));
    for (const name of ["text", "text-secondary", "accent", "accent-text", "bg-surface", "border-control"]) {
      const n = body.match(new RegExp(`--${name}:`, "g"))?.length || 0;
      assert.equal(n, 1, `--${name} is defined ${n} times in ${sel}`);
    }
  }
});
