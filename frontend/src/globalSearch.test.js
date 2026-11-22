import { test } from "node:test";
import assert from "node:assert/strict";
import {
  contextLine, featureHref, featureList, flatResults, highlight, matchTier, mergeGroups, moveActive, near,
  searchFeatures, searchGuides, SYNONYMS,
} from "./globalSearch.js";
import { flatEntries, liveEntries } from "./navigation.js";
import { OFFERED_TABS } from "./explorerTabs.js";

const ALL = { maintenance: true, agent: true, risk: true, work_orders: true };

test("ranks exact, prefix, whole words, inside, then near spellings, as the server does", () => {
  assert.equal(matchTier("oil filter", ["Oil filter"]), 0);
  assert.equal(matchTier("oil filter", ["Oil filter element"]), 1);
  assert.equal(matchTier("oil filter", ["Engine oil filter"]), 2);
  assert.equal(matchTier("oil filter", ["Foil filters"]), 3);
  assert.equal(matchTier("genrator", ["Portable generator set"]), 4);
  assert.equal(matchTier("generatro", ["Portable generator set"]), 4);
  assert.equal(matchTier("avx", ["AVR mk 2"]), null); // short words only as typed
  assert.equal(matchTier("genxxtxr", ["Portable generator set"]), null);
  assert.equal(matchTier("P-101", ["Filter pump", "P-101"]), 0);
  assert.equal(matchTier("gs-1001", ["TP-1001 · Transfer pump"]), null); // codes only as typed
  assert.equal(matchTier("  ", ["x"]), null);
  assert.equal(near("filtr", "filter"), true);
  assert.equal(near("pump", "pimp"), true);
  assert.equal(near("pump", "plum"), false); // two edits in a short word
  assert.equal(near("pum", "pun"), false);
  assert.equal(near("mower", "lower"), false); // another first letter: another word
  assert.equal(near("mower", "power"), false);
  assert.equal(near("omwer", "mower"), true);
});

test("the pages come from the live menu, so a page this workspace lacks isn't offered", () => {
  const features = featureList({ live: liveEntries(ALL), has: ALL });
  const paths = new Set(features.map((f) => f.path));
  for (const e of flatEntries(liveEntries(ALL))) {
    assert.ok(paths.has(e.to), `${e.label} is searchable`);
    for (const c of e.children || []) assert.ok(paths.has(c.to), `${c.label} is searchable`);
  }
  // Without Reliafy Maintenance: no Products, Assets, Orders, Packages, and no Explorer tabs.
  const plain = featureList({ live: liveEntries({}), has: {} });
  const plainPaths = new Set(plain.map((f) => f.path));
  for (const p of ["/products", "/asset-register", "/maintenance/work-orders", "/maintenance/packages"]) {
    assert.ok(!plainPaths.has(p), p);
  }
  assert.ok(!plain.some((f) => f.tab));
  assert.ok(plainPaths.has("/maintenance/rcm") && plainPaths.has("/strategy/test-planning"));
  // Work management off: no Orders.
  const noOrders = featureList({ live: liveEntries({ ...ALL, work_orders: false }), has: { ...ALL, work_orders: false } });
  assert.ok(!noOrders.some((f) => f.path === "/maintenance/work-orders"));
  // Billing and the team page only where they exist.
  assert.ok(!plainPaths.has("/billing") && !plainPaths.has("/team"));
  const both = featureList({ live: liveEntries({}), has: {}, billing: true, team: true });
  assert.ok(both.some((f) => f.path === "/billing") && both.some((f) => f.path === "/team"));
  // One entry per page: RBDs and System models share one.
  assert.equal(features.filter((f) => f.path === "/systems/rbds").length, 1);
});

test("every Explorer tab on offer is a place to go, and the hidden ones aren't", () => {
  const features = featureList({ live: liveEntries(ALL), has: ALL });
  const tabs = features.filter((f) => f.tab).map((f) => f.tab);
  assert.deepEqual(tabs, OFFERED_TABS.filter((t) => t.id !== "summary").map((t) => t.id));
  const missions = features.find((f) => f.tab === "missions");
  assert.equal(missions.path, "/asset-register/explorer?arrange=positions&tab=missions");
  // On an asset already open, the tab opens there.
  assert.equal(featureHref(missions, "/asset-register/explorer", "?arrange=positions&root=r1&sel=p1"),
    "/asset-register/explorer?arrange=positions&root=r1&sel=p1&tab=missions");
  assert.equal(featureHref(missions, "/home", ""), missions.path);
  // Every synonym's address is a page or a tab somewhere.
  for (const key of Object.keys(SYNONYMS)) {
    if (key.startsWith("tab:")) continue;
    assert.ok(key.startsWith("/"), key);
  }
});

