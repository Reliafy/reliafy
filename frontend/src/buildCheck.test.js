import { describe, expect, it, beforeEach } from "vitest";
import { decideBuildAction, noteServerBuild, setUnsaved, anyUnsaved, pendingBuild, _reset } from "./buildCheck.js";

describe("decideBuildAction", () => {
  it("does nothing when the builds match", () => {
    expect(decideBuildAction({ client: "a", server: "a" })).toBe("none");
  });
  it("is off with no build id on either side", () => {
    expect(decideBuildAction({ client: "", server: "b" })).toBe("none");
    expect(decideBuildAction({ client: "a", server: "" })).toBe("none");
  });
  it("reloads on a mismatch with nothing unsaved", () => {
    expect(decideBuildAction({ client: "a", server: "b" })).toBe("reload");
  });
  it("offers a bar on a mismatch while unsaved", () => {
    expect(decideBuildAction({ client: "a", server: "b", unsaved: true })).toBe("bar");
  });
  it("does not loop after reloading for that build", () => {
    expect(decideBuildAction({ client: "a", server: "b", reloadedFor: "b" })).toBe("none");
    expect(decideBuildAction({ client: "a", server: "c", reloadedFor: "b" })).toBe("reload");
  });
});

describe("tracking", () => {
  beforeEach(_reset);
  it("remembers only a differing server build", () => {
    noteServerBuild("a", "a");
    expect(pendingBuild()).toBe("");
    noteServerBuild("", "a");
    expect(pendingBuild()).toBe("");
    noteServerBuild("b", "");
    expect(pendingBuild()).toBe("");
    noteServerBuild("b", "a");
    expect(pendingBuild()).toBe("b");
  });
  it("counts unsaved signals by key", () => {
    setUnsaved("x", true);
    setUnsaved("y", true);
    setUnsaved("x", false);
    expect(anyUnsaved()).toBe(true);
    setUnsaved("y", false);
    expect(anyUnsaved()).toBe(false);
  });
});
