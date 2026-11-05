import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ancestorsOf, depthOf, filterOpen, filterRows, findByPrefix, flatten, levelSet, visiblePick,
} from "./outlineTree.js";

// A small outline: a → (b → (c, d), e); f.
function outline() {
  const rows = new Map();
  const roots = [];
  const add = (key, parent, name) => {
    const r = { key, parent, kids: [], depth: parent ? rows.get(parent).depth + 1 : 0, ref: { name, text: name.toUpperCase() } };
    rows.set(key, r);
    (parent ? rows.get(parent).kids : roots).push(key);
  };
  add("a", null, "alpha");
  add("b", "a", "bravo");
  add("c", "b", "charlie");
  add("d", "b", "delta");
  add("e", "a", "echo");
  add("f", null, "foxtrot");
  return { rows, roots };
}

test("the depth, the levels and a filter that keeps the path down to each match", () => {
  const d = outline();
  assert.equal(depthOf(d), 3);
  assert.deepEqual([...levelSet(d, 2)], ["a"]);
  const f = filterRows(d, (r) => r.ref.name.startsWith("d"));
  assert.deepEqual([...f.match], ["d"]);
  assert.deepEqual([...f.keep].sort(), ["a", "b", "d"]);
  assert.deepEqual([...filterOpen(f)].sort(), ["a", "b"]);
  assert.deepEqual(flatten(d, filterOpen(f), f).list.map((v) => v.key), ["a", "b", "d"]);
});

test("flatten draws siblings in the order asked for, keeping the tree", () => {
  const d = outline();
  const reverse = (keys) => [...keys].reverse();
  const { list } = flatten(d, levelSet(d, Infinity), null, reverse);
  assert.deepEqual(list.map((v) => v.key), ["f", "a", "e", "b", "d", "c"]);
  assert.deepEqual(list.map((v) => [v.pos, v.size]), [[1, 2], [2, 2], [1, 2], [2, 2], [1, 2], [2, 2]]);
});

test("the pick moves up to the row it's hidden in; type-ahead by another name", () => {
  const d = outline();
  const { index, list } = flatten(d, new Set(["a"]));
  assert.equal(visiblePick(d, index, "c"), "b");
  assert.equal(visiblePick(d, index, "e"), "e");
  assert.deepEqual(ancestorsOf(d, "c"), ["a", "b"]);
  assert.equal(findByPrefix(d, list, 0, "ECH", (r) => r.ref.text), "e");
  assert.equal(findByPrefix(d, list, 0, "fox"), "f");
});

test("filtering opens the way down to each match, and a match with matches inside it", () => {
  const rows = new Map();
  const add = (key, parent) => {
    rows.set(key, { key, parent, kids: [], depth: parent ? rows.get(parent).depth + 1 : 0, ref: { name: key } });
    if (parent) rows.get(parent).kids.push(key);
  };
  add("a", null); add("b", "a"); add("c", "b"); add("d", "a");
  const display = { rows, roots: ["a"] };
  const f = filterRows(display, (r) => r.key === "b" || r.key === "c");
  assert.deepEqual([...f.match].sort(), ["b", "c"]);
  assert.deepEqual([...filterOpen(f)].sort(), ["a", "b"]); // b is a match and holds c
});
