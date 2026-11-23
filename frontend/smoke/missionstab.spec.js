// The Explorer's Missions tab (Derryn, 23 Nov 2026): every mission here and below, each under the
// position it lives on, with its phases and their covariates; an empty position says so and offers
// New mission…; the form asks what it runs on, its start, length, calendar and starting state; the
// mission opens with its setup, its phases and its two answers as cards. Nothing scrolls sideways
// at 400 px.
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SAMPLE = "sample-model-bearings-weibull";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const nameRow = (page, text) => page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: text }) });

test("missions tab: empty, New mission…, its setup and two answers, at desktop and 400 px", async ({ page, request, problems }) => {
  const tag = `mt${Date.now()}`;
  const site = await postOk(request, `${M}/positions`, { name: `Water site ${tag}` });
  const station = await postOk(request, `${M}/positions`, { name: `Pump station ${tag}`, parent_id: site.id });
  for (const name of ["Pump A", "Pump B"]) {
    const p = await postOk(request, `${M}/positions`, { name: `${name} ${tag}`, parent_id: station.id });
    await postOk(request, `${M}/positions/${p.id}/models`, { model_id: SAMPLE });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${site.id}&sel=${station.id}&tab=missions`);
  const tabs = page.getByRole("tablist", { name: "What to show for this row" });
  await expect(tabs.getByRole("tab", { name: "Missions" })).toHaveAttribute("aria-selected", "true");
  // Nothing here yet: the table area says so, what a mission is for, New mission… and the guide.
  const landing = page.locator(".missions-landing");
  await expect(landing.getByRole("heading", { name: "No missions here" })).toBeVisible();
  await expect(landing).toContainText("saved what-if");
  await expect(landing.getByRole("link", { name: "Read the guide" }).or(landing.getByRole("button", { name: "Read the guide" }))).toBeVisible();
  await shot(page, "missions-tab-empty-desktop");

  // New mission… on the pump station: runs on its positions in series, 12 months at its own duty.
  await landing.getByRole("button", { name: "New mission…" }).click();
  await expect(page.getByRole("heading", { name: /New mission/ })).toBeVisible();
  await page.getByLabel("Mission name").fill(`Year of use ${tag}`);
  await expect(page.getByText("Its positions, in series")).toBeVisible();
  await page.getByRole("textbox", { name: "Length", exact: true }).or(page.getByRole("spinbutton", { name: "Length", exact: true })).fill("12");
  await page.getByRole("radio", { name: "Its own duty" }).click();
  // Exactly one calendar is chosen (a segmented control).
  await expect(page.getByRole("radiogroup", { name: "Calendar" }).getByRole("radio", { checked: true })).toHaveText("Its own duty");
  await page.getByRole("spinbutton", { name: "Hours a day" }).fill("8");
  await page.getByRole("spinbutton", { name: "Days a week" }).fill("5");
  await shot(page, "missions-new-form-desktop");
  await page.getByRole("button", { name: "Add the mission" }).click();

  // The mission's own details fill the table area: Set-up, Answers, Phases.
  await expect(page.getByRole("heading", { name: "Set-up" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Phases" })).toBeVisible();
  const cards = page.locator(".mission-cards");
  await expect(cards.getByRole("heading", { name: "Chance of completing" })).toBeVisible();
  await expect(cards.getByRole("heading", { name: "Failures to expect" })).toBeVisible();
  await expect(cards).toContainText(/missions like this finish without a system failure/);
  await expect(cards).toContainText(/Expect about .* part failures? over the/);
  await expect(page.locator(".mission-assumed")).toContainText("Planned maintenance isn't counted yet");
  await expect(page.locator(".mission-assumed")).toContainText("its own duty: 8 h a day, 5 days a week");
  // Its one phase, the whole length, in running hours (12 months at 40 h a week), in the phase table.
  await expect(page.locator(".mission-phase-table tbody tr")).toHaveCount(1);
  await expect(page.locator(".mission-phase-table tbody tr").first()).toContainText("2,087 hours");
  await expectHealthy(page, problems, { root: ".tx" });
  await shot(page, "missions-answers-desktop");

  // The mission is a row under the station, where it lives; the site above counts it (aggregated).
  await expect(nameRow(page, `Year of use ${tag}`)).toBeVisible();
  await page.getByRole("button", { name: "Close Mission" }).click().catch(() => {});

  // 400 px: nothing scrolls sideways, the tab and the mission alike.
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${site.id}&sel=${station.id}&tab=missions`);
  await expect(nameRow(page, `Year of use ${tag}`)).toBeVisible();
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "missions-tab-phone");
  const listed = await (await request.get(`${M}/position-missions?position_ids=${station.id}`)).json();
  const rbd = listed.links.find((l) => l.rbd?.mission_rbd).rbd.id;
  await open(page, `/asset-register/explorer?arrange=positions&root=${site.id}&sel=${station.id}&tab=missions&mission=${rbd}:mission&on=${station.id}`);
  await expect(page.locator(".mission-cards")).toContainText("Chance of completing");
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "missions-answers-phone");
});

