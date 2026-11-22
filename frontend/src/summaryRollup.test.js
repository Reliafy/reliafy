import { test } from "node:test";
import assert from "node:assert/strict";
import { rollupChips } from "./summaryRollup.js";

const blank = { positions: 0, items: 0, tasks: 0, failure_modes: 0, models: 0, failure_reports: 0, open_reports: 0 };

test("the Summary's chips count everything below at every depth, the row's own records included", () => {
  const data = {
    here: { ...blank, items: 1, tasks: 1, failure_modes: 1 },
    inside: { ...blank, positions: 7, items: 5, tasks: 2, failure_modes: 2, models: 2, failure_reports: 3, open_reports: 1 },
  };
  const chips = rollupChips(data);
  assert.deepEqual(chips.map((c) => c.text), [
    "7 positions below", "5 fitted items below", "3 tasks", "3 failure modes", "2 models", "3 failure reports, 1 open"]);
  // Its own fitted item is a fact about it (Facts), not counted with what's below.
  assert.equal(chips[1].text, "5 fitted items below");
  assert.equal(chips.find((c) => c.id === "tasks").title, "1 here, 2 below");
  assert.equal(chips.find((c) => c.id === "tasks").tab, "maintenance");
  // Nothing counted: no chip. A design has nothing fitted.
  assert.deepEqual(rollupChips({ here: blank, inside: blank }), []);
  assert.ok(!rollupChips(data, { design: true }).some((c) => c.id === "items"));
  assert.deepEqual(rollupChips(null), []);
});
