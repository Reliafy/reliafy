// Missions on every life and covariate model (Derryn, 22 Nov 2026): Add a mission… is on a model's
// row whether it's in use or not, and on a covariate model fitted from readings that change over
// time too. On a life model with no covariates a mission is a length from a starting age; its
// answer is the chance of lasting it with a 90% one-sided lower bound. Desktop and 400 px.
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const WEIBULL = "sample-model-bearings-weibull";
const TVC = "sample-model-pump-load-weibull-ph";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const nameRow = (page, text) => page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: text }) });

test("plain missions: a length from a starting age, with its bound; Add a mission… on models not in use", async ({ page, request, problems }) => {
  const tag = `pm${Date.now()}`;
  const pump = await postOk(request, `${M}/positions`, { name: `Lone pump ${tag}` });
  await postOk(request, `${M}/positions/${pump.id}/models`, { model_id: WEIBULL });
  // A covariate model fitted from readings that change over time, not the one in use.
  await postOk(request, `${M}/positions/${pump.id}/models`, { model_id: TVC });

  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${pump.id}&sel=${pump.id}&tab=models`);
  const tvc = nameRow(page, "changing load").first();
  await expect(tvc).toBeVisible();
  await tvc.locator(".tp-nm").click({ button: "right" });
  await expect(page.getByRole("menu").last().getByRole("menuitem").first()).toHaveText("Add a mission…");
  await page.keyboard.press("Escape");

  // Add a mission… on the Weibull: named first, then its length and starting age.
  const weibull = nameRow(page, "Bearing life — Weibull").first();
  await weibull.locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menuitem", { name: "Add a mission…" }).click();
  await page.getByLabel("Mission name").fill(`Long shift ${tag}`);
  await page.getByRole("button", { name: "Add the mission" }).click();
  const pane = page.getByRole("region", { name: "Mission" });
  await expect(pane.getByRole("spinbutton", { name: /^Length/ })).toBeVisible({ timeout: 20_000 });
  // No phases to give: a plain model's mission is its length.
  await expect(pane.getByRole("button", { name: "Add a phase" })).toHaveCount(0);
  await pane.getByRole("spinbutton", { name: /^Length/ }).fill("200");
  await pane.getByRole("radio", { name: /An age/ }).click();
  await pane.getByRole("spinbutton", { name: /^Age it starts at/ }).fill("500");
  await pane.getByRole("button", { name: "Calculate" }).click();
  const answer = pane.locator(".mission-answer");
  await expect(answer).toContainText("Starting at 500 hours, the item lasts the mission's 200 hours", { timeout: 30_000 });
  await expect(answer).toContainText("90% one-sided lower bound");
  await pane.getByRole("button", { name: "Save", exact: true }).click();
  await shot(page, "plain-mission-1440");

  // The row sits under the Weibull with its start and chance; no phase rows under it.
  await expect(pane.getByRole("button", { name: "Save", exact: true })).toBeDisabled({ timeout: 20_000 });
  await pane.getByRole("button", { name: /Close/ }).first().click();
  const mission = nameRow(page, `Long shift ${tag}`);
  await expect(mission).toContainText("From 500 hours", { timeout: 20_000 });
  await expect(mission).toContainText("%");
  await expect(mission.locator(".tp-chev")).toHaveCount(0);

  await shot(page, "plain-mission-row-1440");
  await page.setViewportSize({ width: 400, height: 860 });
  await page.waitForTimeout(400);
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "plain-mission-400");
  // Opened on a phone: the same length, start and answer, nothing sideways.
  await mission.locator(".tp-nm").click();
  const side = page.getByRole("complementary", { name: "Details" });
  await expect(side).toContainText("one-sided lower bound");
  await expect(side).toContainText("200 hours · from 500 hours");
  await shot(page, "plain-mission-details-400");
  await side.getByRole("button", { name: "Open in the mission editor" }).click();
  await expect(pane.getByRole("spinbutton", { name: /^Length/ })).toHaveValue("200");
  await expect(pane.locator(".mission-answer")).toContainText("Starting at 500 hours", { timeout: 30_000 });
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "plain-mission-pane-400");
  await page.setViewportSize({ width: 1440, height: 900 });
  await expectHealthy(page, problems, { label: "a plain mission" });
});
