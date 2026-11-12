import { test } from "node:test";
import assert from "node:assert/strict";
import { buildDisplay, computeFilter, flatten, markersOf, rowText } from "./assetTree.js";
import { positionOf } from "./explorerRcm.js";
import {
  MODEL_CHIPS, rangeBound, MODEL_POSITION_ITEMS, MODEL_USUAL, attachGroups, attachedFor, b10Text, boundsLabel, countsText, inUseWords, fmt, graftModels, headline, isModelRow, meanText, modelKey,
  openForModels, predictionAssign, predictionWords, rollupText, rowActions, usedText, withBounds,
  isLifeModelLink, lifeModelOf, builtRbdLink,
  opensInPane,
} from "./explorerModels.js";

const DATA = {
  positions: [
    { id: "plant", name: "Plant", parent_id: null },
    { id: "pump", name: "Pump A", parent_id: "plant" },
    { id: "fan", name: "Fan", parent_id: "plant" },
  ],
  locations: [], spares: [], unhomed: [],
};
const WEIBULL = {
  name: "Bearing life", kind: "Weibull", family: "life", unit: "Hours", trend: null, path: "/models/m/w1",
  numbers: [
    { id: "char_life", label: "Characteristic life", value: 1435.07, lower: 1233.86, upper: 1669.1, unit: "Hours" },
    { id: "shape", label: "Shape", value: 2.4952, lower: 1.876, upper: 3.319, unit: "" },
    { id: "mean", label: "Mean life", value: 1272.6, lower: 1150.2, upper: null, unit: "Hours", bound: "lower" },
    { id: "b10", label: "B10 life", value: 582.37, lower: 467.25, upper: null, unit: "Hours", bound: "lower" },
  ],
  counts: { failures: 30, suspensions: 0 }, quality: { word: "Good", tone: "success", why: "30 failures." },
};
const link = (id, pos, over = {}) => ({
  id, position_id: pos, model_type: "model", model_id: `m-${id}`, role: "assigned", name: "Bearing life",
  failure_modes: [], source_text: "Assigned: Bearing life", stale: null, model: WEIBULL,
  used_by: { decisions: [], rbds: [] }, ...over,
});
const LINKS = [
  link("a", "pump", { in_use: true }),
  link("b", "pump", { role: "fitted", stale: "2 failures since it was fitted: refit it", failure_modes: [{ id: "seal", text: "Seal leaks" }] }),
  link("c", "fan", { model: null }),
];

test("each link hangs under its position, before the positions inside it", () => {
  const g = graftModels(buildDisplay(DATA, "positions"), LINKS);
  const pump = g.rows.get("pump");
  assert.deepEqual(pump.kids.slice(0, 2), [modelKey("a"), modelKey("b")]);
  assert.equal(pump.modelKids, 2);
  const row = g.rows.get(modelKey("b"));
  assert.ok(isModelRow(row));
  assert.equal(positionOf(row), "pump");
  assert.equal(row.depth, pump.depth + 1);
  assert.match(rowText(row), /seal leaks/);
  assert.deepEqual(markersOf(row), []);
  // The display given is untouched.
  assert.equal(buildDisplay(DATA, "positions").rows.get("pump").kids.length, 0);
});

test("a position rolls up its own models open, and everything inside it closed", () => {
  const g = graftModels(buildDisplay(DATA, "positions"), LINKS);
  assert.equal(rollupText(g.rows.get("pump"), true), "2 models · 1 stale · in use: Weibull");
  assert.equal(rollupText(g.rows.get("plant"), true), "");
  assert.equal(rollupText(g.rows.get("plant"), false), "3 models · 1 stale · 1 missing");
  assert.equal(rollupText(g.rows.get("fan"), true), "1 model · 1 missing");
  const gone = g.rows.get(modelKey("c"));
  assert.equal(gone.ref.name, "Bearing life");
});

