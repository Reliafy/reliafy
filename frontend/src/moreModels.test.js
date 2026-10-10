import { test } from "node:test";
import assert from "node:assert/strict";
import { groupProblem, pickerGroups, withGroup } from "./moreModels.js";

const plain = [
  { id: "best" }, { id: "weibull" }, { id: "geometric", discrete: true },
  { id: "kaplan_meier", nonparametric: true }, { id: "beta", more: true, bounded: true },
  { id: "discretized_gamma", discrete: true, more: true }, { id: "royston_parmar", flexible: true, more: true },
];
const regression = [
  { id: "weibull_ph", effect: "hazard" }, { id: "weibull_aft", effect: "aft" },
  { id: "buckley_james", effect: "aft", more: true }, { id: "weibull_frailty", effect: "hazard", more: true, frailty: true },
];

test("rare models go last, under More models", () => {
  const groups = pickerGroups(plain, false);
  assert.deepEqual(groups.map(([h]) => h), ["Continuous", "Discrete", "Non-parametric", "More models"]);
  assert.deepEqual(groups[3][1].map((d) => d.id), ["beta", "discretized_gamma", "royston_parmar"]);
  assert.deepEqual(groups[1][1].map((d) => d.id), ["geometric"]);
  const reg = pickerGroups(regression, true);
  assert.deepEqual(reg.map(([h]) => h), ["Proportional hazards", "Accelerated failure time", "More models"]);
  assert.deepEqual(reg[2][1].map((d) => d.id), ["buckley_james", "weibull_frailty"]);
});

test("no More models section when nothing is rare", () => {
  assert.deepEqual(pickerGroups([{ id: "weibull" }], false).map(([h]) => h), ["Continuous"]);
});

test("Group by rides on the mapping for frailty models only", () => {
  const m = { x: "t", c: "c", group: "old" };
  assert.deepEqual(withGroup(m, { frailty: true }, "site"), { x: "t", c: "c", group: "site" });
  assert.deepEqual(withGroup(m, { id: "weibull_ph" }, "site"), { x: "t", c: "c" });
  assert.deepEqual(withGroup(m, { frailty: true }, ""), { x: "t", c: "c" });
  assert.match(groupProblem({ frailty: true }, ""), /Group by/);
  assert.equal(groupProblem({ frailty: true }, "site"), null);
  assert.equal(groupProblem({ id: "weibull" }, ""), null);
});
