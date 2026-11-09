// Missions (Derryn, 9 Nov 2026: "Products need an RBD tab, called Missions"; "Missions are RBDs,
// so they belong to positions"): a survey drone whose two motor bearings are NSWC-11 covariate
// models (design fixed at each position, use and environment left open), its RBD built from the
// tree, and a mission of two phases at different temperatures. The Missions tab lists it under the
// drone; opening it shows each phase's covariates with the blocks they feed; a value missing makes
// that phase wait, then set it and the result comes per phase and for the whole mission. The
// gimbal inside has its own RBD and its own mission, and doesn't show the drone's. Nothing scrolls
// sideways at 400 px.
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const BEARING = "nswc-11:bearing-rolling-load-rating";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name, full = false) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: full });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const nameRow = (page, text) => page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: text }) });
const bind = (rating) => ({ bind: { source: "nswc", ref: BEARING, fixed: { L_S: rating, X: 1, Y: 0, R: 50 } } });

test("missions: a product's mission by phase, its covariates with the blocks they feed, a sub-position's own", async ({ page, request, problems }) => {
  const tag = `ms${Date.now()}`;
  const drone = await postOk(request, `${M}/positions`, { name: `Survey drone ${tag}` });
  const front = await postOk(request, `${M}/positions`, { name: `Front motor bearing ${tag}`, parent_id: drone.id });
  const rear = await postOk(request, `${M}/positions`, { name: `Rear motor bearing ${tag}`, parent_id: drone.id });
  const gimbal = await postOk(request, `${M}/positions`, { name: `Gimbal ${tag}`, parent_id: drone.id });
  const pivot = await postOk(request, `${M}/positions`, { name: `Gimbal pivot ${tag}`, parent_id: gimbal.id });
  await postOk(request, `${M}/positions/${front.id}/models`, bind(5000));
  await postOk(request, `${M}/positions/${rear.id}/models`, bind(8000));
  await postOk(request, `${M}/positions/${pivot.id}/models`, bind(3000));
  const built = await postOk(request, `${M}/positions/${drone.id}/models`, { build_rbd: true });
  const gimbalRbd = await postOk(request, `${M}/positions/${gimbal.id}/models`, { build_rbd: true });

  // A mission of two phases at different temperatures; the survey's speed not set yet.
  const made = await postOk(request, `/api/rbds/${built.model_id}/missions`, {
    name: `Corridor inspection ${tag}`,
    phases: [
      { name: "Take-off", duration: 0.2, values: { "Radial load": 1000, "Operating speed": 3600, "Bearing operating temperature": 90 } },
      { name: "Survey", duration: 3, values: { "Radial load": 600, "Bearing operating temperature": 40 } },
    ],
  });
  await postOk(request, `/api/rbds/${gimbalRbd.model_id}/missions`, {
    name: `Stabilise ${tag}`, phases: [{ name: "Hover", duration: 1, values: { "Radial load": 50, "Operating speed": 300 } }],
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${drone.id}&tab=missions`);
  await expect(page.getByRole("tab", { name: "Missions" })).toHaveAttribute("aria-selected", "true");
  const mission = nameRow(page, `Corridor inspection ${tag}`);
  await expect(mission).toBeVisible();
  await expect(mission).toContainText("2 phases: Take-off, Survey");
  // The gimbal's own mission is under the gimbal; the drone's isn't repeated there.
  await nameRow(page, `Gimbal ${tag}`).first().locator(".tp-chev").click();
  await expect(nameRow(page, `Stabilise ${tag}`)).toBeVisible();
  await expect(nameRow(page, `Front motor bearing ${tag}`)).toContainText("No RBD yet");
  await expect(nameRow(page, `Corridor inspection ${tag}`)).toHaveCount(1);

  // Open the mission: the table area, phases as rows.
  await mission.locator(".tp-nm").dblclick();
  const pane = page.getByRole("region", { name: "Mission" });
  await expect(pane).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`[?&]mission=${built.model_id}(%3A|:)${made.mission.id}`));
  const phases = pane.getByRole("list", { name: /phases/ });
  await expect(phases.locator(":scope > li")).toHaveCount(2);

  // Take-off is open: its covariates, grouped Use / Environment, with the blocks each feeds.
  const takeoff = phases.locator(":scope > li").nth(0);
  const covs = takeoff.getByRole("region", { name: "Covariates in Take-off" });
  await expect(covs.getByRole("group", { name: "Use" })).toBeVisible();
  await expect(covs.getByRole("group", { name: "Environment" })).toBeVisible();
  await expect(covs).toContainText(`Feeds Front motor bearing ${tag} and Rear motor bearing ${tag} (2 blocks)`);
  await expect(covs.getByRole("textbox", { name: "Bearing operating temperature", exact: true })).toHaveValue("90");

  // The survey waits: its speed is missing, and the result says how far it got.
  await expect(pane.getByRole("status").or(pane.locator(".mission-answer")).first()).toContainText(/Survey needs values first/, { timeout: 30_000 });
  const survey = phases.locator(":scope > li").nth(1);
  await survey.getByRole("button", { name: /Open phase 2/ }).click();
  const surveyCovs = survey.getByRole("region", { name: "Covariates in Survey" });
  await expect(surveyCovs.getByRole("textbox", { name: "Bearing operating temperature", exact: true })).toHaveValue("40");
  await expect(surveyCovs).toContainText("needs a value");
  await shot(page, "mission-phase-covariates-1440");
  await page.setViewportSize({ width: 400, height: 860 });
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "mission-phase-covariates-400");
  await page.setViewportSize({ width: 1440, height: 900 });

  // Set it once for the phase: every block using it takes it.
  await surveyCovs.getByRole("textbox", { name: "Operating speed", exact: true }).fill("1800");
  await expect(surveyCovs).not.toContainText("needs a value");
  // The rear bearing runs slower in the survey: its own value, shown on its row.
  await surveyCovs.getByRole("combobox", { name: "Set a block's own Operating speed in this phase" })
    .selectOption({ label: `Rear motor bearing ${tag}` });
  await surveyCovs.getByLabel(`Rear motor bearing ${tag}'s own in this phase`).fill("1200");
  await expect(surveyCovs).toContainText("The other uses 1800 rpm (this phase)");
  await pane.getByRole("button", { name: "Calculate" }).click();
  const answer = pane.locator(".mission-answer");
  await expect(answer).toContainText("The mission completes with probability", { timeout: 30_000 });
  await expect(takeoff).toContainText("Completes");
  await expect(survey).toContainText("still going");
  await expect(survey).toContainText("Weakest:");
  await pane.getByRole("button", { name: "Save" }).click();
  await expect(pane.getByRole("button", { name: "Save" })).toBeDisabled();

  // Show the RBD for the survey: the diagram, drawn read-only.
  await survey.getByRole("button", { name: "Show the RBD" }).click();
  await expect(survey.getByRole("img", { name: /The RBD in Survey/ })).toBeVisible();

  // Back to the table: the mission's chance of completing is in its row.
  await page.keyboard.press("Escape");
  await expect(pane).toHaveCount(0);
  await expect(nameRow(page, `Corridor inspection ${tag}`)).toContainText("%");
  await shot(page, "missions-tab-1440");

  // At 400 px: the tab, then the mission on its own screen with Back.
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${drone.id}&tab=missions`);
  await expect(nameRow(page, `Corridor inspection ${tag}`)).toBeVisible();
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "missions-tab-400");
  await open(page, `/asset-register/explorer?arrange=positions&sel=${drone.id}&tab=missions&mission=${built.model_id}:${made.mission.id}&on=${drone.id}`);
  await expect(pane).toBeVisible();
  await expect(pane.getByRole("button", { name: "Back to the table" })).toBeVisible();
  await expect(pane.locator(".mission-answer")).toContainText("The mission completes with probability", { timeout: 30_000 });
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "mission-open-400");
  await page.setViewportSize({ width: 1440, height: 900 });
  await shot(page, "mission-open-1440");
  await expectHealthy(page, problems, { label: "missions on the Explorer" });
});
