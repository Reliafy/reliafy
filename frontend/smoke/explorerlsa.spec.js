// The Explorer's LSA tab (Operate › Assets › Explorer, ?tab=lsa; it was the
// Packages tab, and ?tab=packages still opens it): a table of every task on the
// picked row and below it with what each needs, formatted as the RCM table. A
// task's row opens its LSA (?task=): add a labour line and a tool and the
// table's Labour and Tools fill in, and the bar adds up the ticked tasks. Search it (?q=), sort it (a header click, Shift-click for a second
// key: ?sort=), tick two tasks and Package selected… makes a package with
// them: the Package column fills in, and the package's name opens it in the
// tab. At 400 px the table scrolls inside its card, the action bar shows,
// and nothing scrolls the page sideways. A product's design has the tab too:
// what each task needs and the sum of it, with no ticks, packages or due
// dates (those happen on the items built from it), and its links stay on the
// product's page.
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

test("LSA: search and sort the tasks below, tick two and package them", async ({ page, request, problems }) => {
  const tag = `k${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pool.id}`);
  await page.getByRole("tab", { name: "LSA" }).click();
  await expect.poll(() => query(page).get("tab")).toBe("lsa");
  await expect(rows(page)).toHaveCount(3);
  await expect(panel(page).getByRole("columnheader")).toHaveText(
    ["", "Position", "Failure mode", "Task", "Kind", "Interval", "Trade", "Next due", "Package", "Labour", "People", "Tools", "Spares",
      "Consumables", "Method"]);
  await expect((await headMenu(page)).locator(".ovm-menu .ovm-item")).toHaveText(["Columns…", "Export CSV", "Package the tasks…", "Add a package…", "Open the full page"]);
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

// Package the tasks…, then Make: each trade's visit holds tasks on different
// positions (the short one on the battery, its layer's on the alternator), and
// every draft is made.
test("LSA: Package the tasks… makes every draft when a visit's tasks are on different positions", async ({ page, request, problems }) => {
  const tag = `g${Date.now()}`;
  const post = (path, data) => postOk(request, path, data);
  const set = await post(`${M}/positions`, { name: `Genset ${tag}` });
  const battery = await post(`${M}/positions`, { name: `Battery ${tag}`, parent_id: set.id });
  const alternator = await post(`${M}/positions`, { name: `Alternator ${tag}`, parent_id: set.id });
  await post(`${M}/positions/${battery.id}/tasks`, { name: `Test battery ${tag}`, interval: 3, unit: "months", trade: "Electrician" });
  await post(`${M}/positions/${alternator.id}/tasks`, { name: `Load bank test ${tag}`, interval: 6, unit: "months", trade: "Electrician" });
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${set.id}&tab=lsa`);
  await expect(rows(page)).toHaveCount(2);
  await (await headMenu(page)).locator(".ovm-menu .ovm-item", { hasText: "Package the tasks…" }).click();
  const packaging = panel(page).getByRole("region", { name: "Package the tasks" });
  await expect(packaging.locator(".pk-prow")).toHaveCount(2);
  await shot(page, "lsa-package-drafts");
  await packaging.getByRole("button", { name: "Make 2 packages" }).click();
  await expect(panel(page)).toContainText("Made 2 packages.");
  await expect(rows(page)).toHaveCount(2);
  for (const r of await rows(page).all()) await expect(r).toContainText("check (Electrician)");
  await shot(page, "lsa-package-made");
  const made = await (await request.get(`${M}/packages?position_id=${set.id}`)).json();
  expect(made.packages).toHaveLength(2);
  await expectHealthy(page, problems, { label: "Package the tasks, made" });
});

test("LSA: Next due follows a task's first due date (start)", async ({ page, request, problems }) => {
  const tag = `s${Date.now()}`;
  const pool = await postOk(request, `${M}/positions`, { name: `Start pool ${tag}` });
  const year = new Date().getFullYear() + 1;
  await postOk(request, `${M}/positions/${pool.id}/tasks`,
    { name: `Raise the acid dose for summer ${tag}`, interval: 12, unit: "months", start: `${year}-10-01` });
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pool.id}&tab=lsa`);
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toContainText(new RegExp(`Oct.*${year}|${year}.*Oct`));
  await expectHealthy(page, problems, { label: "lsa start", root: ".tx" });
});

test("LSA at 400 px: the table scrolls in its card, the bar shows, nothing scrolls sideways", async ({ page, request }) => {
  const tag = `m${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=packages`); // the old address: opens the LSA tab
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
  // A task's LSA fits too: its lines wrap.
  await panel(page).getByRole("button", { name: `Skim ${tag}`, exact: true }).click();
  await panel(page).getByRole("region", { name: "Labour" }).getByRole("button", { name: "+ Add labour" }).click();
  await panel(page).getByRole("region", { name: "Tools and instruments" }).getByRole("button", { name: "+ Add a tool" }).click();
  await shot(page, "lsa-task-phone");
  expect(await sideways(page)).toBeLessThanOrEqual(400);
});

