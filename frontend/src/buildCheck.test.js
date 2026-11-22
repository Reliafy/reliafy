import { describe, it, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { decideBuildAction, noteServerBuild, setUnsaved, anyUnsaved, pendingBuild, _reset } from "./buildCheck.js";

describe("decideBuildAction", () => {
  it("does nothing when the builds match", () => {
    assert.equal(decideBuildAction({ client: "a", server: "a" }), "none");
  });
  it("is off with no build id on either side", () => {
    assert.equal(decideBuildAction({ client: "", server: "b" }), "none");
    assert.equal(decideBuildAction({ client: "a", server: "" }), "none");
  });
  it("reloads on a mismatch with nothing unsaved", () => {
    assert.equal(decideBuildAction({ client: "a", server: "b" }), "reload");
  });
  it("offers a bar on a mismatch while unsaved", () => {
    assert.equal(decideBuildAction({ client: "a", server: "b", unsaved: true }), "bar");
  });
  it("does not loop after reloading for that build", () => {
    assert.equal(decideBuildAction({ client: "a", server: "b", reloadedFor: "b" }), "none");
    assert.equal(decideBuildAction({ client: "a", server: "c", reloadedFor: "b" }), "reload");
  });
});

describe("tracking", () => {
  beforeEach(_reset);
  it("remembers only a differing server build", () => {
    noteServerBuild("a", "a");
    assert.equal(pendingBuild(), "");
    noteServerBuild("", "a");
    assert.equal(pendingBuild(), "");
    noteServerBuild("b", "");
    assert.equal(pendingBuild(), "");
    noteServerBuild("b", "a");
    assert.equal(pendingBuild(), "b");
  });
  it("counts unsaved signals by key", () => {
    setUnsaved("x", true);
    setUnsaved("y", true);
    setUnsaved("x", false);
    assert.equal(anyUnsaved(), true);
    setUnsaved("y", false);
    assert.equal(anyUnsaved(), false);
  });
});
