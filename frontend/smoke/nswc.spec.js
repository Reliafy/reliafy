// NSWC-11, the Navy's mechanical handbook, as a library of covariate models (Derryn, 9 Nov 2026:
// "literally just a library of covariate models"): its source page (the Navy's statement, each
// component's parts and failure modes), a bearing's record (the model in words, its factors, Try it
// with a value past the handbook's limit), and a prediction line set to an NSWC bearing with its
// Conditions… (the result changes). At 400 px nothing scrolls the page sideways.
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { headMenu } from "./explorer.js";

const M = "/api/maintenance";
const SOURCE = "NSWC-11: covariate models for mechanical parts (base rate × condition factors)";
const BEARING = "Bearing, rolling element (from its load rating)";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name, full = false) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: full });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

async function headPick(page, group, item) {
  await headMenu(page);
  await page.getByRole("menuitem", { name: group, exact: true }).click();
  await page.getByRole("menu", { name: group }).getByRole("menuitem", { name: item }).click();
}

test("the NSWC-11 library source, a bearing's record and Try it past a limit", async ({ page, problems }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, "/models/library");
  await page.getByRole("link", { name: SOURCE }).click();
  await expect(page).toHaveURL(/\/models\/library\/nswc-11$/);
  await expect(page.getByRole("heading", { name: "Covariate models: base rate × condition factors" })).toBeVisible();
  await expect(page.locator(".lib-disclaimer")).toContainText("did not take part");
  const table = page.locator(".lib-table");
  await expect(table.locator("thead th")).toHaveText(["Component", "Part or failure mode", "Base rate", "Factors", "Equation"]);
  await expect(table.getByRole("link", { name: BEARING }).first()).toBeVisible();
  await shot(page, "nswc-source-1440");
  await page.setViewportSize({ width: 400, height: 860 });
  await page.reload();
  await expect(page.locator(".lib-disclaimer")).toBeVisible();
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "nswc-source-400");
  await page.setViewportSize({ width: 1440, height: 900 });

  await table.getByRole("link", { name: BEARING }).first().click();
  await expect(page).toHaveURL(/\/models\/library\/nswc-11\/bearing-rolling-load-rating$/);
  await expect(page.getByRole("heading", { name: "The model in words" })).toBeVisible();
  await expect(page.locator("body")).toContainText("starts at one over its L10 life");
  await expect(page.getByRole("heading", { name: "The formula" })).toBeVisible();
  const tryIt = page.getByRole("region", { name: "Try it" });
  const out = tryIt.getByRole("status");
  await expect(out).toContainText("Needs these before it gives a rate");
  await tryIt.getByLabel("Dynamic load rating (catalogue) (L_S)").fill("5000");
  await tryIt.getByLabel("Radial load (F_R)").fill("1000");
  await tryIt.getByLabel("Operating speed (n)").fill("1800");
  await expect(out).toContainText("failures per 10⁶ h");
  const before = await out.locator(".cov-big b").textContent();
  // Past the handbook's range: it still computes, and says which limit and where.
  await tryIt.getByLabel("Bearing operating temperature (T_O)").fill("300");
  await expect(tryIt.locator(".cov-warn")).toContainText("Outside the handbook’s range (at most 260 °C, p. 7-17)");
  await expect(out).toContainText("NSWC-11 p. 7-17");
  await expect(out.locator(".cov-big b")).not.toHaveText(before);
  // Past a physical limit: refused, in words.
  await tryIt.getByLabel("Operating speed (n)").fill("0");
  await expect(out).toContainText("Can’t give a rate for these inputs");
  await tryIt.getByLabel("Operating speed (n)").fill("1800");
  await expect(out).toContainText("NSWC-11 p. 7-17");
  await expect(page.locator(".lib-disclaimer")).toContainText("not an official DoD document");
  await shot(page, "nswc-bearing-1440", true);
  await page.setViewportSize({ width: 400, height: 860 });
  await page.reload();
  const narrow = page.getByRole("region", { name: "Try it" });
  await narrow.getByLabel("Dynamic load rating (catalogue) (L_S)").fill("5000");
  await narrow.getByLabel("Radial load (F_R)").fill("1000");
  await narrow.getByLabel("Operating speed (n)").fill("1800");
  await narrow.getByLabel("Bearing operating temperature (T_O)").fill("300");
  await expect(narrow.getByRole("status")).toContainText("NSWC-11 p. 7-17");
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "nswc-bearing-400", true);
  await expectHealthy(page, problems, { label: "an NSWC-11 record" });
});

