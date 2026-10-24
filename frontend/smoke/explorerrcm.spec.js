// The Explorer's detail panel tabs (Operate › Assets › Explorer): Summary and
// RCM; the RCM tab's table for the position picked in the tree (no position
// rows, levels or chips of its own: the tree is the index), "Include positions
// inside", edits written at once, the evidence check, that it fits the window,
// the "Not analysed" chip, Full width, and full screen (F, Esc, a dialog on top,
// the selection and tab kept).
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
  const fn = await post(`${M}/positions/${pump.id}/functions`, { text: `Pump water ${tag}`, standard: "50 L/s" });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `No flow ${tag}` });
  const mode = await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Bearing seizes ${tag}`, functional_failure_id: ff.id });
  const res = await request.put(`${M}/failure-modes/${mode.id}/decision`, {
    data: { consequence: "operational", decision: { outcome: "rtf", rtf_basis: "random", evidence: { type: "model", id: "sample-model-bearings-weibull" } } },
  });
  expect(res.ok()).toBeTruthy();
  await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Seal leaks ${tag}` }); // under no functional failure
  await post(`${M}/positions/${pump.id}/fit`, { new_item: { name: `Rcm unit ${tag}`, serial: `RU-${tag}` } });
  return { top, pump, motor, fn, ff, mode };
}

const row = (page, name) => page.getByRole("treeitem", { name: new RegExp(`^${name}`) });
const panel = (page) => page.getByRole("region", { name: "Details" });
const grid = (page) => page.getByRole("treegrid", { name: "RCM worksheet" });
const overflow = (page) => page.evaluate(() => {
  const el = document.documentElement;
  return { down: el.scrollHeight - innerHeight, side: el.scrollWidth - innerWidth };
});

test("the panel's tabs: Summary and RCM, in the address, kept while walking the tree", async ({ page, request, problems }) => {
  const tag = `t${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.top.id}`);
  const tabs = panel(page).getByRole("tablist", { name: "What to show for this row" });
  await expect(tabs.getByRole("tab")).toHaveText(["Summary", "RCM"]);
  await expect(tabs.getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "true");
  // A long description takes two lines, and More opens the whole of it.
  const more = panel(page).getByRole("button", { name: /More/ });
  await expect(more).toBeVisible();
  await more.click();
  await expect(page.getByRole("dialog", { name: "Description" })).toBeVisible();
  await page.keyboard.press("Escape");

  // The arrow keys move between tabs (the ARIA tab pattern); the address follows.
  await tabs.getByRole("tab", { name: "Summary" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.getByRole("tab", { name: "RCM" })).toHaveAttribute("aria-selected", "true");
  await expect(page).toHaveURL(/tab=rcm/);
  await expect(grid(page)).toBeVisible();
  // The plant itself has no functions yet; the table is the plant's only.
  await expect(grid(page).getByText(/No functions yet/)).toBeVisible();
  await expect(grid(page).getByText(`Bearing seizes ${tag}`)).toHaveCount(0);

  // Walk down the tree: the RCM tab stays and the table follows.
  await row(page, `Rcm plant ${tag}`).focus();
  await page.keyboard.press("ArrowDown");
  await expect(row(page, `Rcm pump ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expect(panel(page).getByRole("tab", { name: "RCM" })).toHaveAttribute("aria-selected", "true");
  await expect(page).toHaveURL(new RegExp(`sel=${p.pump.id}`));
  await expect(grid(page).getByText(`Bearing seizes ${tag}`)).toBeVisible();
  await expect(grid(page).getByText("Contradicted").first()).toBeVisible();
  await expect(grid(page).getByText("Not under a functional failure").first()).toBeVisible();
  // The tree is the index: the table has no position rows, and no levels or chips of its own.
  await expect(grid(page).getByText(`Rcm pump ${tag}`, { exact: true })).toHaveCount(0);
  await expect(grid(page).getByText(`Rcm motor ${tag}`, { exact: true })).toHaveCount(0);
  await expect(panel(page).getByRole("button", { name: "Needs a decision" })).toHaveCount(0);
  await expect(panel(page).getByRole("group", { name: "Open the tree to a level" })).toHaveCount(0);

  // An item has Summary only (no tab row); a position again shows RCM.
  await open(page, `/asset-register/explorer?arrange=items&tab=rcm`);
  await row(page, `Rcm unit ${tag}`).click();
  await expect(panel(page).getByRole("heading", { name: `Rcm unit ${tag}` })).toBeVisible();
  await expect(panel(page).getByRole("tablist")).toHaveCount(0);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  await expect(panel(page).getByRole("tab", { name: "RCM" })).toHaveAttribute("aria-selected", "true");
  await expectHealthy(page, problems, { label: "explorer tabs" });
});

for (const [w, h] of [[1440, 900], [1366, 768]]) {
  test(`the RCM tab fits ${w}x${h}: no page scroll, the grid scrolls in its card`, async ({ page, request, problems }) => {
    const tag = `f${w}${Date.now()}`;
    const p = await plant(request, tag);
    await page.setViewportSize({ width: w, height: h });
    await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm&inside=1`);
    await expect(grid(page)).toBeVisible();
    expect(await overflow(page)).toEqual({ down: 0, side: 0 });
    // The details panel opens beside the grid and it still fits.
    await grid(page).getByText(`Bearing seizes ${tag}`).click();
    await expect(page.getByRole("complementary", { name: "Details" })).toBeVisible();
    expect(await overflow(page)).toEqual({ down: 0, side: 0 });
    await open(page, `/asset-register/explorer?arrange=positions&sel=${p.top.id}`);
    await expectHealthy(page, problems, { label: `rcm fits ${w}` });
  });
}

