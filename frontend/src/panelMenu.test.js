import { test } from "node:test";
import assert from "node:assert/strict";
import { menuKey, withFullPage } from "./panelMenu.js";

test("menuKey changes with what the menu says, not with fresh closures", () => {
  const a = [{ id: "add", label: "Add a measuring point…", onSelect: () => 1 }];
  const b = [{ id: "add", label: "Add a measuring point…", onSelect: () => 2 }];
  assert.equal(menuKey(a), menuKey(b));
  assert.notEqual(menuKey(a), menuKey([{ ...a[0], disabled: true }]));
  assert.notEqual(menuKey(a), menuKey([{ ...a[0], title: "Pick a position first" }]));
  assert.notEqual(menuKey(a), menuKey([...a, { id: "export", label: "Export CSV" }]));
  assert.equal(menuKey(null), "");
  assert.equal(menuKey([null, false]), "");
});

test("withFullPage puts Open the full page last, only where the row has a page", () => {
  const items = [{ id: "import", label: "Import worksheet…" }, null];
  assert.deepEqual(withFullPage(items, "/asset-register/positions/p1").map((i) => i.label),
    ["Import worksheet…", "Open the full page"]);
  assert.equal(withFullPage(items, "/asset-register/positions/p1").at(-1).to, "/asset-register/positions/p1");
  assert.deepEqual(withFullPage(items, null).map((i) => i.id), ["import"]);
  assert.deepEqual(withFullPage(undefined, null), []);
});
