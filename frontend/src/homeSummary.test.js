import { test } from "node:test";
import assert from "node:assert/strict";
import { cardFailed, homeFromSummary } from "./homeSummary.js";
import { modelRows } from "./modelRows.js";
import { attentionFailed, attentionReady, recentRows } from "./home.js";

const life = { models: [{ id: "m1", name: "Pumps", distribution: "Weibull", created_at: "2026-11-02" }] };
const alt = { models: [{ id: "a1", name: "Bearings", distribution: "Weibull", life_model: "Arrhenius",
  created_at: "2026-11-05" }] };
const summary = {
  maintenance: true,
  sections: {
    models: life, alt_models: alt, recurrent_models: { models: [] }, degradation_models: { models: [] },
    joint_models: { models: [] },
    datasets: { datasets: [{ id: "d1", name: "Pump data", created_at: "2026-11-01" }] },
    rbds: { rbds: [] }, fleets: { fleets: [] }, strategy_analyses: { analyses: [] },
    tracked_fleets: { fleets: [{ id: "t1", name: "Line 2" }] },
    changes: { counts: { items: 2 }, sentence: "2 things changed." },
    maintenance_overview: { due: [], open_work_orders: [], late: { work_orders_late: 0 } },
    rcm_rollup: { decisions: 3 },
  },
  errors: {},
};

test("Home draws from the summary what it used to read from each list", () => {
  const home = homeFromSummary(summary);
  // The models are the rows the Models list draws, from the same lists.
  assert.deepEqual(home.lists.models, modelRows({ life, alt }));
  assert.deepEqual(home.lists.models.map((m) => m.id), ["a1", "m1"]);
  assert.deepEqual(home.lists.datasets, summary.sections.datasets.datasets);
  assert.deepEqual(home.lists.tracked, summary.sections.tracked_fleets.fleets);
  assert.equal(home.lists.failed, false);
  assert.equal(home.changes, summary.sections.changes);
  assert.equal(home.access, true);
  assert.equal(home.maintenance, summary.sections.maintenance_overview);
  assert.deepEqual(home.rcm, { decisions: 3 });
  assert.deepEqual(home.failedParts, []);
  assert.equal(attentionReady({ ...home, tracked: home.lists.tracked }), true);
  assert.equal(attentionFailed({ ...home, tracked: home.lists.tracked }), false);
  assert.equal(recentRows(home.lists).length, 4);
  // The first-run starts are worked out from the same lists, not read again.
  assert.deepEqual(home.firstRunLists.models, life.models);
  assert.deepEqual(home.firstRunLists.alt, alt.models);
  assert.deepEqual(home.firstRunLists.datasets, summary.sections.datasets.datasets);
});

test("a part that failed spoils only the lists drawn from it", () => {
  const { changes, ...sections } = summary.sections;
  delete sections.datasets;
  const home = homeFromSummary({ ...summary, sections,
    errors: { changes: "Couldn't load what changed.", datasets: "Couldn't load this list." } });
  assert.equal(home.changes, null);
  assert.equal(home.lists.failed, true);
  assert.deepEqual(home.lists.datasets, []);
  assert.equal(home.lists.models.length, 2);
  assert.equal(cardFailed("recent-data", home.failedParts), true);
  assert.equal(cardFailed("recent-models", home.failedParts), false);
  assert.equal(cardFailed("recent", home.failedParts), true);
  // "Needs attention" says it couldn't load, never "Nothing needs you".
  assert.equal(attentionFailed({ ...home, tracked: home.lists.tracked }), true);
});

test("without Maintenance its pieces are never waited for", () => {
  const home = homeFromSummary({ ...summary, maintenance: false });
  assert.equal(home.access, false);
  assert.equal(home.maintenance, undefined);
  assert.equal(attentionReady({ ...home, tracked: home.lists.tracked }), true);
});

test("the request itself failing: every section says it couldn't load", () => {
  const home = homeFromSummary(null);
  assert.equal(home.lists.failed, true);
  assert.equal(home.changes, null);
  assert.equal(home.access, null);
  assert.equal(cardFailed("recent-models", home.failedParts), true);
  assert.equal(attentionFailed({ ...home, tracked: null }), true);
});