test("the cells: headline with bounds, mean, B10, counts, used by", () => {
  assert.equal(headline(WEIBULL), "Life 1,435 hours (1,234–1,669) · shape 2.5 (1.88–3.32)");
  assert.equal(meanText(WEIBULL), "1,273 hours (≥ 1,150)");
  assert.equal(b10Text(WEIBULL), "582 hours (≥ 467)");
  assert.equal(countsText(WEIBULL), "30 failures, 0 suspensions");
  const exp = { numbers: [{ id: "mtbf", value: 2000, lower: 1500, upper: 2800, unit: "Hours" }] };
  assert.equal(headline(exp), "MTBF 2,000 hours (1,500–2,800)");
  assert.equal(meanText(exp), "—");
  const rec = { trend: "Getting worse", numbers: [{ id: "rate", value: 0.0030919, lower: 0.00173, upper: 0.00512, unit: "per hour" },
    { id: "mtbf", value: 323.4, unit: "Hours" }] };
  assert.equal(headline(rec), "Rate 0.00309 per hour (0.00173–0.00512) · Getting worse");
  assert.equal(headline({ numbers: [{ id: "threshold", label: "Fails at", text: "8 mm · linear path" }] }), "Fails at 8 mm · linear path");
  assert.equal(countsText({ counts: { units: 6 } }), "6 units measured");
  assert.equal(usedText({ used_by: { decisions: [{}, {}], rbds: [{}] } }), "2 decisions · 1 RBD");
  assert.equal(usedText({ used_by: { decisions: [], rbds: [] } }), "");
  assert.equal(fmt(null), "—");
  assert.equal(fmt(1234567), "1,235,000");
  assert.equal(withBounds({ value: 5, unit: "" }), "5");
});

test("the row's actions: Refit only for a fitted model, Open in Models only when it's there", () => {
  const g = graftModels(buildDisplay(DATA, "positions"), LINKS);
  assert.deepEqual(rowActions(g.rows.get(modelKey("a"))).map((a) => a.id),
    ["model-open", "model-page", "model-bayes", "model-to-library", "model-replace", "model-unlink"]);
  assert.deepEqual(rowActions(g.rows.get(modelKey("b"))).map((a) => a.id),
    ["model-open", "model-page", "model-use", "model-refit", "model-bayes", "model-to-library", "model-replace", "model-unlink"]);
  const bayes = graftModels(buildDisplay(DATA, "positions"), [link("q", "pump", { role: "bayesian", model: { ...WEIBULL, kind: "Weibull (Bayesian)" } })]);
  assert.equal(rowActions(bayes.rows.get(modelKey("q"))).find((a) => a.id === "model-bayes").label, "Update with new failures…");
  assert.deepEqual(rowActions(g.rows.get(modelKey("c"))).map((a) => a.id), ["model-open", "model-replace", "model-unlink"]);
  assert.ok(rowActions(g.rows.get(modelKey("a")), { viewOnly: "View only" }).find((a) => a.id === "model-unlink").disabled);
  assert.ok(!MODEL_USUAL.includes("b10") && MODEL_USUAL.includes("mean"));
});

test("the Stale chip finds models behind their history and models that are gone", () => {
  const g = graftModels(buildDisplay(DATA, "positions"), LINKS);
  const f = computeFilter(g, { query: "", chips: ["stale"] });
  assert.ok(f.match.has(modelKey("b")) && f.match.has(modelKey("c")) && !f.match.has(modelKey("a")));
  assert.equal(MODEL_CHIPS[0].tab, "models");
  assert.deepEqual(openForModels(g, "pump"), ["pump", "plant"]);
  const { list } = flatten(g, new Set(["plant", "pump"]));
  const keys = list.map((v) => v.key);
  assert.deepEqual(keys.slice(keys.indexOf("pump"), keys.indexOf("pump") + 3), ["pump", modelKey("a"), modelKey("b")]);
});