test("a feature is found by the words people use for it", () => {
  const features = featureList({ live: liveEntries(ALL), has: ALL, billing: true });
  const top = (q) => searchFeatures(features, q).results[0];
  assert.equal(top("test planning").path, "/strategy/test-planning");
  assert.equal(top("spares").tier, 0);
  assert.ok(["/forecasts", "tab:spares"].includes(top("spares").id));
  assert.equal(top("FMECA").tab, "fmea");
  assert.equal(top("rcm").tier, 0);
  assert.equal(top("fleet forecast").tier, 0);
  assert.equal(top("missions").tab, "missions");
  assert.equal(top("condition monitoring").tier, 0);
  assert.equal(top("bom import").path, "/products");
  assert.equal(top("api keys").path, "/settings?tab=api");
  assert.equal(top("availability").tier, 0);
  assert.equal(top("tset planning").path, "/strategy/test-planning"); // a typo
  assert.equal(searchFeatures(features, "zzzz").results.length, 0);
});

test("guides: the drawer's filter, near spellings of a title, title matches first", () => {
  const guides = [
    { slug: "a", title: "Fit a Weibull", task: "From a CSV", body: "shape and scale" },
    { slug: "b", title: "Build an RBD", task: "Blocks", body: "uses a weibull per block" },
    { slug: "c", title: "Plan a test", task: "", body: "" },
  ];
  assert.deepEqual(searchGuides(guides, "weibull").results.map((g) => g.slug), ["a", "b"]);
  assert.deepEqual(searchGuides(guides, "wiebull").results.map((g) => g.slug), ["a"]);
  assert.deepEqual(searchGuides(guides, "shape").results.map((g) => g.slug), ["a"]);
  assert.equal(searchGuides(guides, "nothing like it").results.length, 0);
});

const g = (kind, tiers) => ({ kind, label: kind, total: tiers.length, results: tiers.map((tier, i) => ({ id: `${kind}${i}`, tier })) });

test("groups: the best match's group first; ties keep records, then pages, then guides", () => {
  const merged = mergeGroups([g("part", [2, 3]), g("model", [0])], g("feature", [0]), g("guide", [1]));
  assert.deepEqual(merged.map((x) => x.kind), ["model", "feature", "guide", "part"]);
  assert.deepEqual(mergeGroups([], g("feature", []), null), []);
  // Near spellings drop out when anything matches as typed; kept when nothing does.
  const real = mergeGroups([g("asset", [4, 4]), g("model", [2])], g("feature", [4]), null);
  assert.deepEqual(real.map((x) => [x.kind, x.results.length, x.total]), [["model", 1, 1]]);
  assert.equal(mergeGroups([g("asset", [4])], null, null)[0].results.length, 1);
});

test("keyboard: arrows wrap, Tab jumps to the next group's first result, past the last it's the page's", () => {
  const groups = [g("a", [0, 1]), g("b", [1]), g("c", [2, 3])];
  assert.equal(flatResults(groups).length, 5);
  assert.equal(moveActive(groups, 0, "ArrowDown"), 1);
  assert.equal(moveActive(groups, 4, "ArrowDown"), 0);
  assert.equal(moveActive(groups, 0, "ArrowUp"), 4);
  assert.equal(moveActive(groups, 1, "Tab"), 2);
  assert.equal(moveActive(groups, 2, "Tab"), 3);
  assert.equal(moveActive(groups, 3, "Tab"), null);
  assert.equal(moveActive(groups, 3, "Tab", true), 2);
  assert.equal(moveActive(groups, 0, "Tab", true), null);
  assert.equal(moveActive(groups, 2, "End"), 4);
  assert.equal(moveActive(groups, 0, "x"), null);
  assert.equal(moveActive([], 0, "ArrowDown"), null);
});

test("highlighting and the context line", () => {
  assert.deepEqual(highlight("Oil filter OF-200", "of-200 oil"), [
    { text: "Oil", hit: true }, { text: " filter ", hit: false }, { text: "OF-200", hit: true }]);
  assert.deepEqual(highlight("x", ""), [{ text: "x", hit: false }]);
  assert.equal(contextLine({ context: "Data", updated_at: "2026-11-03T00:00:00Z", sample: true }),
    "Data · updated 3 Nov 2026 · Sample");
  assert.equal(contextLine({ context: "Part · 3 on hand" }), "Part · 3 on hand");
});
