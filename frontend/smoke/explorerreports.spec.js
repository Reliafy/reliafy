// The Explorer's Failure reports tab (Operate › Assets › Explorer): right-click
// a position → Add failure report… → the dialog (the fitted item shown, the
// consequence, a failure mode typed in) → the report opens in the tab with
// ?report= in the address and a few words in the heading; the parent's list
// shows it with its level under the parent and the counts; the loop: status
// to Investigating from the stepper, the investigation saved, a corrective
// action added and marked done, the verification with the repeat check, the
// close with its sign-off. At 400 px the row's ⋯ button offers the same, the
// report is its own screen, and nothing scrolls sideways.
// Each test makes its own small plant through the API.
//
// With SMOKE_SHOTS_DIR set, it also saves screenshots there (for the pull request).
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};

async function plant(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const site = await post(`${M}/locations`, { name: `Report site ${tag}` });
  const pool = await post(`${M}/positions`, { name: `Report pool ${tag}`, location_id: site.id });
  const circ = await post(`${M}/positions`, { name: `Report circulation ${tag}`, parent_id: pool.id });
  const pump = await post(`${M}/positions`, { name: `Report pump ${tag}`, parent_id: circ.id });
  await post(`${M}/positions/${pump.id}/fit`, { new_item: { name: `Report unit ${tag}`, serial: `RU-${tag}` } });
  return { site, pool, circ, pump };
}

const row = (page, name) => page.getByRole("treeitem", { name: new RegExp(`^${name}`) });
const rowMenu = (page, name) => page.getByRole("menu", { name: new RegExp(`^Actions for ${name}`) });
const query = (page) => new URL(page.url()).searchParams;
const panel = (page) => page.locator(".fr-panel, .fr-detail").first();
const detail = (page) => page.locator(".fr-detail");
const stepper = (page) => page.getByRole("list", { name: "Stage" });
const status = (page) => page.locator(".fr-h2 .td-pill");
const said = (page) => page.locator(".fr-msg");

