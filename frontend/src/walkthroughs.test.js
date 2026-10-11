import test from "node:test";
import assert from "node:assert/strict";
import {
  SHEET_MAX_WIDTH,
  WALKTHROUGHS,
  WALKTHROUGH_IDS,
  canGoBack,
  getWalkthrough,
  launchHref,
  move,
  parseLaunch,
  placeCallout,
  rectInView,
  ringRect,
  routeMatches,
  stepFunnel,
  stripLaunch,
  targetsOf,
  withLaunch,
} from "./walkthroughs.js";

test("five walkthroughs, 3–4 steps each, one sentence a step", () => {
  assert.deepEqual(Object.keys(WALKTHROUGHS), WALKTHROUGH_IDS);
  assert.deepEqual(WALKTHROUGH_IDS, ["fit", "replacement", "rbd", "rcm", "fleet"]);
  for (const id of WALKTHROUGH_IDS) {
    const wt = WALKTHROUGHS[id];
    assert.ok(wt.title && wt.route.startsWith("/"), id);
    assert.ok(wt.steps.length >= 3 && wt.steps.length <= 4, `${id}: ${wt.steps.length} steps`);
    for (const step of wt.steps) {
      assert.ok(targetsOf(step).length > 0, `${id}: a step with no target`);
      // One sentence: a single full stop, at the end.
      assert.match(step.text, /^[A-Z].*\.$/, `${id}: ${step.text}`);
      assert.equal(step.text.replace(/\.$/, "").includes(". "), false, `${id}: more than one sentence`);
      // No library names in what users read.
      assert.doesNotMatch(step.text, /surpyval|repyability/i);
    }
  }
});

test("the backend allowlist has the same ids", async () => {
  const { readFile } = await import("node:fs/promises");
  const py = await readFile(new URL("../../backend/services/walkthroughs.py", import.meta.url), "utf8");
  const m = py.match(/WALKTHROUGH_IDS = \(([^)]*)\)/);
  assert.ok(m);
  assert.deepEqual([...m[1].matchAll(/"(\w+)"/g)].map((x) => x[1]), WALKTHROUGH_IDS);
});

test("getWalkthrough: known ids only", () => {
  assert.equal(getWalkthrough("fit").title, "Fit a model");
  assert.equal(getWalkthrough("nope"), null);
  assert.equal(getWalkthrough("toString"), null);
  assert.equal(getWalkthrough(undefined), null);
});

test("targetsOf: one selector or a list", () => {
  assert.deepEqual(targetsOf({ target: ".a" }), [".a"]);
  assert.deepEqual(targetsOf({ target: [".a", ".b"] }), [".a", ".b"]);
  assert.deepEqual(targetsOf({}), []);
  assert.deepEqual(targetsOf(null), []);
});

test("routeMatches: same path and every query value the route sets", () => {
  const r = "/strategy/replacement?model=m1&planned=200";
  assert.equal(routeMatches(r, "/strategy/replacement", "?model=m1&planned=200"), true);
  assert.equal(routeMatches(r, "/strategy/replacement/", "?planned=200&model=m1&x=1"), true);
  assert.equal(routeMatches(r, "/strategy/replacement", "?model=m2&planned=200"), false);
  assert.equal(routeMatches(r, "/strategy/replacement", ""), false);
  assert.equal(routeMatches(r, "/strategy", "?model=m1&planned=200"), false);
  assert.equal(routeMatches("/rcm/studies/s", "/rcm/studies/s", "?anything=1"), true);
});

test("launch links: href, parse and strip", () => {
  assert.equal(launchHref("rcm"), "/rcm/studies/sample-rcm-truck?walkthrough=rcm");
  assert.equal(
    launchHref("fit", { auto: true }),
    "/modelling/new?dataset=sample-ds-bearings&walkthrough=fit&auto=1"
  );
  assert.equal(launchHref("nope"), null);
  assert.deepEqual(parseLaunch("?walkthrough=rbd&auto=1"), { id: "rbd", auto: true });
  assert.deepEqual(parseLaunch("?walkthrough=fleet"), { id: "fleet", auto: false });
  assert.equal(parseLaunch("?walkthrough=nope"), null);
  assert.equal(parseLaunch(""), null);
  assert.equal(stripLaunch("?dataset=d1&walkthrough=fit&auto=1"), "?dataset=d1");
  assert.equal(stripLaunch("?walkthrough=fit"), "");
});

test("withLaunch: only on the walkthrough's own page", () => {
  assert.equal(
    withLaunch("/rbds/b/sample-rbd-pump-station", "rbd", { auto: true }),
    "/rbds/b/sample-rbd-pump-station?walkthrough=rbd&auto=1"
  );
  // Another diagram gets no walkthrough.
  assert.equal(withLaunch("/rbds/b/sample-other", "rbd", { auto: true }), "/rbds/b/sample-other");
  assert.equal(withLaunch("/rbds/b/x", "nope"), "/rbds/b/x");
});

