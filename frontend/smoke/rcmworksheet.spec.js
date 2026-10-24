// The RCM study's worksheet (an outline grid): open and close, the levels,
// the filter and chips that keep the path to a match, the column chooser,
// the details panel and in-place edits saved with the study, the decision
// dialog, the Tree view still there, the phone's two-line rows, and a study
// of about 2,000 rows (only the rows on screen in the page). Each test makes
// its own study through the API: a house pool pump, invented.
import { test, expect, open, expectHealthy } from "./health.js";

const POOL = [
  { text: "Circulate pool water at 12 m³/h", standard: "12 m³/h for 8 hours a day", failures: [
    { text: "No flow at all", modes: [
      { text: "Pump motor bearing seizes", effects: "Pump stops; the water turns green.", consequence: "operational",
        decision: { outcome: "fixed_interval", task: "Replace the motor bearings", interval: 3, interval_unit: "years" } },
      { text: "Capacitor fails", effects: "Motor won't start.", consequence: "non_operational",
        decision: { outcome: "rtf", rtf_basis: "random", task: "Replace the capacitor when it fails" } },
    ] },
    { text: "Flow below 12 m³/h", modes: [
      { text: "Impeller worn", effects: "Slow turnover; cloudy water.", consequence: "operational", decision: null },
    ] },
  ] },
  { text: "Protect the pump from running dry", failures: [
    { text: "Pump runs dry without tripping", modes: [
      { text: "Low-level switch stuck closed", effects: "Seal burns out.", consequence: "hidden",
        decision: { outcome: "failure_finding", task: "Check the switch trips", interval: 6, interval_unit: "months" } },
    ] },
  ] },
];

// About 2,000 rows: 20 functions, 10 failures each, 9 modes each.
function bigStudy() {
  const out = [];
  for (let f = 1; f <= 20; f++) {
    const fn = { text: `Function ${f}: keep line ${f} running`, failures: [] };
    for (let x = 1; x <= 10; x++) {
      const fail = { text: `Failure ${f}.${x}: line ${f} stops`, modes: [] };
      for (let m = 1; m <= 9; m++) {
        fail.modes.push({ text: `Mode ${f}.${x}.${m}: part ${m} wears out`, effects: `Stops for ${m} hours.`,
          consequence: m % 3 ? "operational" : "hidden",
          decision: m % 4 ? { outcome: "fixed_interval", task: `Replace part ${m}`, interval: 100 * m, interval_unit: "hours" } : null });
      }
      fn.failures.push(fail);
    }
    out.push(fn);
  }
  return out;
}

async function study(request, name, functions) {
  const made = await request.post("/api/rcm/studies", { data: { name, system: "Pool pump", description: "" } });
  expect(made.ok()).toBeTruthy();
  const { id } = await made.json();
  const put = await request.put(`/api/rcm/studies/${id}/tree`, { data: { functions } });
  expect(put.ok(), await put.text()).toBeTruthy();
  return id;
}

const grid = (page) => page.getByRole("treegrid", { name: "RCM worksheet" });
const row = (page, text) => grid(page).locator('[role="row"][data-key]', { hasText: text });

