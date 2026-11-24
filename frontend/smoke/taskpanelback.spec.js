// A task's details survive Back (Derryn, 23 Nov 2026: following "Based on" and pressing Back didn't
// return to the same place). The row open, and whether its details are across the table, are in the
// address (?fm= on the RCM tab, ?mtask= on Maintenance, ?wide=1), so Back and Forward restore them.
// Also: "Interval based on" shows the saved calculation's answer in one line, and the calculation
// itself in place (no dialog), started from its saved inputs.
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";

async function plant(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const mower = await post(`${M}/positions`, { name: `Back mower ${tag}` });
  const fn = await post(`${M}/positions/${mower.id}/functions`, { text: `Cut grass ${tag}` });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `Does not cut ${tag}` });
  const mode = await post(`${M}/positions/${mower.id}/failure-modes`, { text: `Belt breaks ${tag}`, functional_failure_id: ff.id });
  const analysis = await post("/api/strategy/analyses", {
    name: `Belt check interval ${tag}`, kind: "on_condition_interval",
    inputs: { pf_interval: 120, pf_unit: "hours", detection_probability: 1, unit: "hours" },
  });
  const res = await request.put(`${M}/failure-modes/${mode.id}/decision`, {
    data: { consequence: "operational", hidden: false, decision: {
      outcome: "on_condition", task: `Check the belt ${tag}`, interval: 50, interval_unit: "hours",
      evidence: { type: "strategy_analysis", id: analysis.id },
    } },
  });
  expect(res.ok()).toBeTruthy();
  return { mower, mode, analysis, task: (await res.json()).decision.task_id };
}

const panel = (page) => page.getByRole("complementary", { name: "Details" });
const query = (page) => new URL(page.url()).searchParams;

test("the RCM tab: a task's details, across the table, come back after following its evidence and pressing Back", async ({ page, request, problems }) => {
  const tag = `b${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.mower.id}&sel=${p.mower.id}&tab=rcm&fm=T:${p.mode.id}:${p.task}`);
  const heading = panel(page).getByRole("heading", { level: 2, name: `Check the belt ${tag}` });
  await expect(heading).toBeVisible();
  // Interval based on: the saved calculation's answer and inputs, its status, one action.
  const basis = panel(page).getByRole("group", { name: "Interval based on" });
  await expect(basis).toContainText("Check every 60 hours · from a P-F interval of 120 hours");
  await expect(basis).toContainText("Supported");
  await basis.getByRole("button", { name: /^Change: how often/ }).click();
  const calc = basis.getByRole("group", { name: "Work out the check interval" });
  await expect(calc.getByRole("spinbutton", { name: "P-F interval" })).toHaveValue("120");
  await expect(calc.locator(".ivc-answer")).toContainText("Check every 60 hours", { timeout: 15_000 });
  await expect(page.getByRole("dialog")).toHaveCount(0);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/interval-based-on-open-1440.png` });
  await basis.getByRole("button", { name: "Cancel" }).click();
  // Across the table: in the address.
  await panel(page).getByRole("button", { name: "Expand the details" }).click();
  await expect.poll(() => query(page).get("wide")).toBe("1");
  await expect.poll(() => query(page).get("fm")).toBe(`T:${p.mode.id}:${p.task}`);
  // Follow the saved calculation's link, then Back: the same details, still across the table.
  await basis.getByRole("link", { name: `Belt check interval ${tag}` }).click();
  await expect(page).toHaveURL(new RegExp(`/strategy/analyses/${p.analysis.id}`));
  await page.goBack();
  await expect(heading).toBeVisible();
  await expect(panel(page)).toHaveClass(/is-expanded/);
  expect(query(page).get("tab")).toBe("rcm");
  await expectHealthy(page, problems, { label: "rcm task back" });
});

test("the Maintenance tab: a task's details, across the table, come back after Open in RCM and Back", async ({ page, request, problems }) => {
  const tag = `n${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.mower.id}&sel=${p.mower.id}&tab=maintenance&mtask=${p.task}`);
  const form = page.getByRole("form", { name: `Task: Check the belt ${tag}` });
  await expect(form).toBeVisible();
  // The same one line for what the interval rests on, the way to its calculation in RCM.
  await expect(form.locator(".mt-basis")).toContainText("Check every 60 hours · from a P-F interval of 120 hours");
  await page.getByRole("button", { name: "Expand the details" }).click();
  await expect.poll(() => query(page).get("wide")).toBe("1");
  await form.getByRole("link", { name: "Open in RCM ›" }).click();
  await expect.poll(() => query(page).get("tab")).toBe("rcm");
  await page.goBack();
  await expect(form).toBeVisible();
  await expect(page.locator(".rw-panel.mt-task-panel")).toHaveClass(/is-expanded/);
  await expectHealthy(page, problems, { label: "maintenance task back" });
});
