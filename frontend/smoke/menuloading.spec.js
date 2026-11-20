// A menu click on a page whose code hasn't loaded yet shows "Loading…" at
// once, never the page you left under the new address. The page's code is
// held back by a second, as on a slow connection, so the gap can be seen.
import { test, expect, open, expectHealthy } from "./health.js";

const mainMenu = (page) => page.locator('nav[aria-label="Main"]');

// Open every group in the menu, so each entry's link is on screen.
async function openGroups(page) {
  for (let i = 0; i < 4; i++) {
    const closed = mainMenu(page).locator('button[aria-expanded="false"]');
    if (!(await closed.count())) break;
    await closed.first().click();
  }
}

for (const width of [1440, 400]) {
  test(`a menu click shows Loading, not the page left behind, at ${width} px`, async ({ page, problems }) => {
    await page.setViewportSize({ width, height: 900 });
    await open(page, "/home");
    const home = await page.locator("main").innerText();

    let release;
    const held = new Promise((resolve) => { release = resolve; });
    await page.route("**/assets/*.js", async (route) => {
      await Promise.race([held, new Promise((r) => setTimeout(r, 1000))]);
      await route.continue();
    });

    if (width < 700) await page.getByRole("button", { name: "Menu", exact: true }).click();
    await openGroups(page);
    await mainMenu(page).locator('a[href="/data"]').first().click();
    await expect(page).toHaveURL(/\/data$/);
    await expect(page.locator("main .view-loading")).toBeVisible({ timeout: 500 });
    expect(await page.locator("main").innerText()).not.toBe(home);

    release();
    await expect(page.locator("main .view-loading")).toHaveCount(0, { timeout: 15000 });
    await expect(page.locator("main")).not.toHaveText(home);
    await expectHealthy(page, problems, { label: `/data after a menu click at ${width} px` });
  });
}