test("the evidence picker's models on the position: this mode's first, then every failure's", () => {
  const links = [
    link("x", "pump", { model_id: "all" }),
    link("y", "pump", { model_id: "mine", failure_modes: [{ id: "seal", text: "Seal" }] }),
    link("z", "pump", { model_id: "other", failure_modes: [{ id: "bearing", text: "Bearing" }] }),
    link("r", "pump", { model_id: "rec", model_type: "recurrent_model" }),
    link("d", "pump", { model_id: "deg", model_type: "degradation_model" }),
  ];
  assert.deepEqual(attachedFor(links, { modeId: "seal", expectedType: "model" }).map((o) => o.id), ["mine", "all"]);
  assert.equal(attachedFor(links, { modeId: "seal", expectedType: "model" })[0].meta, "On this position, for this failure mode");
  assert.deepEqual(attachedFor(links, { modeId: "seal", expectedType: "degradation_model" }).map((o) => o.id), ["deg"]);
});

test("a Bayesian update's numbers are credible intervals at its level, never bounds or confidence", () => {
  const bayes = {
    kind: "Weibull (Bayesian)", credible: true, credible_level: 0.9, unit: "Years",
    numbers: [
      { id: "char_life", value: 4.1512, lower: 3.2311, upper: 5.3489, unit: "Years", bound: "credible" },
      { id: "shape", value: 2.03, lower: 1.5, upper: 2.74, unit: "", bound: "credible" },
      { id: "mean", value: 3.68, lower: 2.9, upper: 4.6, unit: "Years", bound: "credible" },
    ],
  };
  assert.equal(headline(bayes), "Life 4.15 years, 90% credible 3.23–5.35 · shape 2.03, 90% credible 1.5–2.74");
  assert.equal(meanText(bayes), "3.68 years, 90% credible 2.9–4.6");
  assert.equal(boundsLabel(bayes), "90% credible interval");
  assert.equal(boundsLabel({ ...bayes, credible_level: 0.95 }), "95% credible interval");
  assert.equal(boundsLabel(WEIBULL), "95% bounds");
  for (const text of [headline(bayes), meanText(bayes), boundsLabel(bayes)]) assert.doesNotMatch(text, /bound|confidence/i);
});

test("a prediction's part types as the server takes them, and its numbers in words", () => {
  const lines = [
    { reference: "C-100", record: { id: "rec-cap" }, quality_factor: "1" },
    { reference: "U-7", record_id: "rec-opto", quality_factor: "3" },
    { reference: "G-1", record: null },
    { part_id: "p9", record: { id: "rec-x" } },
    { reference: "BAT-1", record: null, rate_per_million_hours: "12.5" },
    { reference: "AF-1", record: { id: "rec-y" }, excluded: true },
  ];
  // A quality factor typed is sent as typed (1 too: left blank, the part type's default grade applies).
  assert.deepEqual(predictionAssign(lines), {
    "C-100": { record_id: "rec-cap", quality_factor: 1 }, "U-7": { record_id: "rec-opto", quality_factor: 3 },
    "G-1": { record_id: null }, p9: { record_id: "rec-x" },
    "BAT-1": { rate_per_million_hours: 12.5 }, "AF-1": { excluded: true },
  });
  assert.equal(predictionWords({ rate_per_million_hours: 12.34, mtbf_hours: 81037 }), "12.3 failures per million hours · MTBF 81,040 hours");
  assert.equal(predictionWords({}), "No part types chosen yet");
});

test("a covariate model's headline names the level it's read at", () => {
  const alt = { kind: "Accelerated life (Weibull)", numbers: [
    { id: "char_life", value: 2121.8, lower: 1788.5, upper: 2478, unit: "Hours" },
    { id: "reference", label: "at", text: "its lowest tested stress (Temperature (°C) 60, Load 0.5)" },
  ] };
  assert.equal(headline(alt), "Life 2,122 hours (1,789–2,478) · at its lowest tested stress (Temperature (°C) 60, Load 0.5)");
});

