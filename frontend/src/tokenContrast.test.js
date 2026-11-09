// Text colour tokens keep WCAG AA contrast (4.5:1 for normal text) on every
// surface they sit on, so a token tweak can't quietly make links unreadable.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("./index.css", import.meta.url), "utf8");
const root = css.slice(css.indexOf(":root"), css.indexOf("}", css.indexOf(":root")));
const token = (name) => {
  const m = root.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`));
  assert.ok(m, `--${name} is a 6-digit hex colour in :root`);
  return m[1];
};
const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const lin = (c) => ((c /= 255) <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const lum = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};
// The accent tint (--acc-t: the accent at 9%) laid over a surface.
const tint = (fg, bg, a = 0.09) => fg.map((c, i) => Math.round(c * a + bg[i] * (1 - a)));

const surfaces = () => ({
  page: rgb(token("bg")),
  card: rgb(token("surf")),
  panel: rgb(token("surf-2")),
  stripe: rgb(token("line2")),
});

for (const name of ["ink", "muted", "subtle", "acc", "acc-d"]) {
  test(`--${name} text passes 4.5:1 on every surface`, () => {
    const fg = rgb(token(name));
    for (const [where, bg] of Object.entries(surfaces())) {
      const r = ratio(fg, bg);
      assert.ok(r >= 4.5, `--${name} on ${where}: ${r.toFixed(2)}:1`);
    }
  });
}

test("accent text passes on its own tint (active tabs, selected chips)", () => {
  const acc = rgb(token("acc"));
  for (const where of ["page", "card"]) {
    const r = ratio(acc, tint(acc, surfaces()[where]));
    assert.ok(r >= 4.5, `--acc on --acc-t over ${where}: ${r.toFixed(2)}:1`);
  }
});

// Tinted panels the accent sits on, measured in the page sweep: the active menu
// item and dropzone, the API docs' active side link, the joint model's panel.
test("accent text passes on the tinted panels seen in the app", () => {
  const acc = rgb(token("acc"));
  for (const bg of [[236, 242, 254], [233, 238, 249], [243, 246, 254]]) {
    const r = ratio(acc, bg);
    assert.ok(r >= 4.5, `--acc on rgb(${bg}): ${r.toFixed(2)}:1`);
  }
});

test("white text on the primary button passes", () => {
  for (const name of ["acc", "acc-d"]) {
    const r = ratio(rgb(token("on-fill")), rgb(token(name)));
    assert.ok(r >= 4.5, `--on-fill on --${name}: ${r.toFixed(2)}:1`);
  }
});

// The app has one theme today. A second set of these tokens (a dark theme, a
// print sheet) must get its own checks above before it lands.
test("the text tokens are defined once, so every definition is checked", () => {
  for (const name of ["ink", "muted", "subtle", "acc", "acc-d", "on-fill", "bg", "surf", "surf-2", "line2"]) {
    const n = css.match(new RegExp(`--${name}:`, "g"))?.length || 0;
    assert.equal(n, 1, `--${name} is defined ${n} times in index.css: add the new theme's surfaces to this test`);
  }
});

// The performance-standard icon colour (RCM tree, details, lists): a graphical
// object needs 3:1 on every surface it sits on, selected row included.
test("--std icon colour passes 3:1 on every surface and the selected row", () => {
  const fg = rgb(token("std"));
  const acc = rgb("#2f6df6"); // --acc-t is this accent at 9%
  const on = { ...surfaces(), selected: tint(acc, surfaces().card), "selected on page": tint(acc, surfaces().page) };
  for (const [where, bg] of Object.entries(on)) {
    const r = ratio(fg, bg);
    assert.ok(r >= 3, `--std on ${where}: ${r.toFixed(2)}:1`);
  }
});
