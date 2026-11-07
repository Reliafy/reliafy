// The Explorer's Packages tab (Operate › Assets › Explorer, ?tab=packages): a
// table of every task on the picked row and below it, formatted as the RCM
// table. Search it (?q=), sort it (a header click, Shift-click for a second
// key: ?sort=), tick two tasks and Package selected… makes a package with
// them: the Package column fills in, and the package's name opens it in the
// tab. At 400 px the table scrolls inside its card, the action bar shows,
// and nothing scrolls the page sideways.
// Each test makes its own small plant through the API.
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
const rows = (page) => panel(page).locator(".pk-trow");
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth);

test("Packages: search and sort the tasks below, tick two and package them", async ({ page, request, problems }) => {
  const tag = `k${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pool.id}`);
  await page.getByRole("tab", { name: "Packages" }).click();
  await expect.poll(() => query(page).get("tab")).toBe("packages");
  await expect(rows(page)).toHaveCount(3);
  await expect(panel(page).getByRole("columnheader")).toHaveText(
    ["", "Position", "Failure mode", "Task", "Kind", "Interval", "Trade", "Next due", "Package"]);
  await expect((await headMenu(page)).locator(".ovm-menu .ovm-item")).toHaveText(["Columns…", "Package the tasks…", "Add a package…", "Open the full page"]);
  await page.keyboard.press("Escape");

  // Search: every column; kept in the address.
  const search = panel(page).getByRole("searchbox", { name: "Search the tasks" });
  await search.fill("water");
  await expect(rows(page)).toHaveCount(1);
  await expect.poll(() => query(page).get("q")).toBe("water");
  await search.fill("");
  await expect(rows(page)).toHaveCount(3);

  // Sort: by interval (the monthly one last), then Shift-click Task for a second key.
  await panel(page).getByRole("button", { name: /^Interval: sort/ }).click();
  await expect.poll(() => query(page).get("sort")).toBe("interval");
  await expect(rows(page).last()).toContainText(`Clean cell ${tag}`);
  await panel(page).getByRole("button", { name: /^Task: sort/ }).click({ modifiers: ["Shift"] });
  await expect.poll(() => query(page).get("sort")).toBe("interval,task");
  await expect(rows(page).first()).toContainText(`Skim ${tag}`);

  // Tick the two weekly tasks: the bar offers Package selected…
  await panel(page).getByRole("checkbox", { name: `Tick Skim ${tag}` }).check();
  await panel(page).getByRole("checkbox", { name: `Tick Test water ${tag}` }).check();
  const bar = panel(page).getByRole("region", { name: "Selected tasks" });
  await expect(bar).toContainText("2 tasks selected");
  await shot(page, "packages-table-desktop");
  await bar.getByRole("button", { name: "Package selected…" }).click();
  const dialog = page.getByRole("dialog", { name: "Package 2 tasks" });
  await expect(dialog.getByRole("spinbutton", { name: "Every" })).toHaveValue("1");
  await expect(dialog.getByRole("combobox", { name: "Unit" })).toHaveValue("weeks");
  await dialog.getByRole("textbox", { name: "Name" }).fill(`Pool weekly ${tag}`);
  await dialog.getByRole("button", { name: "Make package" }).click();
  await expect(dialog).toHaveCount(0);

  // The Package column fills in; the bar goes.
  await expect(panel(page).getByRole("button", { name: `Pool weekly ${tag}` })).toHaveCount(2);
  await expect(bar).toHaveCount(0);
  await panel(page).getByRole("button", { name: `Pool weekly ${tag}` }).first().click();
  await expect.poll(() => query(page).get("package")).toBeTruthy();
  await expect(panel(page).locator(".pk-member")).toHaveCount(2);
  await panel(page).getByRole("button", { name: "← All packages here" }).click();
  await expect(rows(page)).toHaveCount(3);
  await expectHealthy(page, problems, { label: "packages", root: ".tx" });
});

test("Packages at 400 px: the table scrolls in its card, the bar shows, nothing scrolls sideways", async ({ page, request }) => {
  const tag = `m${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=packages`);
  // On a phone the panel is its own screen: tap the row to open it.
  await page.getByRole("treeitem", { name: new RegExp(`^Package pump ${tag}`) }).locator(".tp-nm").click();
  await expect(rows(page)).toHaveCount(3);
  expect(await sideways(page)).toBeLessThanOrEqual(400);
  await panel(page).getByRole("checkbox", { name: `Tick Skim ${tag}` }).check();
  const bar = panel(page).getByRole("region", { name: "Selected tasks" });
  await expect(bar).toBeVisible();
  await shot(page, "packages-table-phone-ticked");
  expect(await sideways(page)).toBeLessThanOrEqual(400);
  await bar.getByRole("button", { name: "Package selected…" }).click();
  const dialog = page.getByRole("dialog", { name: "Package 1 task" });
  await dialog.getByRole("textbox", { name: "Name" }).fill(`Pump weekly ${tag}`);
  expect(await sideways(page)).toBeLessThanOrEqual(400);
  await dialog.getByRole("button", { name: "Make package" }).click();
  await expect(panel(page).getByRole("button", { name: `Pump weekly ${tag}` })).toHaveCount(1);
  await shot(page, "packages-table-phone");
  expect(await sideways(page)).toBeLessThanOrEqual(400);
});
