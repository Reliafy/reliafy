import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ASSETS_LIST_PATH, NOT_PLACED_PATH, assetOpenPath, assetPath, explorerCarry, assetsSummary, dueText, insideText, openWorkPath, placePath,
  itemHitText, matchesText, positionHitText, siteText,
} from "./maintenanceAssets.js";

test("a place's page, its open work and the positions at no place", () => {
  assert.equal(placePath("l1"), "/asset-register/locations/l1");
  assert.equal(assetPath("l1"), "/asset-register/explorer?arrange=locations&root=l1&sel=l1");
  assert.equal(openWorkPath("l 1"), "/maintenance/work-orders?location=l+1");
  assert.equal(NOT_PLACED_PATH, "/asset-register/explorer?arrange=positions&place=none");
});

test("what's inside and what's due, in words", () => {
  assert.equal(insideText({ locations: 0 }), "");
  assert.equal(insideText({ locations: 1 }), "1 place inside");
  assert.equal(insideText({ locations: 27 }), "27 places inside");
  assert.deepEqual(dueText({ due: 0 }), { text: "Nothing due", overdue: "" });
  // The late line is the shared wording, from the asset's late counts (not its overdue tasks alone).
  assert.deepEqual(dueText({ due: 3, overdue: 1, next_due: "2026-10-01",
    late: { work_orders_late: 2, tasks_overdue_without_work_order: 1 } }, (d) => `on ${d}`),
  { text: "3 due", overdue: "2 work orders late · 1 task overdue with no work order" });
  // A hand-raised work order late with no task due: still said.
  assert.deepEqual(dueText({ due: 0, late: { work_orders_late: 1, tasks_overdue_without_work_order: 0 } }),
    { text: "Nothing due", overdue: "1 work order late" });
  assert.deepEqual(dueText({ due: 1, overdue: 0, next_due: "2026-11-04" }), { text: "1 due, next 2026-11-04", overdue: "" });
});

test("a past date is never said as the next one", () => {
  // Work management off (a plan, so nothing counts as overdue) with an old last done: the
  // date has passed, and the line says so instead of "next 18 May 2023".
  const row = { due: 1, overdue: 0, next_due: "2023-05-18" };
  assert.deepEqual(dueText(row, (d) => d, "2026-11-22"), { text: "1 due, overdue since 2023-05-18", overdue: "" });
  assert.deepEqual(dueText({ ...row, next_due: "2026-11-22" }, (d) => d, "2026-11-22"),
    { text: "1 due, next 2026-11-22", overdue: "" });
  assert.deepEqual(dueText({ ...row, next_due: "2026-12-01" }, (d) => d, "2026-11-22"),
    { text: "1 due, next 2026-12-01", overdue: "" });
});

test("the list's summary line", () => {
  assert.equal(assetsSummary(null), "");
  assert.equal(assetsSummary({ places: [{ positions: 24 }], not_placed: { positions: 13 } }),
    "1 asset · 37 positions · 13 not at a place yet");
  assert.equal(assetsSummary({ places: [{ positions: 2 }, { positions: 1 }], not_placed: { positions: 0 } }),
    "2 assets · 3 positions");
});

test("locationChoices: every place depth first, A to Z, labelled with its path", async () => {
  const { locationChoices } = await import("./maintenanceAssets.js");
  const out = locationChoices([
    { id: "b", name: "Pump hall", parent_id: "a" },
    { id: "a", name: "Riverside" },
    { id: "c", name: "Annex" },
    { id: "d", name: "Store", parent: { id: "c", name: "Annex" } },
  ]);
  assert.deepEqual(out, [
    { id: "c", label: "Annex" },
    { id: "d", label: "Annex › Store" },
    { id: "a", label: "Riverside" },
    { id: "b", label: "Riverside › Pump hall" },
  ]);
  assert.deepEqual(locationChoices(null), []);
});

