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
  // The mission's length is every phase added up; opened, each phase's row shows its own.
  await expect(mission).toContainText("3.2 hours");
  await mission.locator(".tp-chev").click();
  const phaseRow = (name) => page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: new RegExp(`^${name}$`) }) });
  await expect(phaseRow("Take-off")).toContainText("0.2 hours");
  await expect(phaseRow("Survey")).toContainText("3 hours");
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
  // Saving works the saved mission out for the table. That answer is held back here, so the table
  // has read the missions again before it exists: the row still gets it (below, the pane closed).
  const calculation = "**/api/rbds/*/missions/*/calculate";
  await page.route(calculation, async (route) => {
    await new Promise((done) => setTimeout(done, 1500));
    await route.continue();
  });
  const workedOut = page.waitForResponse((res) => new URL(res.url()).pathname.endsWith("/calculate"));
  await pane.getByRole("button", { name: "Save" }).click();
  await expect(pane.getByRole("button", { name: "Save" })).toBeDisabled();
  await workedOut;
  await page.unroute(calculation);

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

// One RBD per mission: Add a mission on a position with no RBD builds the mission an RBD of its own
// from what's inside; the phase × block grid sets a pump on standby by day and the other by night;
// the result says what standby means; the mission's RBD opens in the shared builder beside the tree.
test("missions: each mission builds its own RBD; blocks set working, standby or not needed per phase", async ({ page, request, problems }) => {
  const tag = `mr${Date.now()}`;
  const station = await postOk(request, `${M}/positions`, { name: `Pump station ${tag}` });
  for (const name of ["Pump A", "Pump B"]) {
    const kid = await postOk(request, `${M}/positions`, { name: `${name} ${tag}`, parent_id: station.id });
    await postOk(request, `${M}/positions/${kid.id}/models`, { model_id: "sample-model-bearings-weibull" });
  }

  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${station.id}&tab=missions`);
  const stationRow = nameRow(page, `Pump station ${tag}`).first();
  await expect(stationRow).toContainText("Add a mission");
  await stationRow.locator(".tp-nm").click({ button: "right" });
  const made = page.waitForResponse((r) => r.url().includes(`${M}/positions/${station.id}/missions`) && r.request().method() === "POST");
  await page.getByRole("menuitem", { name: "Add a mission", exact: true }).click();
  expect((await made).status()).toBe(200);
  const pane = page.getByRole("region", { name: "Mission" });
  await expect(pane).toBeVisible();
  await expect(pane).toContainText(`Flown on Pump station ${tag} — Mission 1`);
  await expect(nameRow(page, "Mission 1")).toBeVisible();
  await shot(page, "mission-rbd-added-1440");

  // Two phases, then the grid: Pump B stands by by day, Pump A by night.
  await pane.getByRole("button", { name: "Add a phase" }).click();
  await pane.getByRole("button", { name: "Add a phase" }).click();
  const phases = pane.getByRole("list", { name: /phases/ }).locator(":scope > li");
  await phases.nth(0).getByLabel("Name of phase 1").fill("Day");
  await phases.nth(0).getByLabel(/Duration of phase 1/).fill("500");
  await phases.nth(1).getByLabel("Name of phase 2").fill("Night");
  await phases.nth(1).getByLabel(/Duration of phase 2/).fill("500");
  const grid = pane.getByRole("region", { name: "Blocks in each phase" });
  await expect(grid.getByRole("columnheader")).toContainText(["Block", "1 Day", "2 Night"]);
  await grid.getByRole("combobox", { name: `Pump B ${tag} in Day` }).selectOption("standby");
  await grid.getByRole("combobox", { name: `Pump A ${tag} in Night` }).selectOption("standby");
  await expect(grid.getByRole("combobox", { name: `Pump A ${tag} in Day` })).toHaveValue("working");
  await shot(page, "mission-grid-1440");
  await pane.getByRole("button", { name: "Calculate" }).click();
  const answer = pane.locator(".mission-answer");
  await expect(answer).toContainText("The mission completes with probability", { timeout: 30_000 });
  await expect(answer).toContainText("Standby: the block is there but not running");
  await pane.getByRole("button", { name: "Save" }).click();
  await expect(pane.getByRole("button", { name: "Save" })).toBeDisabled();
  await shot(page, "mission-result-1440", true);

  await page.setViewportSize({ width: 400, height: 860 });
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await grid.scrollIntoViewIfNeeded();
  await shot(page, "mission-grid-400");
  await answer.scrollIntoViewIfNeeded();
  await shot(page, "mission-result-400");
  await page.setViewportSize({ width: 1440, height: 900 });

  // The mission's own RBD, in the builder beside the tree.
  await pane.getByRole("button", { name: "open it" }).click();
  const rbdPane = page.getByRole("region", { name: "RBD", exact: true });
  await expect(rbdPane).toBeVisible();
  await expect(page).toHaveURL(/[?&]rbd=[\w-]+&on=/);
  await expect(rbdPane.locator(".react-flow__node", { hasText: `Pump A ${tag}` })).toBeVisible({ timeout: 20_000 });
  await shot(page, "mission-own-rbd-1440");
  await page.setViewportSize({ width: 400, height: 860 });
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "mission-own-rbd-400");
  await page.setViewportSize({ width: 1440, height: 900 });
  await expectHealthy(page, problems, { label: "a mission's own RBD" });
});