test("LSA: open a task, add a labour line and a tool, see them in the table and the bar", async ({ page, request, problems }) => {
  const tag = `l${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pool.id}&tab=lsa`);
  await expect(rows(page)).toHaveCount(3);
  await panel(page).getByRole("button", { name: `Test water ${tag}`, exact: true }).click();
  await expect.poll(() => query(page).get("task")).toBeTruthy();
  const labour = panel(page).getByRole("region", { name: "Labour" });
  await labour.getByRole("button", { name: "+ Add labour" }).click();
  await labour.getByRole("textbox", { name: "Trade, line 1" }).fill("Pool technician");
  await labour.getByRole("spinbutton", { name: "Hours each, line 1" }).fill("0.5");
  const tools = panel(page).getByRole("region", { name: "Tools and instruments" });
  await tools.getByRole("button", { name: "+ Add a tool" }).click(); // leaving Labour saves it
  await expect(labour.getByRole("status")).toContainText("Saved");
  await tools.getByRole("textbox", { name: "Tool, line 1" }).fill("Photometer");
  await panel(page).getByRole("textbox", { name: "Method" }).click(); // leaving Tools saves it
  await expect(tools.getByRole("status")).toContainText("Saved");
  await expect(panel(page).locator(".lsa-total")).toContainText("0.5 h labour");
  await shot(page, "lsa-task-desktop");

  await panel(page).getByRole("button", { name: "← All tasks here" }).click();
  await expect.poll(() => query(page).get("task")).toBeNull();
  await expect(rows(page)).toHaveCount(3);
  const row = rows(page).filter({ hasText: `Test water ${tag}` });
  const cols = await panel(page).getByRole("columnheader").allTextContents();
  const cell = (name) => row.getByRole("cell").nth(cols.findIndex((c) => c.startsWith(name)));
  await expect(cell("Labour")).toContainText("0.5 h");
  await expect(cell("Tools")).toHaveText("Photometer");
  await panel(page).getByRole("checkbox", { name: `Tick Test water ${tag}` }).check();
  const bar = panel(page).getByRole("region", { name: "Selected tasks" });
  await expect(bar.getByRole("group", { name: "To bring" })).toContainText("0.5 h (Pool technician 0.5 h)");
  await expect(bar.getByRole("group", { name: "To bring" })).toContainText("Photometer");
  await expectHealthy(page, problems, { label: "lsa task", root: ".tx" });
});

test("a task's LSA and its row on the RCM tab link to each other: Serves → the task's row, Open in LSA → back", async ({ page, request, problems }) => {
  const tag = `k${Date.now()}`;
  const post = (path, data) => postOk(request, path, data);
  const pump = await post(`${M}/positions`, { name: `Package link pump ${tag}` });
  const fn = await post(`${M}/positions/${pump.id}/functions`, { text: `Move water ${tag}` });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `No flow ${tag}` });
  const fm = await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Impeller clogs ${tag}`, functional_failure_id: ff.id });
  const res = await request.put(`${M}/failure-modes/${fm.id}/decision`, {
    data: { consequence: "operational", decision: { outcome: "on_condition", task: `Look in the basket ${tag}`, interval: 1, interval_unit: "weeks" } },
  });
  expect(res.ok()).toBeTruthy();
  const taskId = (await res.json()).decision.task_id;
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pump.id}&tab=lsa&task=${taskId}`);
  const serves = panel(page).locator(".lsa-modes");
  await expect(serves).toContainText(`Impeller clogs ${tag}`);
  // The failure mode it serves: a link to the task's row under it on the RCM tab.
  await serves.getByRole("link", { name: `Impeller clogs ${tag}` }).click();
  await expect.poll(() => query(page).get("tab")).toBe("rcm");
  const table = page.getByRole("treegrid", { name: /and their RCM/ });
  const taskRow = table.getByRole("row", { name: new RegExp(`^Task: Look in the basket ${tag}`) });
  await expect(taskRow).toBeVisible();
  await expect(taskRow).toHaveAttribute("aria-selected", "true");
  // Its details: Logistics, with Open in LSA back to the task's LSA.
  await taskRow.locator(".tp-nm").dblclick();
  const details = page.getByRole("complementary", { name: "Details" });
  const logistics = details.getByRole("region", { name: "Logistics" });
  await expect(logistics).toContainText("No labour, tools or method set yet.");
  await logistics.getByRole("link", { name: "Open in LSA" }).click();
  await expect.poll(() => [query(page).get("tab"), query(page).get("task")]).toEqual(["lsa", taskId]);
  await expect(panel(page).getByRole("heading", { name: `Look in the basket ${tag}` })).toBeVisible();
  await expectHealthy(page, problems, { label: "lsa and rcm task links", root: ".tx" });
});

