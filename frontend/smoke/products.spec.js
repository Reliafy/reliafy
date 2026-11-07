// Products and Items: "Add the sample UAV product" on Products (a copy there
// already: Add another copy), the product's page (the tree on its design, its
// facts and sections on the product's Summary, no maintenance tabs), Build an item
// (check first: the positions it will make; then build; the same serial again
// is refused in plain words), the item's page, the failure reports rolled up
// across the items, linking to each on its item, and the Items list with its
// filters. The Assets list leaves the products' trees out. At 400 px nothing
// scrolls the page sideways. smoke/seed.js adds one sample product first.
//
// With SMOKE_SHOTS_DIR set, it also saves screenshots there (for the pull request).
import { test, expect, open, expectHealthy } from "./health.js";

// One after another: building an item writes its tree in steps, and the Assets list is checked meanwhile.
test.describe.configure({ mode: "serial" });

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
// A tab of the panel: on a phone the tabs row shows whole tabs only, so one
// out of view is reached from the keyboard, as a person would with the arrows.
const pickTab = async (page, name) => {
  const tab = page.getByRole("tab", { name, exact: true });
  if (await tab.isVisible()) return tab.click();
  await page.locator("[role=tab][aria-selected=true]").focus();
  for (let i = 0; i < 8 && (await tab.getAttribute("aria-selected")) !== "true"; i++) await page.keyboard.press("ArrowRight");
  return expect(tab).toHaveAttribute("aria-selected", "true");
};