const STEPS = [{}, { next: "click" }, {}, {}];

test("canGoBack: not from the first step, nor past a click", () => {
  assert.equal(canGoBack(STEPS, 0), false);
  assert.equal(canGoBack(STEPS, 1), true);
  assert.equal(canGoBack(STEPS, 2), false); // step 2 ran the fit
  assert.equal(canGoBack(STEPS, 3), true);
});

test("move: next, back, skip and done", () => {
  let run = { index: 0, reached: 0 };
  run = move(run, "next", STEPS);
  assert.deepEqual(run, { index: 1, reached: 1, reachedNew: true, click: false });
  run = move(run, "next", STEPS);
  assert.equal(run.index, 2);
  assert.equal(run.click, true); // the step it left clicks its target
  assert.deepEqual(move(run, "back", STEPS), { index: 2, reached: 2 }); // can't go back past the click
  run = move({ index: 3, reached: 3 }, "back", STEPS);
  assert.deepEqual(run, { index: 2, reached: 3 });
  run = move(run, "next", STEPS);
  assert.equal(run.reachedNew, false); // step 4 was seen already
  assert.equal(move(run, "next", STEPS).done, "completed");
  assert.equal(move({ index: 1, reached: 1 }, "skip", STEPS).done, "skipped");
  assert.deepEqual(move({ index: 1, reached: 1 }, "jump", STEPS), { index: 1, reached: 1 });
});

test("move: a click on the last step still completes", () => {
  const steps = [{}, {}, { next: "click" }];
  const res = move({ index: 2, reached: 2 }, "next", steps);
  assert.equal(res.done, "completed");
  assert.equal(res.click, true);
});

test("ringRect pads the target", () => {
  assert.deepEqual(ringRect({ top: 10, left: 20, width: 100, height: 40 }), {
    top: 4, left: 14, width: 112, height: 52,
  });
});

const VP = { width: 1360, height: 900 };
const SIZE = { width: 320, height: 160 };

test("placeCallout: a bottom sheet on a phone", () => {
  assert.deepEqual(placeCallout({ top: 100, left: 10, width: 50, height: 20 }, SIZE, { width: 390, height: 844 }), {
    mode: "sheet",
  });
  assert.equal(placeCallout({ top: 1, left: 1, width: 1, height: 1 }, SIZE, { width: SHEET_MAX_WIDTH, height: 800 }).mode, "sheet");
});

test("placeCallout: below, else above, else beside, inside the viewport", () => {
  const below = placeCallout({ top: 100, left: 300, width: 200, height: 40 }, SIZE, VP);
  assert.deepEqual(below, { mode: "float", side: "below", top: 152, left: 300 });
  const above = placeCallout({ top: 700, left: 300, width: 200, height: 40 }, SIZE, VP);
  assert.deepEqual(above, { mode: "float", side: "above", top: 528, left: 300 });
  // Tall target: no room above or below, room to the right.
  const right = placeCallout({ top: 100, left: 300, width: 400, height: 700 }, SIZE, VP);
  assert.equal(right.side, "right");
  assert.equal(right.left, 712);
  // Near the right edge: clamped so the callout stays 16 px inside.
  const edge = placeCallout({ top: 100, left: 1300, width: 40, height: 40 }, SIZE, VP);
  assert.equal(edge.left, 1360 - 320 - 16);
  // As big as the screen: over its lower edge, still on screen.
  const huge = placeCallout({ top: 0, left: 0, width: 1360, height: 900 }, SIZE, VP);
  assert.equal(huge.side, "over");
  assert.ok(huge.top >= 16 && huge.top + SIZE.height <= 900 - 16 + 1);
});

test("rectInView keeps the sheet's inset clear", () => {
  assert.equal(rectInView({ top: 100, height: 40 }, { height: 844 }), true);
  assert.equal(rectInView({ top: -10, height: 40 }, { height: 844 }), false);
  assert.equal(rectInView({ top: 700, height: 40 }, { height: 844 }, 200), false);
});

test("stepFunnel: runs reaching each step, in order, zeros included", () => {
  assert.deepEqual(stepFunnel({ steps: { 1: 5, 2: 4, 4: 1 } }, "fit"), [5, 4, 0, 1]);
  assert.deepEqual(stepFunnel({ steps: {} }, "rcm"), [0, 0, 0, 0]);
  assert.deepEqual(stepFunnel({ steps: { 1: 2, 2: 1 } }, "unknown"), [2, 1]);
});