test("Failure reports: file one from the row menu, see it under the parent, and take it round the loop", async ({ page, request, problems }) => {
  const tag = `r${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}`);
  await expect(row(page, `Report pump ${tag}`)).toHaveAttribute("aria-selected", "true");

  // The tab is there for a position; empty, it says how to add one and links the guide.
  await page.getByRole("tab", { name: "Failure reports" }).click();
  await expect.poll(() => query(page).get("tab")).toBe("reports");
  await expect(panel(page)).toContainText("No failure reports here yet");
  await expect(panel(page).getByRole("button", { name: "How failure reports work" })).toBeVisible();
  await expect(panel(page)).toContainText("0 open · 0 in all, at this position");

  // Right-click the pump: Add failure report… is after New position inside.
  await row(page, `Report pump ${tag}`).locator(".tp-nm").click({ button: "right" });
  const menu = rowMenu(page, `Report pump ${tag}`);
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("menuitem").nth(1)).toHaveText("Add failure report…");
  await menu.getByRole("menuitem", { name: "Add failure report…" }).click();
  const dialog = page.getByRole("dialog", { name: "New failure report" });
  await expect(dialog).toContainText(`At Report pump ${tag}`);
  await expect(dialog).toContainText(`Report unit ${tag} · serial RU-${tag}`); // the fitted item
  await expect(dialog.getByRole("textbox", { name: /Who found it/ })).toHaveValue("Dev User");
  await expect(dialog.getByRole("button", { name: "Report it" })).toBeDisabled(); // nothing said yet
  await dialog.getByRole("textbox", { name: /What happened/ }).fill(`Seal leaking at the drive end ${tag}`);
  await dialog.getByRole("radio", { name: "Safety" }).check();
  await dialog.getByRole("combobox").selectOption("new");
  await dialog.getByPlaceholder("e.g. Seal leaking").fill("Mechanical seal leak");
  await shot(page, "reports-desktop-new");
  await dialog.getByRole("button", { name: "Report it" }).click();
  await expect(dialog).toHaveCount(0);

  // The report opens in the tab, in the address, with a few words in the heading; the tree marks the pump.
  await expect.poll(() => query(page).get("report")).toBeTruthy();
  expect(query(page).get("tab")).toBe("reports");
  expect(query(page).get("sel")).toBe(p.pump.id);
  await expect(detail(page).getByRole("heading", { level: 2 })).toContainText(/FR-\d+ Seal leaking at the drive end/);
  await expect(page.locator(".tt-headslot")).toContainText(/Reported FR-\d+\./);
  await expect(status(page)).toHaveText("Reported");
  await expect(detail(page)).toContainText(`Report unit ${tag} · serial RU-${tag}`);
  await expect(detail(page)).toContainText("Mechanical seal leak");
  await expect(detail(page)).toContainText("Safety");
  await expect(row(page, `Report pump ${tag}`).locator(".tp-mini.report")).toHaveText("1");
  await expect(row(page, `Report pool ${tag}`).locator(".tp-mini.report")).toHaveAttribute("title", "1 open failure report inside");
  const reportId = query(page).get("report");
  await shot(page, "reports-desktop-report");

  // Investigating, from the stepper.
  await stepper(page).getByRole("button", { name: "Investigating" }).click();
  await expect(status(page)).toHaveText("Investigating");
  await expect(said(page)).toHaveText("Now investigating.");
  // The investigation card is open for the stage: the root cause saved.
  await detail(page).getByRole("combobox", { name: /Root cause category/ }).selectOption("wear");
  await detail(page).getByRole("textbox", { name: /^Root cause/ }).fill("Seal faces worn through at 4,000 hours");
  await detail(page).getByRole("textbox", { name: "Why 1" }).fill("The seal faces wore out");
  await detail(page).getByRole("button", { name: "Add a why" }).click();
  await detail(page).getByRole("textbox", { name: "Why 2" }).fill("It ran dry during the shutdown");
  await detail(page).getByRole("button", { name: "Save investigation" }).click();
  await expect(said(page)).toHaveText("Investigation saved.");
  await expect(detail(page)).toContainText("Wear: Seal faces worn through");

  // The parent's list: the report with its level under the parent, and the counts.
  await detail(page).getByRole("button", { name: "‹ All reports" }).click();
  await expect.poll(() => query(page).get("report")).toBeNull();
  await row(page, `Report pool ${tag}`).click();
  await expect.poll(() => query(page).get("sel")).toBe(p.pool.id);
  const list = page.getByRole("list", { name: "Failure reports" });
  await expect(list.getByRole("button")).toHaveCount(1);
  await expect(list.locator(".fr-sub")).toContainText(`Report circulation ${tag} › Report pump ${tag}`);
  await expect(list.locator(".fr-pills")).toContainText("Investigating");
  await expect(panel(page)).toContainText("1 open · 1 in all, at this position and the 2 positions inside it");
  await expect(panel(page).getByRole("button", { name: /^Investigating/ })).toContainText("1");
  await shot(page, "reports-desktop-list");
  // The Closed chip: nothing yet, and a way back.
  await panel(page).getByRole("button", { name: /^Closed/ }).click();
  await expect(panel(page)).toContainText("Nothing matches these filters.");
  await panel(page).getByRole("button", { name: "Show open reports" }).click();
  await list.getByRole("button", { name: /FR-\d+/ }).click();
  await expect.poll(() => query(page).get("report")).toBe(reportId);

  // A corrective action, marked done.
  await detail(page).getByRole("button", { name: "Corrective actions" }).click();
  await detail(page).getByRole("textbox", { name: /What will be done/ }).fill("Replace the seal and check alignment");
  await detail(page).getByRole("textbox", { name: /Work order/ }).fill("WO-77");
  await detail(page).getByRole("button", { name: "Add action" }).click();
  await expect(said(page)).toHaveText("Action added.");
  const actions = detail(page).locator("table.fr-actions");
  await expect(actions).toContainText("Replace the seal and check alignment");
  await expect(actions).toContainText("WO-77");
  await actions.getByRole("button", { name: "Done" }).click();
  await expect(said(page)).toHaveText("Marked done.");
  await expect(actions.locator(".td-pill")).toHaveText("Done");

  // Verification, with the repeat check beside it; then the close with its sign-off.
  await detail(page).getByRole("button", { name: "Verification" }).click();
  await expect(detail(page).locator(".fr-repeat")).toContainText("No repeat failure at this position since");
  await detail(page).getByRole("radio", { name: /It worked/ }).check();
  await detail(page).getByRole("button", { name: "Save verification" }).click();
  await expect(said(page)).toHaveText("Verification saved.");
  await detail(page).getByRole("button", { name: /^Close$/ }).click();
  await detail(page).getByRole("textbox", { name: /Sign-off note/ }).fill("New seal fitted; dry after a week");
  await detail(page).getByRole("button", { name: "Close report" }).click();
  await expect(said(page)).toHaveText(/Closed FR-\d+\./);
  await expect(status(page)).toHaveText("Closed");
  await expect(detail(page).locator(".fr-signoff")).toContainText(/^Closed on .* by Dev User: New seal fitted; dry after a week$/);
  await expect(detail(page)).toContainText("Closed: New seal fitted; dry after a week"); // in the history
  // The tree's marker goes with the last open report.
  await expect(row(page, `Report pump ${tag}`).locator(".tp-mini.report")).toHaveCount(0);
  // A link opens on the report.
  await open(page, `/asset-register/explorer?arrange=positions&tab=reports&sel=${p.pump.id}&report=${reportId}`);
  await expect(detail(page).getByRole("heading", { level: 2 })).toContainText(/Seal leaking at the drive end/);
  await expect(status(page)).toHaveText("Closed");
  await expectHealthy(page, problems, { label: "failure reports", root: ".tx" });
});