test("one model in use per position: its chip, its actions, the roll-up and the evidence order", () => {
  const rbdLink = link("r", "pump", { model_type: "rbd", role: "rbd", in_use: false, source: { built_from: 2 },
    model: { name: "Pump (from the tree)", kind: "RBD", family: "rbd", path: "/systems/b/r", unit: "Hours",
      numbers: [{ id: "mtbf", value: 849, unit: "Hours" }], counts: { blocks: 2, placeholders: 1 } } });
  const life = link("l", "pump", { in_use: true });
  const g = graftModels(buildDisplay(DATA, "positions"), [life, rbdLink]);
  const pump = g.rows.get("pump");
  assert.equal(rollupText(pump, true), "2 models · in use: Weibull");
  const rbdRow = g.rows.get(modelKey("r"));
  assert.deepEqual(rowActions(rbdRow).map((a) => a.id), ["model-rbd-pane", "model-page", "model-use", "model-rebuild", "model-unlink"]);
  assert.equal(rowActions(rbdRow).find((a) => a.id === "model-rbd-pane").label, "Open in the pane");
  assert.equal(rowActions(rbdRow).find((a) => a.id === "model-page").label, "Open full page");
  assert.equal(opensInPane(rbdLink), true);
  // A diagram that's gone opens its details (which say so); a life model never opens the builder.
  assert.equal(opensInPane({ ...rbdLink, model: null }), false);
  assert.equal(opensInPane(life), false);
  assert.equal(rowActions({ ref: { ...rbdRow.ref, link: { ...rbdLink, model: null } } })[0].id, "model-open");
  assert.ok(!rowActions(g.rows.get(modelKey("l"))).some((a) => a.id === "model-use"));
  assert.equal(headline(rbdLink.model), "MTBF 849 hours");
  assert.equal(countsText(rbdLink.model), "2 blocks, 1 placeholder");
  assert.equal(inUseWords(rbdLink), "RBD");
  const one = graftModels(buildDisplay(DATA, "positions"), [link("x", "fan", { in_use: true })]);
  assert.ok(!rowActions(one.rows.get(modelKey("x"))).some((a) => a.id === "model-use"));
  assert.equal(rollupText(one.rows.get("fan"), true), "1 model");
  const ev = attachedFor([link("a", "pump", { model_id: "plain" }), link("b", "pump", { model_id: "used", in_use: true })], { expectedType: "model" });
  assert.deepEqual(ev.map((o) => o.id), ["used", "plain"]);
  assert.equal(ev[0].meta, "On this position · in use");
});

