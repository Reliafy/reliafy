import { test } from "node:test";
import assert from "node:assert/strict";
import { PANE_PARAMS, TABLE_PANES, paneFromQuery, setPaneQuery } from "./tablePane.js";

test("the pane the address asks for", () => {
  assert.equal(paneFromQuery(new URLSearchParams("sel=p1")), null);
  assert.equal(paneFromQuery(null), null);
  assert.deepEqual(paneFromQuery(new URLSearchParams("sel=p1&fit=p1")), { kind: "fit", id: "p1" });
  assert.deepEqual(paneFromQuery(new URLSearchParams("predict=p2&tab=models")), { kind: "predict", id: "p2" });
  // Both somehow: the fit, one pane at a time.
  assert.deepEqual(paneFromQuery(new URLSearchParams("predict=p2&fit=p1")), { kind: "fit", id: "p1" });
});

test("an RBD's pane: the diagram, and the position it opens beside", () => {
  assert.deepEqual(paneFromQuery(new URLSearchParams("tab=models&rbd=r9&on=p3")), { kind: "rbd", id: "p3", rbd: "r9" });
  // No position: not one for the Explorer.
  assert.equal(paneFromQuery(new URLSearchParams("rbd=r9")), null);
  assert.equal(paneFromQuery(new URLSearchParams("on=p3")), null);
  // A fit or a prediction first.
  assert.deepEqual(paneFromQuery(new URLSearchParams("rbd=r9&on=p3&predict=p2")), { kind: "predict", id: "p2" });
});

test("putting a pane in the address takes any other out", () => {
  const q = new URLSearchParams("tab=models&sel=p1&fit=p1");
  assert.equal(setPaneQuery(q, "rbd", "p1", { rbd: "r9" }).toString(), "tab=models&sel=p1&rbd=r9&on=p1");
  assert.equal(setPaneQuery(q, "predict", "p2").toString(), "tab=models&sel=p1&predict=p2");
  assert.equal(setPaneQuery(q, "rbd", "p4", { rbd: "r1" }).toString(), "tab=models&sel=p1&rbd=r1&on=p4");
  for (const k of PANE_PARAMS) q.delete(k);
  assert.equal(q.toString(), "tab=models&sel=p1");
});

test("each pane has its address and its words for leaving it changed", () => {
  assert.deepEqual(PANE_PARAMS, ["fit", "predict", "rbd", "on"]);
  assert.equal(TABLE_PANES.predict.discard.title, "Discard this prediction?");
  assert.equal(TABLE_PANES.rbd.discard.title, "Discard your changes to this RBD?");
  for (const p of Object.values(TABLE_PANES)) {
    for (const k of ["title", "body", "confirmLabel", "cancelLabel"]) assert.ok(p.discard[k], k);
  }
});