test("a product's design has the LSA: what each task needs, added up; packaging is on the built items", async ({ page, request, problems }) => {
  const tag = `d${Date.now()}`;
  const post = (path, data) => postOk(request, path, data);
  const product = await post(`${M}/products`, { name: `LSA drone ${tag}`, part_number: `LD-${tag}` });
  const motor = await post(`${M}/positions`, { name: `Motor ${tag}`, parent_id: product.id });
  const fn = await post(`${M}/positions/${motor.id}/functions`, { text: `Turn the propeller ${tag}` });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `No thrust ${tag}` });
  const fm = await post(`${M}/positions/${motor.id}/failure-modes`, { text: `Bearing wears ${tag}`, functional_failure_id: ff.id });
  const res = await request.put(`${M}/failure-modes/${fm.id}/decision`, {
    data: { consequence: "operational", decision: { outcome: "on_condition", task: `Spin the motor by hand ${tag}`, interval: 1, interval_unit: "months" } },
  });
  expect(res.ok()).toBeTruthy();
  const taskId = (await res.json()).decision.task_id;
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/products/${product.id}?view=lsa&sel=${product.id}`);
  await expect(rows(page)).toHaveCount(1);
  // The asset's table less ticks, Next due and Package; the heading's "…" less packaging.
  await expect(panel(page).getByRole("columnheader")).toHaveText(
    ["Position", "Failure mode", "Task", "Kind", "Interval", "Trade", "Labour", "People", "Tools", "Spares", "Consumables", "Method"]);
  await expect(panel(page).getByRole("checkbox")).toHaveCount(0);
  await expect((await headMenu(page)).locator(".ovm-menu .ovm-item")).toHaveText(["Columns…", "Export CSV", "Open the full page"]);
  await page.keyboard.press("Escape");
  await expect(panel(page).locator(".pk-purpose")).toContainText("packaged into visits on the items built from it");
  const foot = panel(page).getByRole("region", { name: "What the tasks need" });
  await expect(foot).toContainText("1 task");
  await expect(foot).toContainText("No labour, tools or spares set yet");

  // A task's LSA, as on an asset: a labour line, then the table and the sum show it.
  await panel(page).getByRole("button", { name: `Spin the motor by hand ${tag}`, exact: true }).click();
  await expect.poll(() => query(page).get("task")).toBe(taskId);
  const labour = panel(page).getByRole("region", { name: "Labour" });
  await labour.getByRole("button", { name: "+ Add labour" }).click();
  await labour.getByRole("textbox", { name: "Trade, line 1" }).fill("Drone technician");
  await labour.getByRole("spinbutton", { name: "Hours each, line 1" }).fill("0.25");
  await panel(page).getByRole("textbox", { name: "Method" }).click(); // leaving Labour saves it
  await expect(labour.getByRole("status")).toContainText("Saved");
  await shot(page, "lsa-design-task");
  // Serves: the task's row on the design's RCM tab, still on the product's page.
  await panel(page).locator(".lsa-modes").getByRole("link", { name: `Bearing wears ${tag}` }).click();
  await expect(page).toHaveURL(new RegExp(`/products/${product.id}\\?.*view=rcm`));
  const taskRow = page.getByRole("treegrid", { name: /and their RCM/ }).getByRole("row", { name: new RegExp(`^Task: Spin the motor by hand ${tag}`) });
  await expect(taskRow).toHaveAttribute("aria-selected", "true");
  // Its details: Open in LSA, back to the design's LSA on the same page.
  await taskRow.locator(".tp-nm").dblclick();
  const logistics = page.getByRole("complementary", { name: "Details" }).getByRole("region", { name: "Logistics" });
  await expect(logistics).toContainText("0.25 labour hours");
  await logistics.getByRole("link", { name: "Open in LSA" }).click();
  await expect(page).toHaveURL(new RegExp(`/products/${product.id}\\?.*view=lsa`));
  await expect.poll(() => query(page).get("task")).toBe(taskId);
  await panel(page).getByRole("button", { name: "← All tasks here" }).click();
  await expect(panel(page).getByRole("region", { name: "What the tasks need" }).getByRole("group", { name: "Together they need" }))
    .toContainText("Drone technician");
  await shot(page, "lsa-design-table");
  await expectHealthy(page, problems, { label: "design lsa", root: ".tx" });
});
