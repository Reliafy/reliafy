// The mission tree's details (Derryn, 15 Nov 2026): a mission and each phase have their own details
// beside the tree; under each phase hang its covariates (automatic, from the life models of the
// mission's RBD) and its node status rules (added by hand: a block's state in the phase). A value
// set in a covariate's details and a rule added on a phase are the same settings the RBD builder's
// Phased mission… shows. Desktop and 400 px, nothing scrolling sideways.
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { choose, expectChosen } from "./select.js";

const M = "/api/maintenance";
const BEARING = "nswc-11:bearing-rolling-load-rating";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const nameRow = (page, text) => page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: text }) });
const exact = (page, text) => page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: new RegExp(`^${text}$`) }) });
const bind = (rating) => ({ bind: { source: "nswc", ref: BEARING, fixed: { L_S: rating, X: 1, Y: 0, R: 50 } } });

test("mission tree: details for missions and phases; covariate and node status rows; one store with the builder", async ({ page, request, problems }) => {
  const tag = `mt${Date.now()}`;
  const drone = await postOk(request, `${M}/positions`, { name: `Survey drone ${tag}` });
  const front = await postOk(request, `${M}/positions`, { name: `Front bearing ${tag}`, parent_id: drone.id });
  const rear = await postOk(request, `${M}/positions`, { name: `Rear bearing ${tag}`, parent_id: drone.id });
  await postOk(request, `${M}/positions/${front.id}/models`, bind(5000));
  await postOk(request, `${M}/positions/${rear.id}/models`, bind(8000));
  // Another asset: none of it may show while the drone is open.
  const other = await postOk(request, `${M}/positions`, { name: `Other asset ${tag}` });
  const made = await postOk(request, `${M}/positions/${drone.id}/missions`, { name: `Inspection ${tag}` });
  const rbdId = made.rbd.id;
  const put = await request.put(`/api/rbds/${rbdId}/missions/${made.mission.id}`, { data: { phases: [
    { name: "Take-off", duration: 0.2, values: { "Radial load": 1000, "Operating speed": 3600, "Bearing operating temperature": 90 } },
    { name: "Survey", duration: 3, values: { "Radial load": 600, "Bearing operating temperature": 40 } },
  ] } });
  expect(put.ok()).toBeTruthy();

  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${drone.id}&sel=${drone.id}&tab=missions`);
  const mission = nameRow(page, `Inspection ${tag}`);
  await expect(mission).toBeVisible();
  await expect(nameRow(page, `Other asset ${tag}`)).toHaveCount(0);

  // A click shows the mission's details beside the tree (not the editor).
  await mission.locator(".tp-nm").click();
  const side = page.getByRole("complementary", { name: "Details" });
  await expect(side).toContainText("Mission");
  await expect(side.getByRole("heading", { name: `Inspection ${tag}` })).toBeVisible();
  await expect(side.getByRole("table")).toContainText("Take-off");
  await expect(side.getByRole("button", { name: "Open in the RBD builder" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Mission" })).toHaveCount(0);
  // The survey's speed isn't set: the mission waits for it.
  await expect(side).toContainText("Needs values", { timeout: 30_000 });
  await shot(page, "mission-panel-1440");

  // Each phase opens to its covariates: automatic, from the bearings' covariate models.
  await mission.locator(".tp-chev").click();
  await exact(page, "Survey").locator(".tp-chev").click();
  const speed = page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: /^Operating speed$/ }) }).last();
  await expect(speed).toContainText("Needs a value");
  await exact(page, "Survey").locator(".tp-nm").click();
  await expect(side).toContainText("Phase 2 of 2");
  await expect(side.getByRole("region", { name: "Covariates in this phase" }).or(side.locator("section", { hasText: "Covariates in this phase" })).first()).toContainText("Operating speed");
  await expect(side.getByLabel(/^Duration/)).toHaveValue("3");
  await shot(page, "phase-panel-1440");

  // Set the speed in its details: the row shows it with its unit, and the mission is worked out.
  await speed.locator(".tp-nm").click();
  await expect(side).toContainText("Covariate · Use");
  await side.getByLabel(/^Value in Survey/).fill("1800");
  await side.getByRole("button", { name: "Save", exact: true }).click();
  await expect(speed).toContainText("1,800", { timeout: 20_000 });
  await expect(speed).not.toContainText("Needs a value");
  await shot(page, "covariate-panel-1440");

  // A node status rule, by hand on the phase: the rear bearing guaranteed working in the survey.
  await exact(page, "Survey").locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menuitem", { name: "Add node status rule…" }).click();
  await choose(side.getByLabel("Block"), { label: `Rear bearing ${tag}` });
  await choose(side.getByLabel("State in this phase"), "guaranteed");
  await side.getByRole("button", { name: "Add the rule" }).click();
  const rule = page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: `Rear bearing ${tag}` }) }).filter({ hasText: "Guaranteed working" });
  await expect(rule).toBeVisible({ timeout: 20_000 });
  await rule.locator(".tp-nm").click();
  await expect(side).toContainText("Node status rule");
  await expectChosen(side.getByLabel("State in this phase"), "guaranteed");
  await shot(page, "rule-panel-1440");

  // A covariate that changes within the phase (#372): the temperature follows a day/night schedule.
  const temp = page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: /^Bearing operating temperature$/ }) }).last();
  await temp.locator(".tp-nm").click();
  await side.getByRole("radio", { name: "Schedule" }).or(side.getByRole("button", { name: "Schedule", exact: true })).first().click();
  const expr = side.getByLabel(/as an expression in t/);
  await expr.fill("60 if t % 24 < 16 else 30");
  await expect(side).toContainText("from the start of the phase");
  await side.getByRole("button", { name: "Save", exact: true }).click();
  await expect(temp).toContainText("follows 60 if t % 24 < 16 else 30", { timeout: 20_000 });
  await shot(page, "covariate-schedule-1440");

  // One store: the RBD's own phases hold both.
  const saved = await (await request.get(`/api/rbds/${rbdId}`)).json();
  const survey = saved.graph.phases[1];
  expect(survey.values["Operating speed"]).toBe(1800);
  expect(survey.values["Bearing operating temperature"]).toEqual({ expression: "60 if t % 24 < 16 else 30" });
  expect(survey.guaranteed?.length).toBe(1);

  // The builder's Phased mission… shows the same values.
  await mission.locator(".tp-nm").click();
  await side.getByRole("button", { name: "Open in the RBD builder" }).click();
  const rbdPane = page.getByRole("region", { name: "RBD", exact: true });
  await expect(rbdPane.locator(".react-flow__node", { hasText: `Rear bearing ${tag}` })).toBeVisible({ timeout: 20_000 });
  await rbdPane.getByRole("button", { name: "More diagram settings" }).click();
  await page.getByRole("button", { name: /^Phased mission/ }).click();
  const modal = page.locator(".rbd-phases-modal");
  await modal.locator(".rbd-phase-needs summary").nth(1).click();
  await expectChosen(modal.getByRole("combobox", { name: `Rear bearing ${tag} in Survey` }), "guaranteed");
  await expect(modal.locator(".rbd-phase").nth(1).getByLabel(/^Operating speed/)).toHaveValue("1800", { timeout: 15_000 });
  await expect(modal.locator(".rbd-phase").nth(1).getByLabel(/^Bearing operating temperature.* as an expression in t/))
    .toHaveValue("60 if t % 24 < 16 else 30");
  await shot(page, "builder-phases-1440");
  await page.keyboard.press("Escape");

  // 400 px: the tree, then a phase's details as a sheet; nothing scrolls sideways.
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${drone.id}&sel=${drone.id}&tab=missions`);
  await nameRow(page, `Inspection ${tag}`).locator(".tp-chev").click();
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "mission-tree-400");
  await nameRow(page, `Inspection ${tag}`).locator(".tp-nm").click();
  await expect(side.getByRole("heading", { name: `Inspection ${tag}` })).toBeVisible();
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "mission-panel-400");
  await side.getByRole("button", { name: "Close the details" }).click();
  await exact(page, "Survey").locator(".tp-nm").click();
  await expect(side).toContainText("Phase 2 of 2");
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "phase-panel-400");
  await side.getByRole("button", { name: "Close the details" }).click();
  await exact(page, "Survey").locator(".tp-chev").click();
  await page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: /^Operating speed$/ }) }).last().locator(".tp-nm").click();
  await expect(side).toContainText("Covariate");
  await shot(page, "covariate-panel-400");
  await side.getByRole("button", { name: "Close the details" }).click();
  await page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: /^Bearing operating temperature$/ }) }).last().locator(".tp-nm").click();
  await expect(side.getByLabel(/as an expression in t/)).toHaveValue("60 if t % 24 < 16 else 30");
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "covariate-schedule-400");
  await side.getByRole("button", { name: "Close the details" }).click();
  await rule.locator(".tp-nm").click();
  await expect(side).toContainText("Node status rule");
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "rule-panel-400");
  expect(other.id).toBeTruthy();
  await expectHealthy(page, problems, { label: "the mission tree's details" });
});
