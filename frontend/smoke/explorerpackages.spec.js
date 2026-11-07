// The Explorer's Packages tab (Operate › Assets › Explorer, ?tab=packages):
// a position with weekly and monthly tasks shows the empty state; the
// heading's "…" › Package the tasks… proposes a weekly package with the
// monthly tasks as a layer on it, and making them lists the package with its
// layer under it; a package opens in the tab with its tasks. At 400 px the
// empty state's own link opens the same dialog and nothing scrolls sideways.
// Each test makes its own small plant through the API.
//
// With SMOKE_SHOTS_DIR set, it also saves screenshots there (for the pull request).
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { headMenu } from "./explorer.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};

async function plant(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const pool = await post(`${M}/positions`, { name: `Package pool ${tag}` });
  const pump = await post(`${M}/positions`, { name: `Package pump ${tag}`, parent_id: pool.id });
  for (const [name, interval, unit] of [["Skim", 1, "weeks"], ["Test water", 1, "weeks"], ["Clean cell", 1, "months"]]) {
    await post(`${M}/positions/${pump.id}/tasks`, { name: `${name} ${tag}`, interval, unit });
  }
  return { pool, pump };
}

const query = (page) => new URL(page.url()).searchParams;
const panel = (page) => page.locator(".pk-panel");
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth);

test("Packages: empty, then Package the tasks… makes a weekly package with its monthly layer", async ({ page, request, problems }) => {
  const tag = `k${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pool.id}`);
  await page.getByRole("tab", { name: "Packages" }).click();
  await expect.poll(() => query(page).get("tab")).toBe("packages");
  await expect(panel(page)).toContainText("No packages here yet");
  await expect(panel(page).getByRole("button", { name: "How work packages work" })).toBeVisible();
  await expect((await headMenu(page)).locator(".ovm-menu .ovm-item")).toHaveText(["Package the tasks…", "Add a package…", "Open the full page"]);
  await page.locator(".ovm-menu").getByRole("button", { name: "Package the tasks…" }).click();

  const dialog = page.getByRole("dialog", { name: "Package the tasks" });
  await expect(dialog.locator(".pk-prow")).toHaveCount(2);
  await expect(dialog).toContainText("Every Saturday");
  await expect(dialog).toContainText("The first Saturday of every month");
  await shot(page, "packages-desktop-propose");
  await dialog.getByRole("button", { name: "Make 2 packages" }).click();
  await expect(dialog).toHaveCount(0);

  const rows = panel(page).locator(".pk-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText(`Package pool ${tag} weekly check`);
  await expect(rows.nth(1)).toHaveClass(/pk-layer/);
  await expect(rows.nth(1)).toContainText("monthly check");
  await shot(page, "packages-desktop-list");

  // A package opens in the tab, with its tasks and the layer.
  await rows.nth(0).getByRole("button").first().click();
  await expect.poll(() => query(page).get("package")).toBeTruthy();
  await expect(panel(page).locator(".pk-member")).toHaveCount(3); // two tasks and the layer
  await expect(panel(page)).toContainText(`Skim ${tag}`);
  await expect(panel(page)).toContainText("every visit");
  await panel(page).getByRole("button", { name: "← All packages here" }).click();
  await expect(rows).toHaveCount(2);
  await expectHealthy(page, problems, { label: "packages", root: ".tx" });
});

test("Packages at 400 px: the empty state opens Package the tasks… and nothing scrolls sideways", async ({ page, request }) => {
  const tag = `m${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=packages`);
  // On a phone the panel is its own screen: tap the row to open it.
  await page.getByRole("treeitem", { name: new RegExp(`^Package pump ${tag}`) }).locator(".tp-nm").click();
  await expect(panel(page)).toContainText("No packages here yet");
  expect(await sideways(page)).toBeLessThanOrEqual(400);
  await panel(page).getByRole("button", { name: "Package the tasks…" }).click();
  const dialog = page.getByRole("dialog", { name: "Package the tasks" });
  await expect(dialog.locator(".pk-prow")).toHaveCount(2);
  expect(await sideways(page)).toBeLessThanOrEqual(400);
  await shot(page, "packages-phone-propose");
  await dialog.getByRole("button", { name: "Make 2 packages" }).click();
  await expect(panel(page).locator(".pk-row")).toHaveCount(2);
  expect(await sideways(page)).toBeLessThanOrEqual(400);
  await shot(page, "packages-phone-list");
});