test("the worksheet: levels, open and close, filter, chips and columns", async ({ page, request, problems }) => {
  const id = await study(request, `Pool pump ${Date.now()}`, POOL);
  await open(page, `/maintenance/rcm/${id}`);
  await expect(page.getByRole("tab", { name: "Worksheet" })).toHaveAttribute("aria-selected", "true");
  await expect(grid(page)).toBeVisible();
  await expect(page.getByText("2 functions · 3 functional failures · 4 failure modes")).toBeVisible();

  // A small study opens with everything showing, the levels and roll-ups on parent rows.
  const fn = row(page, "Circulate pool water");
  await expect(fn).toHaveAttribute("aria-level", "1");
  await expect(fn).toHaveAttribute("aria-expanded", "true");
  await expect(row(page, "Impeller worn")).toHaveAttribute("aria-level", "3");
  await expect(fn.getByText("1 to decide")).toBeVisible();
  await expect(grid(page).getByRole("columnheader", { name: /Decision/ })).toBeVisible();

  await page.getByRole("button", { name: "Open to level 1" }).click();
  await expect(row(page, "No flow at all")).toHaveCount(0);
  await page.getByRole("button", { name: "Open to level 2" }).click();
  await expect(row(page, "No flow at all")).toBeVisible();
  await expect(row(page, "Impeller worn")).toHaveCount(0);
  await page.getByRole("button", { name: "Open everything" }).click();
  await expect(row(page, "Impeller worn")).toBeVisible();

  // The arrow keys close and open, and move to the parent.
  await fn.click();
  await expect(fn).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowLeft");
  await expect(fn).toHaveAttribute("aria-expanded", "false");
  await expect(row(page, "No flow at all")).toHaveCount(0);
  await page.keyboard.press("ArrowRight");
  await expect(fn).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("ArrowDown");
  await expect(row(page, "No flow at all")).toBeFocused();
  await page.keyboard.press("ArrowLeft"); // open: closes it
  await page.keyboard.press("ArrowLeft"); // closed: up to its function
  await expect(fn).toBeFocused();
  await page.keyboard.press("End");
  await expect(row(page, "Low-level switch")).toBeFocused();
  await page.keyboard.press("Home");
  await expect(fn).toBeFocused();
  await page.getByRole("button", { name: "Close the details" }).click();

  // The filter keeps the path to each match; a chip too; nothing matching says so.
  await page.getByLabel("Filter the worksheet").fill("impeller");
  await expect(page.getByText("1 match, shown with what they're inside")).toBeVisible();
  for (const t of ["Circulate pool water", "Flow below 12", "Impeller worn"]) await expect(row(page, t)).toBeVisible();
  await expect(row(page, "Capacitor fails")).toHaveCount(0);
  await page.getByLabel("Filter the worksheet").fill("");
  await page.getByRole("button", { name: /^Hidden failures/ }).click();
  await expect(row(page, "Low-level switch")).toBeVisible();
  await expect(row(page, "Impeller worn")).toHaveCount(0);
  await page.getByRole("button", { name: /^Needs a decision/ }).click();
  await expect(page.getByText("Nothing matches.")).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(row(page, "Impeller worn")).toBeVisible();

  // The column chooser: show a column, hide one; remembered after a reload.
  await page.getByRole("button", { name: "Columns" }).click();
  await page.getByRole("checkbox", { name: "Performance standard" }).check();
  await page.getByRole("checkbox", { name: "Failure effects" }).uncheck();
  await page.keyboard.press("Escape");
  await expect(grid(page).getByRole("columnheader", { name: /Performance standard/ })).toBeVisible();
  await expect(grid(page).getByRole("columnheader", { name: /Failure effects/ })).toHaveCount(0);
  await expect(fn.getByText("12 m³/h for 8 hours a day")).toBeVisible();
  await page.reload();
  await expect(grid(page).getByRole("columnheader", { name: /Performance standard/ })).toBeVisible();
  await page.getByRole("button", { name: "Columns" }).click();
  await page.getByRole("button", { name: "Show the usual columns" }).click();
  await expect(grid(page).getByRole("columnheader", { name: /Failure effects/ })).toBeVisible();
  await expectHealthy(page, problems, { label: "the RCM worksheet" });
});

