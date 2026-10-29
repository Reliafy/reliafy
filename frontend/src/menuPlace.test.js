import { test } from "node:test";
import assert from "node:assert/strict";
import { placeMenu, placeSubmenu } from "./menuPlace.js";

const view = { vw: 400, vh: 800 };
const size = { w: 200, h: 120 };

test("a menu opens at the point when it fits", () => {
  assert.deepEqual(placeMenu({ x: 50, y: 100 }, size, view), { left: 50, top: 100 });
});

test("near the right or bottom edge it flips left or up", () => {
  assert.deepEqual(placeMenu({ x: 350, y: 760 }, size, view), { left: 150, top: 640 });
});

test("it never goes past an edge, even when flipping doesn't fit", () => {
  assert.deepEqual(placeMenu({ x: 150, y: 2 }, { w: 380, h: 120 }, view), { left: 8, top: 8 });
  assert.deepEqual(placeMenu({ x: -20, y: 790 }, size, { vw: 400, vh: 100 }), { left: 8, top: 8 });
});

test("a submenu opens beside its item: to the right, else to the left, kept on screen", () => {
  const item = { left: 100, right: 300, top: 200, bottom: 230 };
  assert.deepEqual(placeSubmenu(item, { w: 180, h: 150 }, { vw: 1280, vh: 800 }), { left: 298, top: 196 });
  // No room on the right: on the left of the menu.
  assert.deepEqual(placeSubmenu({ ...item, left: 1000, right: 1200 }, { w: 180, h: 150 }, { vw: 1280, vh: 800 }), { left: 822, top: 196 });
  // Near the bottom: moved up.
  assert.deepEqual(placeSubmenu({ ...item, top: 760 }, { w: 180, h: 150 }, { vw: 1280, vh: 800 }).top, 642);
});
