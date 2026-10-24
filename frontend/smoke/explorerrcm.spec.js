// The Explorer's tabs (Operate › Assets › Explorer). Summary: the tree (positions)
// with the page about the row picked beside it. RCM: the tree and the RCM are
// one table: the same tree is its first column, each position's functions ›
// functional failures › failure modes nested in it, the RCM's columns beside
// every row; adding in the table grows the tree; the selected row stays put
// across the tabs; it fits the window; the keyboard; the chips; full screen.
// Each test makes its own small plant through the API.
import { test, expect, open, expectHealthy } from "./health.js";

const M = "/api/maintenance";

async function plant(request, tag) {
  const post = async (path, data) => {
    const res = await request.post(path, { data });
    expect(res.ok(), `${path}: ${res.status()} ${await res.text()}`).toBeTruthy();
    return res.json();
  };
  const top = await post(`${M}/positions`, {
    name: `Rcm plant ${tag}`,
    description: "A long description about the plant. ".repeat(20),
  });
  const pump = await post(`${M}/positions`, { name: `Rcm pump ${tag}`, parent_id: top.id });
  const motor = await post(`${M}/positions`, { name: `Rcm motor ${tag}`, parent_id: pump.id });
  // Several functions, each with several functional failures, each with several modes.
  const fns = [];
  for (const f of ["Pump water", "Contain the water"]) {
    const fn = await post(`${M}/positions/${pump.id}/functions`, { text: `${f} ${tag}` });
    fns.push(fn);
    for (const x of ["No flow", "Low flow"]) {
      const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `${x} ${f} ${tag}` });
      for (const mo of ["Bearing seizes", "Seal leaks"]) {
        await post(`${M}/positions/${pump.id}/failure-modes`, { text: `${mo} ${x} ${f} ${tag}`, functional_failure_id: ff.id });
      }
    }
  }
  const mode = await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Coupling fails ${tag}` }); // under none
  const res = await request.put(`${M}/failure-modes/${mode.id}/decision`, {
    data: { consequence: "operational", decision: { outcome: "rtf", rtf_basis: "random", evidence: { type: "model", id: "sample-model-bearings-weibull" } } },
  });
  expect(res.ok()).toBeTruthy();
  await post(`${M}/positions/${pump.id}/fit`, { new_item: { name: `Rcm unit ${tag}`, serial: `RU-${tag}` } });
  return { top, pump, motor, fns, mode };
}

const table = (page) => page.getByRole("treegrid", { name: /and their RCM/ });
const tree = (page) => page.getByRole("tree", { name: "Positions" });
const trow = (page, name) => table(page).getByRole("row", { name: new RegExp(name) });
// Picked by its tree cell (a click mid-row could land on a cell's own button).
const pickRow = (page, name) => trow(page, name).locator(".tt-tree, .tt-l1").first().click();
const treeitem = (page, name) => page.getByRole("treeitem", { name: new RegExp(`^${name}`) });
const overflow = (page) => page.evaluate(() => {
  const el = document.documentElement;
  return { down: el.scrollHeight - innerHeight, side: el.scrollWidth - innerWidth };
});
const topOf = async (locator) => Math.round((await locator.boundingBox()).y);
// A row's place in the tree's own scroll area (the area itself starts higher on
// the RCM tab, whose controls are two slim rows).
const placeOf = async (page, locator) => (await topOf(locator)) - (await topOf(page.locator(".tp-scroll")));

test("RCM: the tree and the RCM are one table; Summary: the tree and the page; the row stays put", async ({ page, request, problems }) => {
  const tag = `t${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}`);
  // Summary: the tree (positions only) and the page beside it.
  await expect(tree(page)).toBeVisible();
  await expect(table(page)).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Details" }).getByRole("heading", { name: `Rcm pump ${tag}` })).toBeVisible();
  await expect(page.getByText(`Pump water ${tag}`)).toHaveCount(0);
  const before = await placeOf(page, treeitem(page, `Rcm pump ${tag}`));

  await page.getByRole("tab", { name: "RCM" }).click();
  await expect(page).toHaveURL(/tab=rcm/);
  // One table: no tree of its own beside it, the positions and their RCM in the same rows.
  await expect(table(page)).toBeVisible();
  await expect(page.getByRole("tree")).toHaveCount(0);
  await expect(table(page).getByRole("columnheader", { name: "Decision" })).toBeVisible();
  await expect(trow(page, `^Rcm plant ${tag}`)).toBeVisible();
  const pumpRow = trow(page, `^Rcm pump ${tag}`);
  await expect(pumpRow).toHaveAttribute("aria-selected", "true");
  expect(await placeOf(page, pumpRow)).toBe(before); // the selected row didn't move in the tree
  // Its functions, failures and modes, nested under it (several of each).
  await expect(trow(page, `^Function: Pump water ${tag}`)).toBeVisible();
  await expect(trow(page, `^Function: Contain the water ${tag}`)).toBeVisible();
  await expect(trow(page, `Functional failure: Low flow Pump water ${tag}`)).toBeVisible();
  await expect(trow(page, `Failure mode: Seal leaks Low flow Pump water ${tag}`)).toBeVisible();
  await trow(page, `^Function: Pump water ${tag}`).locator(".tp-chev").click(); // close two: the rest comes into view
  await trow(page, `^Function: Contain the water ${tag}`).locator(".tp-chev").click();
  await expect(trow(page, "Not under a functional failure").first()).toBeVisible();
  await expect(trow(page, `Coupling fails ${tag}`).getByText("Contradicted")).toBeVisible();
  // RCM is by position: the other arrangements wait for Summary (the counts say so).
  await expect(page.getByRole("radio", { name: "Locations" })).toHaveCount(0);
  await expect(page.locator(".tt-top .tp-status")).toContainText("RCM is by position");

  await page.getByRole("tab", { name: "Summary" }).click();
  await expect(tree(page)).toBeVisible();
  await expect(page.getByText(`Pump water ${tag}`)).toHaveCount(0);
  await expect(treeitem(page, `Rcm pump ${tag}`)).toHaveAttribute("aria-selected", "true");
  expect(await placeOf(page, treeitem(page, `Rcm pump ${tag}`))).toBe(before);
  // The plant's long description: two lines, and More opens the whole of it.
  await treeitem(page, `Rcm plant ${tag}`).click();
  await page.getByRole("region", { name: "Details" }).getByRole("button", { name: /More/ }).click();
  await expect(page.getByRole("dialog", { name: "Description" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expectHealthy(page, problems, { label: "explorer one table" });
});

test("adding in the table grows the tree: a function, its failures and modes", async ({ page, request, problems }) => {
  const tag = `g${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.motor.id}&tab=rcm`);
  const ask = async (title, text) => {
    const d = page.getByRole("dialog", { name: title });
    await d.getByRole("textbox").fill(text);
    await d.getByRole("button", { name: title.replace(/^Add an? /, "Add ") }).click();
  };
  await trow(page, "^Add a function$").click();
  await ask("Add a function", `Turn the shaft ${tag}`);
  const fn = trow(page, `^Function: Turn the shaft ${tag}`);
  await expect(fn).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("complementary", { name: "Details" })).toBeVisible();
  // A second function, then a failure under the first and two modes under that.
  await trow(page, "^Add a function$").click();
  await ask("Add a function", `Stay cool ${tag}`);
  await fn.locator(".tp-chev").click();
  await trow(page, "^Add a functional failure$").first().click();
  await ask("Add a functional failure", `Shaft stops ${tag}`);
  await trow(page, `Shaft stops ${tag}`).locator(".tp-chev").click();
  for (const m of ["Winding burnt", "Bearing worn"]) {
    await trow(page, "^Add a failure mode$").first().click();
    await ask("Add a failure mode", `${m} ${tag}`);
    await expect(trow(page, `${m} ${tag}`)).toBeVisible();
  }
  const sheet = await (await request.get(`${M}/positions/${p.motor.id}/rcm?scope=this`)).json();
  expect(sheet.positions[0].functions.map((f) => f.text)).toEqual([`Turn the shaft ${tag}`, `Stay cool ${tag}`]);
  expect(sheet.positions[0].functions[0].failures[0].modes.map((m) => m.text)).toEqual([`Winding burnt ${tag}`, `Bearing worn ${tag}`]);
  // The motor is analysed now that it has functions; one mode undecided keeps it "not analysed".
  await expect(trow(page, `^Rcm motor ${tag}`)).toBeVisible();
  await expectHealthy(page, problems, { label: "tree grows" });
});

test("keyboard: walk from a position into its functions and modes, Enter for the details", async ({ page, request, problems }) => {
  const tag = `k${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  const pumpRow = trow(page, `^Rcm pump ${tag}`);
  await pumpRow.focus();
  await page.keyboard.press("ArrowDown");
  await expect(trow(page, `^Function: Pump water ${tag}`)).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowLeft"); // close it
  await expect(trow(page, `Functional failure: No flow Pump water ${tag}`)).toHaveCount(0);
  await page.keyboard.press("ArrowRight"); // open it
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(trow(page, `Failure mode: Bearing seizes No flow Pump water ${tag}`)).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("complementary", { name: "Details" })).toBeVisible();
  await expectHealthy(page, problems, { label: "keyboard" });
});