test("a prediction line on an NSWC bearing, with its conditions", async ({ page, request, problems }) => {
  const tag = `nswc${Date.now()}`;
  const pos = await postOk(request, `${M}/positions`, { name: `Gearbox ${tag}` });
  const part = await postOk(request, `${M}/parts`, { part_number: `B-${tag}`, name: `Input bearing ${tag}` });
  await postOk(request, `${M}/positions/${pos.id}/parts`, { part_id: part.id, role: "component", quantity: 2 });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pos.id}&tab=models`);
  await headPick(page, "Prediction", "Add a prediction (parts count)…");
  const pane = page.getByRole("region", { name: "Add a prediction" });
  await expect(pane.locator(".pred2-table tbody tr")).toHaveCount(1);
  const picker = pane.getByRole("combobox", { name: `Handbook part type of Input bearing ${tag}` });
  await picker.fill("bearing load rating");
  const list = page.getByRole("listbox", { name: `Handbook part type of Input bearing ${tag} matches` });
  await expect(list.locator(".ptp-group", { hasText: "NSWC-11" })).toBeVisible();
  await list.getByRole("option", { name: BEARING }).first().click();
  const status = pane.getByRole("status").first();
  await expect(pane.locator(".pred2-c-lambda").first()).toHaveText("Needs conditions");
  await expect(status).toContainText(`Left out, needs its conditions: Input bearing ${tag} ×2`);

  await pane.getByRole("button", { name: `Conditions of Input bearing ${tag}` }).click();
  const dlg = page.getByRole("dialog", { name: `Conditions: Input bearing ${tag}` });
  await expect(dlg).toBeVisible();
  await dlg.getByLabel("Dynamic load rating (catalogue) (L_S)").fill("5000");
  await dlg.getByLabel("Radial load (F_R)").fill("1000");
  await dlg.getByLabel("Operating speed (n)").fill("1800");
  await expect(dlg.getByRole("status")).toContainText("failures per 10⁶ h");
  await shot(page, "nswc-conditions-1440");
  await dlg.getByRole("button", { name: "Done" }).click();
  await expect(dlg).toHaveCount(0);
  await expect(pane.locator(".pred2-c-lambda").first()).not.toHaveText(/Needs conditions|—/);
  await expect(status).toContainText("1 of 1 line counted");
  await expect(status).toContainText("NSWC-11: 1 line");
  await expect(status).toContainText("did not take part");
  const rate = await status.locator(".pred2-big b").textContent();
  // A harder condition, a higher rate.
  await pane.getByRole("button", { name: `Conditions of Input bearing ${tag}` }).click();
  await dlg.getByLabel("Radial load (F_R)").fill("2000");
  await dlg.getByRole("button", { name: "Done" }).click();
  await expect(status.locator(".pred2-big b")).not.toHaveText(rate);
  // At 400 px: the pane and its Conditions… fit, nothing sideways.
  await page.setViewportSize({ width: 400, height: 860 });
  await page.reload();  // unsaved, so the line starts again: pick the bearing and its conditions once more
  await expect(pane).toBeVisible();
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await picker.fill("bearing load rating");
  await list.getByRole("option", { name: BEARING }).first().click();
  await pane.getByRole("button", { name: `Conditions of Input bearing ${tag}` }).click();
  await dlg.getByLabel("Dynamic load rating (catalogue) (L_S)").fill("5000");
  await dlg.getByLabel("Radial load (F_R)").fill("1000");
  await dlg.getByLabel("Operating speed (n)").fill("1800");
  await expect(dlg.getByRole("status")).toContainText("failures per 10⁶ h");
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "nswc-conditions-400");
  await dlg.getByRole("button", { name: "Cancel" }).click();
  await expectHealthy(page, problems, { label: "a prediction with an NSWC-11 line" });
});
