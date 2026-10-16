import { test } from "node:test";
import assert from "node:assert/strict";
import { asHandle, mountForPath, mountsIn, readTokens, sectionOf } from "./extensions.js";

const MOUNTS = [
  { id: "a", path: "/reports", section: "workspace" },
  { id: "b", path: "/tools", section: "account" },
  { id: "c", path: "/odd", section: "sideways" },
];

test("sections: known ones kept, anything else is account", () => {
  assert.equal(sectionOf(MOUNTS[0]), "workspace");
  assert.equal(sectionOf(MOUNTS[2]), "account");
  assert.equal(sectionOf(undefined), "account");
  assert.deepEqual(mountsIn(MOUNTS, "workspace").map((m) => m.id), ["a"]);
  assert.deepEqual(mountsIn(MOUNTS, "account").map((m) => m.id), ["b", "c"]);
  assert.deepEqual(mountsIn(null, "account"), []);
});

test("a page owns its path and everything under it", () => {
  assert.equal(mountForPath(MOUNTS, "/reports")?.id, "a");
  assert.equal(mountForPath(MOUNTS, "/reports/x/y")?.id, "a");
  assert.equal(mountForPath(MOUNTS, "/reports/")?.id, "a");
  assert.equal(mountForPath(MOUNTS, "/reportsx"), null);
  assert.equal(mountForPath([], "/reports"), null);
});

test("mount() may return a cleanup function, a handle or nothing", () => {
  const fn = () => {};
  assert.equal(asHandle(fn).unmount, fn);
  const h = asHandle({ unmount() { return this; }, update() {} });
  assert.equal(typeof h.unmount, "function");
  assert.equal(typeof h.update, "function");
  assert.deepEqual(asHandle(undefined), { unmount: null, update: null });
});

test("theme tokens: only set ones, trimmed", () => {
  const style = { getPropertyValue: (n) => ({ "--acc": " #2f6df6 ", "--ink": "#14171c" })[n] || "" };
  assert.deepEqual(readTokens(style), { "--ink": "#14171c", "--acc": "#2f6df6" });
  assert.deepEqual(readTokens(null), {});
});
