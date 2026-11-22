import { test } from "node:test";
import assert from "node:assert/strict";
import { windowText } from "./compareWindow.js";

test("the automatic window says it is the last time of the group whose data ends first", () => {
  const t = windowText({ tau_source: "auto", tau_group: "A" }, "1,233 cycles");
  assert.match(t, /^Window 1,233 cycles, set automatically: the last time seen in group A, whose data ends first\./);
  assert.match(t, /Type a shorter Window/);
});

test("a typed window says so, and a capped one says why it was cut", () => {
  assert.equal(windowText({ tau_source: "given", tau_group: "A" }, "500 h"),
    "Window 500 h, as you set it. Average lives count time up to it only.");
  assert.match(windowText({ tau_source: "capped", tau_group: "B" }, "900 h"), /was longer, so it was cut to the last time seen in group B/);
});