test("missions tab: phases, their covariates and a schedule within a phase, as before", async ({ page, request, problems }) => {
  const tag = `mc${Date.now()}`;
  const seal = await postOk(request, `${M}/positions`, { name: `Valve seal ${tag}` });
  const link = await postOk(request, `${M}/positions/${seal.id}/models`, { model_id: "sample-model-seal-weibull-ph" });
  const made = await postOk(request, `${M}/positions/${seal.id}/missions`, {
    name: `Hot season ${tag}`, link_id: link.id, setup: { start: "2026-12-01", calendar: { linked: true }, from: "new" },
    length: { value: 30, unit: "days" },
  });
  const rbd = made.rbd.id;
  const detail = await (await request.get(`/api/rbds/${rbd}/missions/mission`)).json();
  const [first, second] = detail.covariates.map((c) => c.name);
  // Two phases: a constant value in the first; in the second, one covariate follows a schedule.
  const values1 = { [first]: 40, ...(second ? { [second]: 1 } : {}) };
  const values2 = { [first]: { expression: "40 if t < 120 else 80" }, ...(second ? { [second]: 1.5 } : {}) };
  const put = await request.put(`/api/rbds/${rbd}/missions/mission`, { data: {
    phases: [{ name: "Cool", duration: 360, values: values1 }, { name: "Hot", duration: 360, values: values2 }] } });
  expect(put.ok(), await put.text()).toBeTruthy();

  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${seal.id}&sel=${seal.id}&tab=missions`);
  const mission = nameRow(page, `Hot season ${tag}`);
  await expect(mission).toContainText("2 phases: Cool, Hot");
  await mission.locator(".tp-chev").click();
  const hot = page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: /^Hot$/ }) });
  await expect(hot).toContainText("Phase 2 of 2");
  await hot.locator(".tp-chev").click();
  await expect(nameRow(page, first).first()).toBeVisible();
  await shot(page, "missions-phases-covariates-desktop");

  // A click on the mission opens its details, filling the table area: the two answers over both
  // phases, and the phases as a compact table.
  await mission.locator(".tp-nm").click();
  await expect(page.locator(".mission-cards")).toContainText("Chance of completing");
  await expect(page.locator(".mission-assumed")).toContainText("2 phases");
  const table = page.locator(".mission-phase-table tbody tr");
  await expect(table).toHaveCount(2);
  await expect(table.nth(1)).toContainText("Hot");
  await expect(table.nth(1)).toContainText(/\d+(\.\d+)?%/);
  await expectHealthy(page, problems, { root: ".tx" });
  await shot(page, "mission-details-desktop");

  // A phase's own details: from the mission's table, then Next / Previous and Back to the mission.
  // (Its covariates: one value, or a schedule over the phase, edited in place.)
  await table.nth(0).getByRole("button", { name: "Cool", exact: true }).click();
  await expect(page.getByText(/Phase 1 of 2 · Hot season/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Covariates in this phase" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "What runs in this phase" })).toBeVisible();
  await page.getByRole("button", { name: "Next phase ›" }).click();
  await expect(page.getByText(/Phase 2 of 2 · Hot season/)).toBeVisible();
  await expect(page.getByLabel("Phase name")).toHaveValue("Hot");
  await expect(page.getByRole("heading", { name: "Result" })).toBeVisible();
  await expect(page.locator(".mission-phase-result-list")).toContainText("Still going");
  await expect(page.getByRole("radiogroup", { name: `One value or a schedule over the phase for ${first}` }).getByRole("radio", { checked: true })).toHaveText("Schedule");
  await expect(page.locator(".mission-cov-list")).not.toContainText("[object Object]");
  await shot(page, "phase-details-desktop");
  await page.getByRole("button", { name: /Back to Hot season/ }).click();
  await expect(page.getByRole("heading", { name: "Phases" })).toBeVisible();
  // The tree's phase row switches the panel in place to that phase.
  await hot.locator(".tp-nm").click();
  await expect(page.getByText(/Phase 2 of 2 · Hot season/)).toBeVisible();
  // Escape (or ×) closes it: the Missions table again.
  await page.getByRole("button", { name: /^Close/ }).first().click();
  await expect(page.locator(".mission-phase-table")).toHaveCount(0);

  // 400 px: each panel takes the screen; nothing scrolls sideways.
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${seal.id}&sel=${seal.id}&tab=missions&mission=${rbd}:mission&on=${seal.id}`);
  await expect(page.locator(".mission-cards")).toContainText("Chance of completing");
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "mission-details-phone");
  await page.locator(".mission-phase-table tbody tr").nth(1).getByRole("button", { name: "Hot", exact: true }).click();
  await expect(page.getByText(/Phase 2 of 2/)).toBeVisible();
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "phase-details-phone");
});