test("Failure reports at 400 px: the ⋯ button offers Add failure report…, the report is its own screen and nothing scrolls sideways", async ({ page, request, problems }) => {
  const tag = `q${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.circ.id}`);
  const more = row(page, `Report circulation ${tag}`).getByRole("button", { name: "Actions", exact: true });
  await more.click();
  const menu = rowMenu(page, `Report circulation ${tag}`);
  await expect(menu.getByRole("menuitem", { name: "Add failure report…" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await shot(page, "reports-phone-menu");
  await menu.getByRole("menuitem", { name: "Add failure report…" }).click();
  const dialog = page.getByRole("dialog", { name: "New failure report" });
  await expect(dialog).toContainText("Nothing fitted at this position");
  await dialog.getByRole("textbox", { name: /What happened/ }).fill(`Flow dropped to half ${tag}`);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await dialog.getByRole("button", { name: "Report it" }).click();
  await expect(dialog).toHaveCount(0);

  // The report, as its own screen, on the Failure reports tab.
  await expect.poll(() => query(page).get("report")).toBeTruthy();
  await expect(detail(page).getByRole("heading", { level: 2 })).toContainText(/Flow dropped to half/);
  await expect(page.getByRole("tab", { name: "Failure reports" })).toHaveAttribute("aria-selected", "true");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await shot(page, "reports-phone-report");
  await detail(page).getByRole("button", { name: "Corrective actions" }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);

  // Back to the list: the row stacks; the filters wrap.
  await detail(page).getByRole("button", { name: "‹ All reports" }).click();
  const list = page.getByRole("list", { name: "Failure reports" });
  await expect(list.getByRole("button", { name: /Flow dropped to half/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await shot(page, "reports-phone-list");
  await expectHealthy(page, problems, { label: "failure reports at 400 px", root: ".tx" });
});
