import { test } from "node:test";
import assert from "node:assert/strict";
import { PANE_PARAMS, TABLE_PANES, paneFromQuery } from "./tablePane.js";

test("the pane the address asks for", () => {
  assert.equal(paneFromQuery(new URLSearchParams("sel=p1")), null);
  assert.equal(paneFromQuery(null), null);
  assert.deepEqual(paneFromQuery(new URLSearchParams("sel=p1&fit=p1")), { kind: "fit", id: "p1" });
  assert.deepEqual(paneFromQuery(new URLSearchParams("predict=p2&tab=models")), { kind: "predict", id: "p2" });
  // Both somehow: the fit, one pane at a time.
  assert.deepEqual(paneFromQuery(new URLSearchParams("predict=p2&fit=p1")), { kind: "fit", id: "p1" });
});

test("each pane has its address and its words for leaving it changed", () => {
  assert.deepEqual(PANE_PARAMS, ["fit", "predict"]);
  assert.equal(TABLE_PANES.predict.discard.title, "Discard this prediction?");
  for (const p of Object.values(TABLE_PANES)) {
    for (const k of ["title", "body", "confirmLabel", "cancelLabel"]) assert.ok(p.discard[k], k);
  }
});