test("an Explorer address with no asset lands on the Assets list, keeping what it asked for", () => {
  assert.equal(ASSETS_LIST_PATH, "/asset-register");
  const q = (s) => new URLSearchParams(s);
  assert.equal(explorerCarry(q("all=1&sel=p1&arrange=positions&tab=rcm")), "arrange=positions&tab=rcm");
  assert.equal(explorerCarry(q("all=1")), "");
  assert.equal(assetOpenPath("l1", ""), assetPath("l1"));
  assert.equal(assetOpenPath("l1", "arrange=positions&tab=models&fit_prior=r9&root=x"),
    "/asset-register/explorer?arrange=positions&root=l1&sel=l1&tab=models&fit_prior=r9");
});

test("a search result says the asset it's at, the way down and what's fitted", () => {
  const site = { id: "l1", name: "Riverside", kind: "location", unit: null };
  assert.equal(siteText(site), "Riverside");
  assert.equal(siteText({ id: null, name: "", kind: null, unit: null }), "Not at a place yet");
  assert.equal(siteText({ ...site, unit: "UAV · Q-7" }), "UAV · Q-7 at Riverside");
  assert.equal(siteText({ id: "p", name: "UAV · Q-7", kind: "position", unit: "UAV · Q-7" }), "UAV · Q-7");
  assert.deepEqual(positionHitText({ name: "Filter pump", tag: "P-101", path: "Pumping station", site,
                                     item: { name: "Grundfos CR", serial: "SN-42" } }),
                   { title: "P-101 · Filter pump", sub: "Riverside · Pumping station · fitted: Grundfos CR, serial SN-42" });
  assert.deepEqual(positionHitText({ name: "Pump 9", tag: "", path: "", site, item: null }),
                   { title: "Pump 9", sub: "Riverside" });
  assert.deepEqual(itemHitText({ name: "Grundfos CR", serial: "SN-42", site,
                                 where: { how: "fitted", position: { name: "Filter pump" } }, product: null }),
                   { title: "Grundfos CR · serial SN-42", sub: "Riverside · fitted to Filter pump" });
  assert.deepEqual(itemHitText({ name: "UAV · Q-7", serial: "Q-7", site: { name: "" }, where: { how: null },
                                 product: { name: "UAV", built: false } }),
                   { title: "UAV · Q-7", sub: "not fitted or placed · a UAV" });
  assert.equal(itemHitText({ name: "M", serial: "", site, where: { how: "placed", location: { name: "Store" } },
                             product: { name: "UAV", built: true } }).sub, "Riverside · kept at Store · built from UAV");
  // A built item at the top of its own tree: named once, where the tree is.
  const unitSite = { id: "p", name: "UAV · Q-7", kind: "position", unit: "UAV · Q-7" };
  assert.deepEqual(itemHitText({ name: "UAV · Q-7", serial: "Q-7", site: unitSite,
                                 where: { how: "fitted", position: { name: "UAV · Q-7" } }, product: { name: "UAV", built: true } }),
                   { title: "UAV · Q-7", sub: "built from UAV" });
  assert.equal(itemHitText({ name: "UAV · Q-7", serial: "Q-7", site: { ...site, unit: "UAV · Q-7" },
                             where: { how: "fitted", position: { name: "UAV · Q-7" } }, product: { name: "UAV", built: true } }).sub,
               "at Riverside · built from UAV");
  assert.deepEqual(positionHitText({ name: "UAV · Q-7", tag: "", path: "", site: unitSite,
                                     item: { name: "UAV · Q-7", serial: "Q-7" } }),
                   { title: "UAV · Q-7", sub: "fitted: serial Q-7" });
  assert.equal(positionHitText({ name: "UAV · Q-7", tag: "", path: "", site: { ...site, unit: "UAV · Q-7" }, item: null }).sub,
               "at Riverside");
});

test("the search's count line", () => {
  assert.equal(matchesText(null), "");
  assert.equal(matchesText({ positions: [], items: [], positions_total: 0, items_total: 0 }), "");
  assert.equal(matchesText({ positions: [1, 2], items: [1], positions_total: 2, items_total: 1 }),
               "2 positions and 1 item inside your assets");
  assert.equal(matchesText({ positions: [1], items: [], positions_total: 120, items_total: 0 }),
               "first 1 of 120 positions inside your assets");
});