test("the Modelling tab's position menu: three groups, two levels", () => {
  const g = attachGroups({ positionClass: "Pump", hasPrediction: true });
  assert.deepEqual(g.map((x) => x.label), ["Life model", "RBD", "Prediction"]);
  assert.deepEqual(g[0].items.map((x) => x.label), ["Fit a life model…", "Assign a saved model…", "From the data library…",
    "From the class…", "Enter parameters…", "Add to a library…"]);
  assert.deepEqual(g[1].items.map((x) => x.label), ["Build from what's inside…", "New blank RBD…", "Link an existing RBD…"]);
  // A leaf: nothing to build from, so a new blank RBD is the way in.
  const leaf = attachGroups({ hasInside: false })[1].items;
  assert.ok(leaf.find((x) => x.id === "model-attach-rbd-build").disabled);
  assert.ok(!leaf.find((x) => x.id === "model-attach-rbd-new").disabled);
  assert.deepEqual(g[2].items.map((x) => x.id), ["model-attach-predict", "model-refresh-predict"]);
  // A position that already has an RBD built from what's inside: the menu opens it, and a rebuild
  // is its own item. Building is never offered twice.
  const had = attachGroups({ builtRbd: true })[1].items;
  assert.deepEqual(had.map((x) => x.label), ["Open the RBD", "Rebuild from what's inside…", "New blank RBD…", "Link an existing RBD…"]);
  assert.deepEqual(had.map((x) => x.id), ["model-attach-rbd-open", "model-attach-rbd-rebuild", "model-attach-rbd-new", "model-attach-rbd-link"]);
  assert.ok(attachGroups({ builtRbd: true, viewOnly: "View only" })[1].items.find((x) => x.id === "model-attach-rbd-rebuild").disabled);
  // Which row that is: an RBD built from the tree on this position (the one in use first); a linked
  // diagram, a life model and another position's RBD are not it.
  const rbds = [link("b1", "pump", { model_id: "r1", model_type: "rbd", source: { built_from: 2 } }),
    link("b2", "pump", { model_id: "r2", model_type: "rbd", source: { built_from: 3 }, in_use: true }),
    link("b3", "pump", { model_id: "r3", model_type: "rbd" }), link("b4", "fan", { model_id: "r4", model_type: "rbd", source: { built_from: 1 } })];
  assert.equal(builtRbdLink(rbds, "pump").model_id, "r2");
  assert.equal(builtRbdLink([rbds[0], rbds[2]], "pump").model_id, "r1");
  assert.equal(builtRbdLink([rbds[2], rbds[3], link("p0", "pump", { model_id: "m0", model: WEIBULL })], "pump"), null);
  assert.equal(builtRbdLink(null, "pump"), null);
  const bare = attachGroups();
  assert.equal(bare[0].items.find((x) => x.id === "model-attach-class").reason, "This position has no class");
  // Add to a library… needs a life model on the position (the one in use, else its first).
  assert.equal(bare[0].items.find((x) => x.id === "model-attach-to-library").reason, "This position has no life model yet");
  assert.ok(!attachGroups({ hasLifeModel: true })[0].items.find((x) => x.id === "model-attach-to-library").disabled);
  const links = [link("p1", "pump", { model_id: "m1", model: WEIBULL }), link("p2", "pump", { model_id: "m2", model: WEIBULL, in_use: true }),
    link("p3", "pump", { model_id: "r", model: WEIBULL, model_type: "rbd", in_use: true }), link("p4", "pump", { model_id: "gone", model: null })];
  assert.equal(lifeModelOf(links, "pump").model_id, "m2");
  assert.equal(lifeModelOf([links[2], links[3]], "pump"), null);
  assert.ok(isLifeModelLink(links[0]) && !isLifeModelLink(links[2]) && !isLifeModelLink({ model_id: "x", model: WEIBULL, role: "prediction" }));
  assert.equal(bare[2].items.length, 1);
  assert.ok(attachGroups({ viewOnly: "View only" }).every((grp) => grp.items.every((x) => x.disabled)));
  assert.deepEqual(MODEL_POSITION_ITEMS, ["tree-rename"]);
});

test("a non-repairable RBD's headline is its mean life, never an MTBF; B10 says why it has no bounds", () => {
  const note = "no bounds: the system curve is exact from the blocks' point models";
  const rbd = { family: "rbd", kind: "RBD", unit: "Hours", numbers: [
    { id: "mean", label: "Mean life", value: 964.2, lower: null, upper: null, unit: "Hours", bound: "", note },
    { id: "b10", label: "B10 life", value: 441.3, lower: null, upper: null, unit: "Hours", bound: "", note },
    { id: "reference", label: "", text: "reliability 61.2% at 500 hours" },
  ] };
  assert.equal(headline(rbd), "Mean life 964 hours · reliability 61.2% at 500 hours");
  assert.doesNotMatch(headline(rbd), /MTBF/);
  assert.equal(b10Text(rbd), "441 hours");
  // A system that may never fail: words, not a number.
  const never = { ...rbd, numbers: [{ id: "mean", label: "Mean life", value: null, text: "not finite (the system may never fail)" }] };
  assert.equal(headline(never), "Mean life not finite (the system may never fail)");
});

// 12 Nov review: a fit with a prior gave the B10 as "3,506–6,994" (90% two-sided)
// while the saved page said "≥ 3,810 at 90% credible". B-lives are one-sided now.
test("a fitted B-life with a prior reads as a one-sided credible bound", () => {
  assert.equal(rangeBound({ point: 5029.8, lower: 3813.5, upper: null, bound: "lower", level: 0.9 }), "≥ 3,814 at 90% credible");
  assert.equal(rangeBound({ point: 582.37, lower: 467.25, upper: null, bound: "lower" }), "≥ 467");
  assert.equal(rangeBound({ median: 13140, lower: 9239, upper: 24970 }), "9,239–24,970");
  assert.equal(rangeBound({ median: 1 }), null);
});
