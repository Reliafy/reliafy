// Products and Items: "Add the sample UAV product" on Products (a copy there
// already: Add another copy), the product's page and its tabs, Build an item
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

for (const [width, height] of [[1440, 900], [400, 860]]) {
  test(`Products at ${width} px: the sample, its tabs, Build an item, the item and the reports roll-up`, async ({ page, request, problems }) => {
    test.setTimeout(300000);
    await page.setViewportSize({ width, height });
    const w = width;
    // The seeded sample (smoke/seed.js). Asking for it again offers another copy; keeping ours adds none.
    await open(page, "/products");
    await expect(page.getByRole("heading", { name: "Products", level: 1 })).toBeVisible();
    await shot(page, `${w}-products-landing`);
    await page.getByRole("button", { name: "More actions" }).click();
    await page.getByRole("button", { name: "Add the sample UAV product" }).click();
    await expect(page.getByText("The sample product is already in your workspace")).toBeVisible();
    await shot(page, `${w}-sample-already-there`);
    await page.getByRole("button", { name: "Keep the one I have" }).click();
    await expect(page).toHaveURL(/\/products\/[^/?]+$/);
    const product = { id: new URL(page.url()).pathname.split("/").pop() };
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Survey quadcopter (sample");

    // Functional structure: the design's tree alone, by position.
    await expect(page.getByRole("tab", { name: "Functional structure" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("treeitem", { name: /^Propulsion/ }).first()).toBeVisible();
    await expect(page.getByRole("treeitem", { name: /^Pump station|^Delivery truck/ })).toHaveCount(0);
    await shot(page, `${w}-product-structure`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);

    // Parts list: the part's bill of materials.
    await page.getByRole("tab", { name: "Parts list" }).click();
    await expect(page).toHaveURL(/tab=parts/);
    await expect(page.getByText("SQ-M2210").first()).toBeVisible();
    await shot(page, `${w}-product-parts`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);

    // Items: three built; Build an item checks first, then builds.
    await page.getByRole("tab", { name: "Items", exact: true }).click();
    const heading = page.getByRole("heading", { name: /^\d+ items? built$/ });
    await expect(heading).toBeVisible();
    const before = Number((await heading.textContent()).split(" ")[0]);
    expect(before).toBeGreaterThanOrEqual(3);
    await shot(page, `${w}-product-items`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    const serial = `S${width}-${Date.now() % 100000}`;
    await page.getByRole("button", { name: "Build an item" }).first().click();
    const dialog = page.getByRole("dialog", { name: /Build an item/ });
    await dialog.getByLabel("Serial number").fill(serial);
    await dialog.getByRole("button", { name: "Check" }).click();
    await expect(dialog).toContainText("25 positions");
    await expect(dialog.locator(".pp-paths")).toContainText(`· ${serial} › Propulsion › Motor 1`);
    await shot(page, `${w}-build-dry-run`);
    await dialog.getByRole("button", { name: "Build item" }).click();
    await expect(dialog).toBeHidden({ timeout: 120000 }); // copies the design's tree: slow on a busy machine
    await expect(page.getByRole("heading", { name: new RegExp(`^${before + 1} items built$`) })).toBeVisible({ timeout: 60000 });
    await expect(page.getByRole("status")).toContainText(`Built Survey quadcopter`);
    // The same serial again: refused, in plain words.
    await page.getByRole("button", { name: "Build an item" }).first().click();
    await dialog.getByLabel("Serial number").fill(serial);
    await dialog.getByRole("button", { name: "Check" }).click();
    await expect(dialog).toContainText(`Serial ${serial} is already used by an item of`);
    await dialog.getByRole("button", { name: "Cancel" }).click();
    problems.length = 0; // the refusal's 422 is the page working, not an error

    // Failure reports: rolled up across the items, each with its item and place in the design.
    await page.getByRole("tab", { name: "Failure reports" }).click();
    const rollup = page.locator(".pp-rollup");
    await expect(rollup).toContainText("2 reports across the items, 2 open");
    await expect(rollup).toContainText("Propulsion › Motor 1");
    await expect(rollup).toContainText("A report is about an item");
    await shot(page, `${w}-product-reports`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);

    // Analysis: its RBD (placeholder failure rates, said so in its name).
    await page.getByRole("tab", { name: "Analysis" }).click();
    await expect(page.getByRole("link", { name: /flight-critical RBD \(placeholder failure rates\)/ })).toBeVisible();
    await shot(page, `${w}-product-analysis`);

    // A report opens on its item's tree, on the Failure reports tab.
    await page.getByRole("tab", { name: "Failure reports" }).click();
    await rollup.getByRole("link", { name: /^FR-/ }).first().click();
    await expect(page).toHaveURL(/\/asset-register\/explorer\?.*root=.*tab=reports/);
    await expect(page.locator(".fr-detail")).toBeVisible();
    await shot(page, `${w}-report-on-item`);

    // The item's own page, from the product's Items tab: under Items, with its product.
    await open(page, `/products/${product.id}?tab=items`);
    await page.getByRole("link", { name: "0007", exact: true }).click();
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