test("at 400 px nothing scrolls sideways, on either tab", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  for (const tab of ["", "&tab=rcm"]) {
    await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}${tab}`);
    await row(page, `Rcm pump ${tag}`).click();
    await expect(panel(page).getByRole("heading", { name: `Rcm pump ${tag}` })).toBeVisible();
    if (tab) await expect(grid(page)).toBeVisible();
    expect((await overflow(page)).side, `sideways at 400 px${tab}`).toBe(0);
  }
  // No full-screen button on a phone: the page is already the screen.
  await expect(page.getByRole("button", { name: "Full screen", exact: true })).toHaveCount(0);
  await expectHealthy(page, problems, { label: "rcm at 400 px", root: ".tx-detail" });
});

test("Include positions inside, edits and the Not analysed chip", async ({ page, request, problems }) => {
  const tag = `e${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.top.id}&tab=rcm`);
  // The plant only (the default): it has no functions of its own.
  await expect(grid(page).getByText(/No functions yet/)).toBeVisible();
  const inside = page.getByRole("checkbox", { name: "Include positions inside" });
  await expect(inside).not.toBeChecked();
  await inside.click(); // the address holds it, so the box follows a moment later
  await expect(inside).toBeChecked();
  await expect(page).toHaveURL(/inside=1/);
  // The pump's function shows, naming its position in the Position column (no position rows).
  await expect(grid(page).getByText(`Pump water ${tag}`)).toBeVisible();
  await expect(grid(page).getByRole("columnheader", { name: /^Position/ })).toBeVisible();
  await expect(grid(page).getByRole("gridcell", { name: `Rcm pump ${tag}`, exact: true }).first()).toBeVisible();
  await inside.click();
  await expect(inside).not.toBeChecked();
  await expect(page).not.toHaveURL(/inside=1/);

  // Add a function to the plant: written at once, in the tree's own graph.
  await page.getByRole("button", { name: "Add function" }).first().click();
  const ask = page.getByRole("dialog", { name: "Add a function" });
  await ask.getByRole("textbox").fill(`Hold the line together ${tag}`);
  await ask.getByRole("button", { name: "Add function" }).click();
  await expect(grid(page).getByText(`Hold the line together ${tag}`)).toBeVisible();
  const sheet = await (await request.get(`${M}/positions/${p.top.id}/rcm?scope=this`)).json();
  expect(sheet.positions[0].functions.map((f) => f.text)).toEqual([`Hold the line together ${tag}`]);

  // The Not analysed chip lives in the tree: the pump (a failure mode with no
  // decision) and the motor (no function yet); the plant has a function now.
  await page.getByRole("button", { name: "Not analysed" }).click();
  await expect(page.getByRole("status").filter({ hasText: /matches, shown with what they're inside/ })).toBeVisible();
  await expect(row(page, `Rcm plant ${tag}`)).toHaveAccessibleName(/2 positions not analysed yet inside/);
  await expect(row(page, `Rcm pump ${tag}`)).toBeVisible();
  await expect(row(page, `Rcm pump ${tag}`).locator(".tp-mini.rcm")).toBeVisible();
  await expectHealthy(page, problems, { label: "rcm edits" });
});

test("full width folds the tree; full screen: F, a dialog on top, Esc, the row and tab kept", async ({ page, request, problems }) => {
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
  await page.getByRole("button", { name: "Full width" }).click();
  await expect(page.getByRole("button", { name: "Show the tree", exact: true }).first()).toBeVisible();
  await expect(page.getByRole("tree")).toHaveCount(0);
  await page.getByRole("button", { name: /^Show the tree$/ }).first().click();
  await expect(page.getByRole("tree")).toBeVisible();

  await page.locator("body").click({ position: { x: 5, y: 300 } });
  await page.keyboard.press("f");
  await expect(page.getByRole("button", { name: "Exit full screen" })).toBeVisible();
  await expect(page.locator(".tx.is-full")).toBeVisible();
  // The tree and the panel cover the whole screen (the app's menu and header behind).
  expect(await page.evaluate(() => {
    const r = document.querySelector(".tx.is-full").getBoundingClientRect();
    return [r.top, r.left, Math.round(r.width), Math.round(r.height)];
  })).toEqual([0, 0, ...(await page.evaluate(() => [innerWidth, innerHeight]))]);
  // A dialog opens on top, inside full screen.
  await grid(page).getByText(`Bearing seizes ${tag}`).click();
  await page.getByRole("button", { name: "Change the decision…" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  expect(await page.evaluate(() => document.querySelector(".tx.is-full").contains(document.querySelector(".overlay, [role=dialog]")))).toBe(true);
  await page.keyboard.press("Escape"); // the dialog first
  await expect(dialog).toHaveCount(0);
  await expect(page.locator(".tx.is-full")).toBeVisible();
  await page.keyboard.press("Escape"); // then full screen
  await expect(page.locator(".tx.is-full")).toHaveCount(0);
  await expect(row(page, `Rcm pump ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expect(panel(page).getByRole("tab", { name: "RCM" })).toHaveAttribute("aria-selected", "true");
  await expectHealthy(page, problems, { label: "explorer full screen" });
});
