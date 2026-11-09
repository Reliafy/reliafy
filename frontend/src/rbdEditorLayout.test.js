import { test } from "node:test";
import assert from "node:assert/strict";
import { NARROW_BUILDER, TIGHT_BUILDER, builderWidthClass } from "./rbdEditorLayout.js";

test("the builder lays itself out by its own width", () => {
  assert.equal(builderWidthClass(0), "");  // hidden: not measured
  assert.equal(builderWidthClass(undefined), "");
  assert.equal(builderWidthClass(1360), "");  // the page at 1440 px
  assert.equal(builderWidthClass(NARROW_BUILDER), "");
  assert.equal(builderWidthClass(NARROW_BUILDER - 1), " is-narrow");  // the pane beside the tree on a laptop
  assert.equal(builderWidthClass(TIGHT_BUILDER), " is-narrow");
  assert.equal(builderWidthClass(TIGHT_BUILDER - 1), " is-narrow is-tight");
  assert.equal(builderWidthClass(376), " is-narrow is-tight");  // a phone
});
