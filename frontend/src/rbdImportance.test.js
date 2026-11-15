import { test } from "node:test";
import assert from "node:assert/strict";
import { importanceRows } from "./rbdImportance.js";

test("a block the API gives no measures for is named, with a note, never its raw id", () => {
  const result = {
    importance: {
      "pmu-engine": "simulation",
      belt: { label: "Generator belt", birnbaum: 0.97, unavailability_criticality: 0.02 },
    },
    exact: { blocks_by_downtime: [{ id: "pmu-engine", label: "PMU engine", share: 0.06 }] },
  };
  const rows = importanceRows(result);
  const engine = rows.find((r) => r.id === "pmu-engine");
  assert.equal(engine.label, "PMU engine");
  assert.equal(engine.note, "Needs a simulation");
  assert.equal(engine.birnbaum, undefined);
  assert.equal(rows.find((r) => r.id === "belt").note, null);
});

test("with no label anywhere, the id reads as words", () => {
  const rows = importanceRows({ importance: { "fuel-pump_2": "simulation" } });
  assert.equal(rows[0].label, "fuel pump 2");
});

test("rows sort by share of downtime, then by name", () => {
  const rows = importanceRows({
    importance: {
      a: { label: "B", unavailability_criticality: 0.1 },
      b: { label: "A", unavailability_criticality: 0.5 },
      c: "simulation",
    },
    criticality: { c: { label: "C" } },
  });
  assert.deepEqual(rows.map((r) => r.label), ["A", "B", "C"]);
});
