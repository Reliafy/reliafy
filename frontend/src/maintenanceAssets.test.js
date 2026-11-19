import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ASSETS_LIST_PATH, NOT_PLACED_PATH, assetOpenPath, assetPath, explorerCarry, assetsSummary, dueText, insideText, openWorkPath, placePath,
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