for (const [width, height] of [[1440, 900], [400, 860]]) {
  test(`Products at ${width} px: the sample, the tree on its design, Build an item, the item and the reports roll-up`, async ({ page, request, problems }) => {
    test.setTimeout(300000);
    await page.setViewportSize({ width, height });
    const w = width;
    const phone = width < 600;
    // The seeded sample (smoke/seed.js). Asking for it again offers another copy; keeping ours adds none.
    await open(page, "/products");
    await expect(page.getByRole("heading", { name: "Products", level: 1 })).toBeVisible();
    await shot(page, `${w}-products-landing`);
    await page.getByRole("button", { name: "More actions" }).click();
    await page.getByRole("button", { name: "Add the sample UAV product" }).click();
    await expect(page.getByText("The sample product is already in your workspace")).toBeVisible();
    await shot(page, `${w}-sample-already-there`);
    await page.getByRole("button", { name: "Keep the one I have" }).click();
    await expect(page).toHaveURL(/\/products\/[^/?]+(\?|$)/);
    const product = { id: new URL(page.url()).pathname.split("/").pop() };

    // The product's page is the tree on its design, as Assets › Explorer is:
    // no page header or page tabs, the tree's title the product's name.
    await expect(page.locator(".tp-title")).toContainText("Survey quadcopter (sample");
    await expect(page.getByRole("tab", { name: "Functional structure" })).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "Items", exact: true })).toHaveCount(0);
    await expect(page.locator(".pp-head")).toHaveCount(0);
    await expect(page.getByRole("treeitem", { name: /^Propulsion/ }).first()).toBeVisible();
    await expect(page.getByRole("treeitem", { name: /^Pump station|^Delivery truck/ })).toHaveCount(0);
    // One tree: no Positions / Locations switch, and the tree's last row adds inside the product.
    await expect(page.getByRole("radiogroup", { name: "Arrange by" })).toHaveCount(0);
    await expect(page.locator(".tp-addrow")).toHaveText(/^\+New position inside Survey quadcopter \(sample/);
    // At most one h1: the product's row's name.
    expect(await page.getByRole("heading", { level: 1 }).count()).toBeLessThanOrEqual(1);
    if (phone) await page.getByRole("treeitem", { name: /^Survey quadcopter \(sample/ }).first().click();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Survey quadcopter (sample");
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    // A design has no maintenance: no Failure reports or Signals tab; Parts (the parts list), not Parts and stock.
    await expect(page.getByRole("tab", { name: "RCM" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Parts", exact: true })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Classes" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Failure reports" })).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "Signals" })).toHaveCount(0);
    // The product's facts, in place of an asset's (nothing fitted, no location, no work).
    const facts = page.getByRole("region", { name: "Facts", exact: true });
    await expect(facts).toContainText("Revision");
    await expect(facts).toContainText("SQ-4");
    await expect(facts).not.toContainText("Location");
    await expect(page.getByRole("region", { name: "Work", exact: true })).toHaveCount(0);
    await shot(page, `${w}-product-structure`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);

    // Built items: on the product's Summary; Build an item checks first, then builds.
    const built = page.getByRole("region", { name: "Built items", exact: true });
    await expect(built.locator(".psec-count")).toHaveText(/^\d+$/);
    const before = Number(await built.locator(".psec-count").textContent());
    expect(before).toBeGreaterThanOrEqual(3);
    await built.scrollIntoViewIfNeeded();
    await shot(page, `${w}-product-items`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    const serial = `S${width}-${Date.now() % 100000}`;
    await built.getByRole("button", { name: "Build an item…" }).click();
    const dialog = page.getByRole("dialog", { name: /Build an item/ });
    await dialog.getByLabel("Serial number").fill(serial);
    await dialog.getByRole("button", { name: "Check" }).click();
    await expect(dialog).toContainText("25 positions");
    await expect(dialog.locator(".pp-paths")).toContainText(`· ${serial} › Propulsion › Motor 1`);
    await shot(page, `${w}-build-dry-run`);
    await dialog.getByRole("button", { name: "Build item" }).click();
    await expect(dialog).toBeHidden({ timeout: 120000 }); // copies the design's tree: slow on a busy machine
    await expect(built.locator(".psec-count")).toHaveText(String(before + 1), { timeout: 60000 });
    await expect(page.locator(".pp-said")).toContainText("Built Survey quadcopter");
    // The same serial again: refused, in plain words.
    await built.getByRole("button", { name: "Build an item…" }).click();
    await dialog.getByLabel("Serial number").fill(serial);
    await dialog.getByRole("button", { name: "Check" }).click();
    await expect(dialog).toContainText(`Serial ${serial} is already used by an item of`);
    await dialog.getByRole("button", { name: "Cancel" }).click();
    problems.length = 0; // the refusal's 422 is the page working, not an error

    // Failure reports: rolled up across the items on the Summary, each with its item and place in the design.
    const rollup = page.getByRole("region", { name: "Failure reports on the built items" }).locator(".pp-rollup");
    await expect(rollup).toContainText("2 reports across the items, 2 open");
    await expect(rollup).toContainText("Propulsion › Motor 1");
    await expect(rollup).toContainText("A report is about an item");
    await rollup.scrollIntoViewIfNeeded();
    await shot(page, `${w}-product-reports`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);

    // Analyses of this design: its RBD (placeholder failure rates, said so in its name).
    const analyses = page.getByRole("region", { name: "Analyses of this design" });
    await expect(analyses.getByRole("link", { name: /flight-critical RBD \(placeholder failure rates\)/ })).toBeVisible();
    await analyses.scrollIntoViewIfNeeded();
    await shot(page, `${w}-product-analysis`);

    // A report opens on its item's tree, on the Failure reports tab.
    await rollup.getByRole("link", { name: /^FR-/ }).first().click();
    await expect(page).toHaveURL(/\/asset-register\/explorer\?.*root=.*tab=reports/);
    await expect(page.locator(".fr-detail")).toBeVisible();
    await shot(page, `${w}-report-on-item`);

    // The parts list: the tree's Parts tab (an earlier ?tab=parts lands there), with no stock.
    await open(page, `/products/${product.id}?tab=parts`);
    await expect(page).toHaveURL(/view=parts/);
    if (phone) await page.getByRole("treeitem", { name: /^Survey quadcopter \(sample/ }).first().click();
    await expect(page.getByRole("tab", { name: "Parts", exact: true })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByText("SQ-M2210").first()).toBeVisible();
    // The parts lists in the design: no stock columns, no Stock button.
    await expect(page.locator(".td-tab-page .count")).toContainText(/parts? at Survey quadcopter/);
    await expect(page.locator(".td-tab-page table").first().getByRole("columnheader", { name: "On hand" })).toHaveCount(0);
    await expect(page.locator(".td-tab-page").getByRole("button", { name: "Stock" })).toHaveCount(0);
    await shot(page, `${w}-product-parts`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);

    // The item's own page, from the product's Built items: under Items, with its product.
    await open(page, `/products/${product.id}?tab=items`);
    await expect(page).not.toHaveURL(/tab=items/);
    if (phone) await page.getByRole("treeitem", { name: /^Survey quadcopter \(sample/ }).first().click();
    await page.getByRole("region", { name: "Built items", exact: true }).getByRole("link", { name: "0007", exact: true }).click();
    await expect(page).toHaveURL(/\/asset-register\/items\//);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("· 0007");
    await expect(page.getByRole("link", { name: "Its tree" })).toBeVisible();
    await shot(page, `${w}-item-page`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await expectHealthy(page, problems, { label: `products ${w}` });
  });

  test(`Items at ${width} px: every serial-numbered thing, filtered by product`, async ({ page, problems }) => {
    await page.setViewportSize({ width, height });
    await open(page, "/items");
    await expect(page.getByRole("heading", { name: "Items", level: 1 })).toBeVisible();
    await expect(page.locator(".pp-table")).toContainText("Survey quadcopter (sample) · 0007");
    await shot(page, `${width}-items-landing`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await page.getByLabel("Product").selectOption({ label: "Survey quadcopter (sample)" });
    await expect(page.locator(".tablebar .count")).toHaveText(/^\d+ matches$/);
    await expect(page.locator(".pp-table")).toContainText("· 0007");
    await page.getByLabel("Product").selectOption({ label: "No product" });
    await expect(page.locator(".pp-table")).toContainText("Smoke pump");
    await expect(page.locator('.pp-table a[href^="/products/"]')).toHaveCount(0);
    await expectHealthy(page, problems, { label: `items ${width}` });
  });
}

// The one quadcopter example is the sample product: its functional structure's
// FME(C)A tab works as on the Explorer (scored rows, the row menus of a design,
// Isolate incomplete rows, the print view and back), at both widths.
for (const [width, height] of [[1440, 900], [400, 860]]) {
  test(`the sample UAV product's FME(C)A at ${width} px`, async ({ page, request, problems }) => {
    test.setTimeout(120000);
    await page.setViewportSize({ width, height });
    const { products } = await (await request.get(`${M}/products`)).json();
    const product = products.find((p) => /^Survey quadcopter \(sample/.test(p.name));
    await open(page, `/products/${product.id}?view=fmea&sel=${product.id}`);
    await expect(page.getByRole("tab", { name: "FME(C)A" })).toHaveAttribute("aria-selected", "true");
    if (width < 600) {
      // A phone: the tree, the FME(C)A tab picked; nothing scrolls the page sideways.
      await expect(page.getByText(/Survey quadcopter \(sample/).first()).toBeVisible();
      await shot(page, `${width}-product-fmea`);
      expect(await sideways(page)).toBeLessThanOrEqual(0);
      await expectHealthy(page, problems, { label: `sample product fmea ${width}` });
      return;
    }
    const table = page.getByRole("treegrid", { name: /and their FME\(C\)A/ });
    await expect(table).toBeVisible();
    // The top picked: each assembly's roll-up (Airframe's two modes, both scored).
    await expect(table.getByRole("row", { name: /^Airframe/ }).first()).toContainText("2 of 2 scored");
    await shot(page, `${width}-product-fmea`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    // The design's top row: its FME(C)A menu, with no failure report (a report is about an item).
    const top = table.getByRole("row", { name: /^Survey quadcopter \(sample/ }).first();
    await top.locator(".tt-tree").click({ button: "right" });
    const menu = page.getByRole("menu", { name: /^Actions for Survey quadcopter/ });
    // As on the Explorer's FME(C)A tab: Add function, the worksheet in and out, Print view, Isolate, Pin.
    await expect(menu.getByRole("menuitem")).toHaveText(["Add function", "Import worksheet…", "Export CSV", "Print view", "Isolate", "Pin this branch"]);
    await page.keyboard.press("Escape");
    // The RCM tab: Isolate incomplete rows on the design (the winding and seal modes have no decision).
    await page.getByRole("tab", { name: "RCM" }).click();
    const rcm = page.getByRole("treegrid", { name: /and their RCM/ });
    await rcm.getByRole("row", { name: /^Survey quadcopter \(sample/ }).first().locator(".tt-tree").click({ button: "right" });
    await menu.getByRole("menuitem", { name: "Isolate incomplete rows" }).click();
    await expect(page.locator(".sr-only[role='status']")).toContainText(/Collapsed the rest of the tree: \d+ incomplete rows? under Survey quadcopter/);
    await expect(rcm.getByRole("row", { name: /^Failure mode: / }).first()).toBeVisible();
    await shot(page, `${width}-product-rcm-incomplete`);
    // The print view of a design position, from the FME(C)A tab, and Back to the product's tab.
    await page.getByRole("tab", { name: "FME(C)A" }).click();
    await top.locator(".tt-tree").click({ button: "right" });
    await menu.getByRole("menuitem", { name: "Print view" }).click();
    await expect(page).toHaveURL(new RegExp(`/asset-register/positions/${product.id}/fmea$`));
    const sheet = page.locator("table.fm-sheet");
    await expect(sheet).toBeVisible();
    await expect(sheet.getByRole("row", { name: /Bearing seizure/ }).first()).toContainText("216");
    await shot(page, `${width}-product-fmea-print`);
    await page.getByRole("button", { name: "Back" }).click();
    await expect(page).toHaveURL(new RegExp(`/products/${product.id}\\?.*view=fmea`));
    await expectHealthy(page, problems, { label: `sample product fmea ${width}` });
  });
}

test("Assets leaves the products' designs and items' trees out", async ({ page, request, problems }) => {
  const places = await (await request.get(`${M}/places`)).json();
  const tree = await (await request.get(`${M}/tree`)).json();
  const inProducts = tree.positions.filter((p) => p.design || p.design_position_id).map((p) => p.id);
  expect(inProducts.length).toBeGreaterThan(0);
  for (const id of inProducts) expect(places.not_placed.position_ids).not.toContain(id);
  for (const [width, height] of [[1440, 900], [400, 860]]) {
    await page.setViewportSize({ width, height });
    await open(page, "/asset-register/explorer?arrange=positions");
    await expect(page.getByRole("treeitem").first()).toBeVisible();
    await expect(page.getByRole("treeitem", { name: /^Survey quadcopter/ })).toHaveCount(0);
    await open(page, "/asset-register");
    await expect(page.getByRole("heading", { name: "Assets", level: 1 })).toBeVisible();
    await shot(page, `${width}-assets-landing`);
  }
  await expectHealthy(page, problems, { label: "assets without products" });
});

// With no products (the read answered empty here), the page says what a product is and offers the sample and the guide.
test("Products and Items empty states offer the sample and the guide", async ({ page, problems }) => {
  await page.route("**/api/maintenance/products", (route) => (route.request().method() === "GET"
    ? route.fulfill({ json: { products: [] } }) : route.continue()));
  await page.route("**/api/maintenance/items/overview*", (route) => route.fulfill({
    json: { items: [], total: 0, limit: 100, offset: 0 } }));
  for (const [width, height] of [[1440, 900], [400, 860]]) {
    await page.setViewportSize({ width, height });
    await open(page, "/products");
    const empty = page.locator(".section-empty");
    await expect(empty).toContainText("No products yet");
    await expect(empty.getByRole("button", { name: "Add the sample UAV product" })).toBeVisible();
    await expect(empty.getByRole("button", { name: "How products and items work" })).toBeVisible();
    await shot(page, `${width}-products-empty`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await open(page, "/items");
    await expect(page.locator(".section-empty")).toContainText("No items yet");
    await shot(page, `${width}-items-empty`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
  }
  await expectHealthy(page, problems, { label: "empty products and items" });
});

// Assets and Products: two landing pages of one shape (RegisterList), and the
// asset tree's Parts and stock and Classes tabs (they were pages of their
// own), each scoped to the row picked, with "Show all" for everything.
// smoke/seed.js puts the sample truck in the depot.
for (const [width, height] of [[1440, 900], [400, 860]]) {
  test(`Assets and Products landing pages share one shape at ${width} px`, async ({ page, problems }) => {
    await page.setViewportSize({ width, height });
    const shape = {};
    for (const [path, title, action, first] of [
      ["/asset-register", "Assets", "New asset", "Asset"],
      ["/products", "Products", "New product", "Product"],
    ]) {
      await open(page, path);
      await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
      // The main action top right, one search, the counts line, one table.
      await expect(page.getByRole("button", { name: action }).first()).toBeVisible();
      await expect(page.getByRole("searchbox")).toHaveCount(1);
      await expect(page.locator(".section-tablebar .count")).toHaveText(/\d/);
      await expect(page.locator("table.reg-table")).toHaveCount(1);
      await expect(page.locator("table.reg-table thead th").first()).toHaveText(first);
      await expect(page.locator("table.reg-table tbody tr.lib-row").first()).toBeVisible();
      // No links line under the header (Parts and stock and Classes are tabs of the tree).
      await expect(page.getByRole("navigation", { name: "The asset register" })).toHaveCount(0);
      shape[path] = await page.evaluate(() => {
        const t = document.querySelector("table.reg-table");
        const nums = [...t.querySelectorAll("thead th")].slice(1).map((th) => Math.round(th.getBoundingClientRect().width));
        return { nums, headerAction: !!document.querySelector(".page-head button, header button") };
      });
      await shot(page, `${width}-landing-${title.toLowerCase()}`);
      expect(await sideways(page)).toBeLessThanOrEqual(0);
    }
    if (width > 600) {
      // The number columns are the same width on both (the meaning differs: maintenance on Assets, the design on Products).
      const a = shape["/asset-register"].nums;
      const p = shape["/products"].nums;
      expect(Math.abs(a[0] - p[1])).toBeLessThanOrEqual(2);
    }
    await expectHealthy(page, problems, { label: `landing pages ${width}` });
  });

  test(`Parts and stock and Classes are tabs of the asset tree at ${width} px`, async ({ page, problems }) => {
    await page.setViewportSize({ width, height });
    await open(page, "/asset-register");
    await page.getByRole("link", { name: "Smoke test depot", exact: true }).click();
    await expect(page).toHaveURL(/\/asset-register\/explorer\?arrange=locations&sel=/);
    const sel = new URL(page.url()).searchParams.get("sel");
    // On a phone the panel is its own screen: the tabs head it.
    if (width < 600) {
      await page.getByRole("treeitem", { name: /^Smoke test depot\b/ }).click();
    }
    await pickTab(page, "Parts and stock");
    await expect(page).toHaveURL(/tab=parts/);
    const parts = page.locator(".td-tab-page");
    await expect(parts.locator(".count")).toContainText(/(part|parts) at Smoke test depot and inside it|Parts and stock/);
    await expect(parts.getByLabel("Show all parts")).not.toBeChecked();
    await expect(parts.getByRole("button", { name: "New part" })).toBeVisible();
    await shot(page, `${width}-tab-parts`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await parts.getByLabel("Show all parts").click(); // the address holds it: a controlled box, so click, then wait
    await expect(parts.getByLabel("Show all parts")).toBeChecked();
    await expect(page).toHaveURL(/scope=all/);
    await expect(parts.locator(".count")).toContainText("in the catalogue");
    await expect(parts.getByRole("link", { name: "SMOKE-PUMP" }).first()).toBeVisible();
    await shot(page, `${width}-tab-parts-all`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await parts.getByLabel("Show all parts").click(); // the address holds it: a controlled box, so click, then wait
    await expect(parts.getByLabel("Show all parts")).not.toBeChecked();

    await pickTab(page, "Classes");
    await expect(page).toHaveURL(/tab=classes/);
    const classes = page.locator(".td-tab-page");
    await expect(classes.locator(".count")).toContainText("Classes used at Smoke test depot and inside it");
    await expect(classes.getByRole("heading", { name: "Position classes" })).toBeVisible();
    await expect(classes.getByRole("heading", { name: "Item classes" })).toHaveCount(0);
    await shot(page, `${width}-tab-classes`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await classes.getByLabel("Show all classes").click(); // the address holds it: a controlled box, so click, then wait
    await expect(classes.getByLabel("Show all classes")).toBeChecked();
    await expect(classes.locator(".count")).toContainText("Every class in the register");
    await expect(classes.getByRole("heading", { name: "Item classes" })).toBeVisible();
    // A class opens its panel (the address says which, so a link opens it too).
    await classes.getByRole("button", { name: "Smoke test pump", exact: true }).click();
    await expect(page).toHaveURL(/class=Smoke(%20|\+)test(%20|\+)pump/);
    await expect(page.getByRole("heading", { name: "Smoke test pump: pooled life data" })).toBeVisible();
    await shot(page, `${width}-tab-classes-all`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    expect(sel).toBeTruthy();
    await expectHealthy(page, problems, { label: `parts and classes tabs ${width}` });
  });
}