test("editing from the worksheet: the panel, a cell in place, the decision dialog, undo and save", async ({ page, request, problems }) => {
  const id = await study(request, `Pool pump edits ${Date.now()}`, POOL);
  await open(page, `/maintenance/rcm/${id}`);

  // A row opens its details panel.
  await row(page, "Impeller worn").click();
  const panel = page.getByRole("complementary", { name: "Details" });
  await expect(panel.getByRole("heading", { name: "Impeller worn" })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Flow below 12 m³/h" })).toBeVisible();
  await panel.getByLabel("Failure effects").fill("Slow turnover; the water clouds over.");
  await panel.getByLabel("Failure effects").blur();
  await expect(row(page, "Impeller worn").getByText("the water clouds over")).toBeVisible();
  await expect(page.getByText("Unsaved")).toBeVisible();

  // A cell edited in place, checked as the server checks it.
  const bearing = row(page, "Pump motor bearing seizes");
  await bearing.locator('[role="gridcell"]', { hasText: "3 years" }).dblclick();
  const interval = bearing.getByRole("spinbutton");
  await interval.fill("-1");
  await interval.press("Enter");
  await expect(page.getByText("The task interval must be positive.")).toBeVisible();
  await interval.fill("4");
  await interval.press("Enter");
  await expect(bearing.getByText("4 years")).toBeVisible();
  // Undo steps back.
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(bearing.getByText("3 years")).toBeVisible();

  // "To decide" opens the decision dialog.
  await row(page, "Impeller worn").getByRole("button", { name: "To decide" }).click();
  const dialog = page.locator(".decision-modal");
  await dialog.getByRole("button", { name: /^Run-to-failure/ }).click();
  await dialog.getByRole("button", { name: /^Failures are random/ }).click();
  await dialog.getByRole("button", { name: "Apply" }).click();
  await expect(row(page, "Impeller worn").getByText("Run-to-failure (random)")).toBeVisible();

  // Add a failure mode from the panel, then save the lot.
  await row(page, "Flow below 12").click();
  await panel.getByRole("button", { name: "Add a failure mode" }).click();
  await expect(panel.getByRole("heading", { name: "(no description yet)" })).toBeVisible();
  await panel.getByLabel("Description").fill("Pump lid O-ring leaks air");
  await panel.getByLabel("Description").blur();
  await expect(row(page, "Pump lid O-ring leaks air")).toHaveAttribute("aria-level", "3");
  await page.getByRole("button", { name: "Save study" }).click();
  await expect(page.getByRole("button", { name: "Saved" })).toBeVisible();
  const saved = await (await request.get(`/api/rcm/studies/${id}`)).json();
  const modes = saved.functions[0].failures[1].modes;
  expect(modes.map((m) => m.text)).toEqual(["Impeller worn", "Pump lid O-ring leaks air"]);
  expect(modes[0].effects).toBe("Slow turnover; the water clouds over.");
  expect(modes[0].decision.outcome).toBe("rtf");
  expect(saved.functions[0].failures[0].modes[0].decision.interval).toBe(3);

  // The Tree view is still there, with the same study.
  await page.getByRole("tab", { name: "Tree" }).click();
  await expect(page).toHaveURL(/\?tab=tree$/);
  await expect(page.locator(".rcm-tree").getByText("Pump lid O-ring leaks air")).toBeVisible();
  await expectHealthy(page, problems, { label: "editing the RCM worksheet" });
});

test("the sample is read-only, with the walkthrough's anchors on the worksheet", async ({ page, problems }) => {
  await open(page, "/maintenance/rcm/sample-rcm-truck");
  await expect(grid(page)).toBeVisible();
  await expect(page.getByRole("button", { name: "Add function" })).toHaveCount(0);
  for (const wt of ["rcm-function", "rcm-mode", "rcm-evidence", "rcm-checks"]) {
    await expect(page.locator(`[data-wt="${wt}"]`).first()).toBeVisible();
  }
  await row(page, "Wheel-bearing failure").click();
  const panel = page.getByRole("complementary", { name: "Details" });
  await expect(panel.getByText("Contradicted")).toBeVisible();
  await expect(panel.getByRole("button", { name: /Decide|Change the decision/ })).toHaveCount(0);
  await expectHealthy(page, problems, { label: "the sample RCM worksheet" });
});

test("on a phone: two-line rows, the details as a sheet, nothing sideways", async ({ page, request, problems }) => {
  const id = await study(request, `Pool pump phone ${Date.now()}`, POOL);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/maintenance/rcm/${id}`);
  const r = row(page, "Pump motor bearing seizes");
  await expect(r).toBeVisible();
  await expect(r.getByText("Operational · Fixed-interval · 3 years")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await r.click();
  const panel = page.getByRole("complementary", { name: "Details" });
  await expect(panel.getByRole("heading", { name: "Pump motor bearing seizes" })).toBeVisible();
  await expect(panel.getByLabel("Task")).toHaveValue("Replace the motor bearings");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await panel.getByRole("button", { name: "Close the details" }).click();
  await expect(panel).toHaveCount(0);
  await row(page, "Circulate pool water").locator(".rw-chev").click();
  await expect(r).toHaveCount(0);
  await expectHealthy(page, problems, { label: "the RCM worksheet on a phone" });
});

test("a study of about 2,000 rows opens quickly and draws only what's on screen", async ({ page, request, problems }) => {
  const id = await study(request, `Big plant ${Date.now()}`, bigStudy());
  const start = Date.now();
  await open(page, `/maintenance/rcm/${id}`);
  await expect(page.getByText("20 functions · 200 functional failures · 1,800 failure modes")).toBeVisible();
  const firstRender = Date.now() - start;
  // A big study opens two levels deep.
  await expect(row(page, "Failure 1.1: line 1 stops")).toBeVisible();
  await expect(row(page, "Mode 1.1.1:")).toHaveCount(0);
  const before = await page.evaluate(() => performance.now());
  await page.getByRole("button", { name: "Open everything" }).click();
  await expect(row(page, "Mode 1.1.1:")).toBeVisible();
  const expandAll = await page.evaluate((t) => performance.now() - t, before);
  const drawn = await grid(page).locator('[role="row"][data-key]').count();
  expect(drawn, "only the rows on screen are in the page").toBeLessThan(80);
  await expect(grid(page)).toHaveAttribute("aria-rowcount", "2021");
  // Scrolled far down, the rows it sits inside stay pinned at the top.
  await grid(page).evaluate((el) => { el.scrollTop = 41000; }); // inside function 12, failure 12.3
  await expect(page.locator(".rw-pins .rw-row.rw-fn")).toHaveText(/Function 12:/);
  await expect(page.locator(".rw-pins .rw-row.rw-fail")).toHaveText(/Failure 12.3:/);
  test.info().annotations.push({ type: "timing", description: `first render ${firstRender} ms, open everything ${Math.round(expandAll)} ms, ${drawn} rows in the page` });
  console.log(`RCM worksheet, 2,020 rows: first render ${firstRender} ms, open everything ${Math.round(expandAll)} ms, ${drawn} rows drawn`);
  await expectHealthy(page, problems, { label: "a big RCM study" });
});
