import { test } from "node:test";
import assert from "node:assert/strict";
import { clearDraft, draftKey, readDraft, writeDraft } from "./rbdDraft.js";

const memory = () => {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, v), removeItem: (k) => m.delete(k) };
};

test("an unsaved starter's edits come back after a reload, until saved", () => {
  const s = memory();
  const key = draftKey("abc123");
  assert.equal(readDraft(key, s), null);
  writeDraft(key, { nodes: [{ id: "c1", data: { label: "Valve" } }], edges: [] }, s);
  assert.equal(readDraft(key, s).graph.nodes[0].data.label, "Valve");
  clearDraft(key, s);
  assert.equal(readDraft(key, s), null);
});

test("no key for a page opened straight from its address, and storage that refuses is harmless", () => {
  assert.equal(draftKey("default"), null);
  assert.equal(draftKey(undefined), null);
  const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("full"); }, removeItem: () => { throw new Error("x"); } };
  writeDraft("rbd-draft:k", { nodes: [] }, broken);
  assert.equal(readDraft("rbd-draft:k", broken), null);
  clearDraft("rbd-draft:k", broken);
  assert.equal(readDraft("rbd-draft:k", null), null);
});