for (const [w, h] of [[1440, 900], [1366, 768]]) {
  test(`the RCM tab fits ${w}x${h}: no page scroll, the table scrolls in its own area`, async ({ page, request, problems }) => {
    const tag = `f${w}${Date.now()}`;
    const p = await plant(request, tag);
    await page.setViewportSize({ width: w, height: h });
    await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
    await expect(table(page)).toBeVisible();
    expect(await overflow(page)).toEqual({ down: 0, side: 0 });
    await pickRow(page, `Failure mode: Seal leaks No flow Pump water ${tag}`);
    await expect(page.getByRole("complementary", { name: "Details" })).toBeVisible();
    expect(await overflow(page)).toEqual({ down: 0, side: 0 });
    await expectHealthy(page, problems, { label: `rcm fits ${w}`, root: ".tx" });
  });
}

test("the RCM tab's controls are two slim rows: the table gets the height; Columns opens over it", async ({ page, request, problems }) => {
  const tag = `h${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.motor.id}&tab=rcm`);
  await expect(table(page)).toBeVisible();
  const bar = page.locator(".tt-headslot");
  // One bar: the tabs, the position (its way up over its name) and the actions.
  await expect(bar.getByRole("tab", { name: "RCM" })).toHaveAttribute("aria-selected", "true");
  await expect(bar.getByRole("heading", { name: `Rcm motor ${tag}` })).toBeVisible();
  await expect(bar.getByRole("navigation", { name: "Breadcrumb" })).toContainText(`Rcm pump ${tag}`);
  for (const name of ["Columns", "Add function", "Full screen"]) {
    await expect(bar.getByRole("button", { name, exact: true })).toBeVisible();
  }
  await expect(bar.getByRole("link", { name: "Open the full page" })).toBeVisible();
  const heights = await page.evaluate(() => {
    const h = (s) => Math.round(document.querySelector(s).getBoundingClientRect().height);
    return { bar: h(".tt-bar"), all: h(".tt-top") };
  });
  expect(heights.bar).toBeLessThanOrEqual(56);
  expect(heights.all).toBeLessThanOrEqual(100);
  // The way up goes up.
  await bar.getByRole("navigation", { name: "Breadcrumb" }).getByRole("button", { name: `Rcm pump ${tag}` }).click();
  await expect(trow(page, `^Rcm pump ${tag}`)).toHaveAttribute("aria-selected", "true");
  // Columns opens over the table, its last choice not cut off.
  await bar.getByRole("button", { name: "Columns" }).click();
  const list = page.getByRole("group", { name: "Columns to show" });
  await expect(list).toBeVisible();
  const reset = list.getByRole("button", { name: "Show the usual columns" });
  const box = await reset.boundingBox();
  expect(await page.evaluate(([x, y]) => !!document.elementFromPoint(x, y)?.closest(".rw-pop"),
    [box.x + box.width / 2, box.y + box.height / 2])).toBe(true);
  await list.getByRole("checkbox", { name: "Evident or hidden" }).check();
  await expect(table(page).getByRole("columnheader", { name: "Evident or hidden" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(list).toHaveCount(0);
  expect(await overflow(page)).toEqual({ down: 0, side: 0 });
  await expectHealthy(page, problems, { label: "rcm slim header", root: ".tx" });
});

test("at 400 px nothing scrolls sideways, on either tab; a mode opens as a sheet", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}`);
  expect((await overflow(page)).side).toBe(0);
  await page.getByRole("tab", { name: "RCM" }).click();
  await expect(table(page)).toBeVisible();
  expect((await overflow(page)).side).toBe(0);
  await pickRow(page, `Failure mode: Bearing seizes No flow Pump water ${tag}`);
  await expect(page.getByRole("complementary", { name: "Details" })).toBeVisible();
  expect((await overflow(page)).side).toBe(0);
  await expect(page.getByRole("button", { name: "Full screen", exact: true })).toHaveCount(0);
  await expectHealthy(page, problems, { label: "rcm at 400 px", root: ".tx" });
});

test("one search and one chip row: the RCM's text, Needs a decision, Not analysed", async ({ page, request, problems }) => {
  const tag = `c${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  await page.getByRole("searchbox", { name: "Filter the tree and its RCM" }).fill(`Seal leaks Low flow Contain`);
  await expect(trow(page, `Failure mode: Seal leaks Low flow Contain the water ${tag}`)).toBeVisible();
  await expect(trow(page, `Failure mode: Bearing seizes No flow Pump water ${tag}`)).toHaveCount(0);
  await page.getByRole("searchbox", { name: "Filter the tree and its RCM" }).fill("");
  await page.getByRole("button", { name: "Needs a decision" }).click();
  await expect(trow(page, `Failure mode: Bearing seizes No flow Pump water ${tag}`)).toBeVisible();
  await expect(trow(page, `Coupling fails ${tag}`)).toHaveCount(0); // decided
  await page.getByRole("button", { name: "Needs a decision" }).click();
  await page.getByRole("button", { name: "Not analysed" }).click();
  // The plant (no function), the pump (modes with no decision) and the motor
  // (no function): counted in the plant's quiet marker.
  await expect(trow(page, `^Rcm plant ${tag}`)).toHaveAccessibleName(/3 positions not analysed yet here and inside/);
  await expect(trow(page, `^Rcm plant ${tag}`).locator(".tp-mini.rcm")).toBeVisible();
  // The RCM's own chips are for its tab only.
  await page.getByRole("tab", { name: "Summary" }).click();
  await expect(page.getByRole("button", { name: "Needs a decision" })).toHaveCount(0);
  await expectHealthy(page, problems, { label: "rcm chips" });
});

test("full screen: F, a dialog on top, Esc, the row and tab kept", async ({ page, request, problems }) => {
  await page.addInitScript(() => {
    // The page's own full screen (as on an iPhone): Escape leaves it, as the app handles it.
    for (const k of ["requestFullscreen", "webkitRequestFullscreen"]) {
      delete Element.prototype[k];
      delete HTMLElement.prototype[k];
    }
    for (const k of ["exitFullscreen", "webkitExitFullscreen"]) delete Document.prototype[k];
  });
  const tag = `s${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  await page.locator("body").click({ position: { x: 5, y: 300 } });
  await page.keyboard.press("f");
  await expect(page.getByRole("button", { name: "Exit full screen" })).toBeVisible();
  expect(await page.evaluate(() => {
    const r = document.querySelector(".tx.is-full").getBoundingClientRect();
    return [r.top, r.left, Math.round(r.width), Math.round(r.height)];
  })).toEqual([0, 0, ...(await page.evaluate(() => [innerWidth, innerHeight]))]);
  // A dialog opens on top, inside full screen.
  await pickRow(page, `Failure mode: Bearing seizes No flow Pump water ${tag}`);
  await page.getByRole("button", { name: "Decide…" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  expect(await page.evaluate(() => document.querySelector(".tx.is-full").contains(document.querySelector("[role=dialog]")))).toBe(true);
  await page.keyboard.press("Escape"); // the dialog first
  await expect(dialog).toHaveCount(0);
  await expect(page.locator(".tx.is-full")).toBeVisible();
  await page.locator(".tt-headslot .td-title").click();
  await page.keyboard.press("Escape"); // then full screen
  await expect(page.locator(".tx.is-full")).toHaveCount(0);
  await expect(trow(page, `Failure mode: Bearing seizes No flow Pump water ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tab", { name: "RCM" })).toHaveAttribute("aria-selected", "true");
  await expectHealthy(page, problems, { label: "explorer full screen", root: ".tx" });
});
