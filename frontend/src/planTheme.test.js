// Run with: node --test src/planTheme.test.js
import { test } from "node:test";
import assert from "node:assert/strict";
import { ganttThemeVariables, readTokens, shade, tint, TOKENS } from "./planTheme.js";

test("tint and shade", () => {
  assert.equal(tint("#2f6df6", 1), "#2f6df6");
  assert.equal(tint("#2f6df6", 0), "#ffffff");
  assert.equal(shade("#b91c1c", 0), "#b91c1c");
  assert.equal(shade("#b91c1c", 1), "#000000");
});

test("each Gantt state has its own fill, from the app's tokens", () => {
  const v = ganttThemeVariables();
  assert.equal(v.taskBkgColor, TOKENS.acc); // not started: the accent
  assert.equal(v.critBkgColor, TOKENS.danger);
  assert.equal(v.activeTaskBorderColor, TOKENS.acc);
  assert.equal(v.todayLineColor, TOKENS.danger);
  const fills = [v.taskBkgColor, v.activeTaskBkgColor, v.doneTaskBkgColor, v.critBkgColor];
  assert.equal(new Set(fills).size, 4);
  // Text: white on the solid bars, ink on the light ones and outside them.
  assert.equal(v.taskTextColor, "#ffffff");
  assert.equal(v.taskTextDarkColor, TOKENS.ink);
  assert.equal(v.taskTextOutsideColor, TOKENS.ink);
  for (const value of Object.values(v)) assert.match(value, /^#[0-9a-f]{6}$/);
});

test("tokens come from the page's :root, hex only", () => {
  const values = { "--acc": " #112233", "--danger": "rgb(1,2,3)" };
  const t = readTokens({ getPropertyValue: (n) => values[n] || "" });
  assert.equal(t.acc, "#112233");
  assert.equal(t.danger, TOKENS.danger);
  assert.deepEqual(readTokens(null), TOKENS);
  assert.equal(ganttThemeVariables(t).taskBkgColor, "#112233");
});
