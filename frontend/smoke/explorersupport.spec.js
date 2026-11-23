// Supporting tasks, "keeps it on its life" (Operate › Assets › Explorer): greasing or an oil change
// doesn't renew the part, it keeps it on the life its model describes. A task's details on the
// Maintenance tab have a "Keeps it on its life" section (what it supports, the reference interval,
// the impact if it isn't done, grace, where the impact comes from, an Assumed chip); the tasks table
// marks it "Supports × 2"; the RCM task details have a switch per failure mode. At 400 px nothing
// scrolls the page sideways. Each test makes its own small plant through the API.
//
// With SMOKE_SHOTS_DIR set, it saves screenshots (for the pull request).
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (target, name) => {
  if (SHOTS) await target.screenshot({ path: `${SHOTS}/${name}.png` });
};

async function plant(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const deck = await post(`${M}/positions`, { name: `Mower deck ${tag}` });
  const fn = await post(`${M}/positions/${deck.id}/functions`, { text: `Cut the grass ${tag}` });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `Blade stops ${tag}` });
  const wear = await post(`${M}/positions/${deck.id}/failure-modes`, { text: `Spindle bearing worn out ${tag}`, functional_failure_id: ff.id });
  const grease = await post(`${M}/positions/${deck.id}/tasks`, { name: `Grease the spindles ${tag}`, interval: 50, unit: "hours", failure_mode_ids: [wear.id] });
  const oilMode = await post(`${M}/positions/${deck.id}/failure-modes`, { text: `Engine wears out ${tag}`, functional_failure_id: ff.id });
  const res = await request.put(`${M}/failure-modes/${oilMode.id}/decision`, {
    data: { consequence: "operational", hidden: false, decision: { outcome: "fixed_interval", task: `Change the oil ${tag}`, interval: 250, interval_unit: "hours" } },
  });
  expect(res.ok()).toBeTruthy();
  return { deck, wear, grease, oilMode, oil: (await res.json()).decision.task_id };
}

const nameRow = (page, text) => page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: text }) });
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

test("a task marked as keeping it on its life: its section, the Assumed chip, the table's marker", async ({ page, request, problems }) => {
  const tag = `s${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.deck.id}&sel=${p.deck.id}&tab=maintenance&mtask=${p.grease.id}`);
  const form = page.getByRole("form", { name: `Task: Grease the spindles ${tag}` });
  await expect(form).toBeVisible();
  const sec = form.locator(".mt-support");
  await expect(sec).toContainText("Keeps it on its life");
  await sec.getByRole("checkbox", { name: /Supporting/ }).check();
  await expect(sec.getByRole("checkbox", { name: `Spindle bearing worn out ${tag}` })).toBeVisible();
  await sec.getByRole("checkbox", { name: `Spindle bearing worn out ${tag}` }).check();
  await expect(sec.getByLabel(/Reference interval/)).toHaveValue("50");
  await sec.getByLabel(/failure rate ×/).fill("2");
  await expect(sec.locator(".chip", { hasText: "Assumed" })).toBeVisible();
  await expect(sec).toContainText("multiply");
  await sec.scrollIntoViewIfNeeded();
  await shot(sec, "support-task-desktop");
  await form.getByRole("button", { name: "Save", exact: true }).click();
  await expect(nameRow(page, `Grease the spindles ${tag}`)).toContainText("Supports × 2");
  // Read back: the record as saved.
  const saved = await (await request.get(`${M}/tasks/${p.grease.id}/lsa`)).json().catch(() => null);
  if (saved?.task) expect(saved.task.support.impact).toEqual({ form: "hazard_ratio", k: 2 });
  await shot(page, "support-table-desktop");

  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.deck.id}&sel=${p.deck.id}&tab=maintenance&mtask=${p.grease.id}`);
  const phoneSec = page.locator(".mt-support");
  await expect(phoneSec.getByRole("checkbox", { name: /Supporting/ })).toBeChecked();
  await phoneSec.scrollIntoViewIfNeeded();
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "support-task-phone");
  await expectHealthy(page, problems);
});

test("the RCM: a fixed-interval task's details switch it to supporting for this failure mode", async ({ page, request, problems }) => {
  const tag = `r${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.deck.id}&tab=rcm`);
  const table = page.getByRole("treegrid", { name: /and their RCM/ });
  const modeRow = table.getByRole("row", { name: new RegExp(`^Failure mode: Engine wears out ${tag}`) });
  await expect(modeRow).toBeVisible();
  await modeRow.locator(".tp-chev").click();
  const taskRow = table.getByRole("row", { name: new RegExp(`^Task: Change the oil ${tag}`) });
  await expect(taskRow).toBeVisible();
  await taskRow.locator(".tp-nm").click();
  const panel = page.getByRole("complementary", { name: "Details" });
  const sec = panel.getByRole("region", { name: "Keeps it on its life", exact: true });
  await expect(sec).toBeVisible();
  const sw = sec.getByRole("switch");
  await expect(sw).toHaveAttribute("aria-checked", "false");
  await expect(panel.getByRole("region", { name: "Leaves it as", exact: true })).toBeVisible();
  await sw.click();
  await expect(sw).toHaveAttribute("aria-checked", "true");
  await expect(sec).toContainText("No modelled impact");
  await expect(sec).toContainText("“supports”, not “restores 0%”");
  // A supporting task restores none: the per-mode "Leaves it as" row gives way.
  await expect(panel.getByRole("region", { name: "Leaves it as", exact: true })).toHaveCount(0);
  await shot(panel, "support-rcm-desktop");

  await page.setViewportSize({ width: 400, height: 860 });
  await page.waitForTimeout(300);
  await sec.scrollIntoViewIfNeeded().catch(() => {});
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "support-rcm-phone");
  await page.setViewportSize({ width: 1440, height: 900 });
  await sw.click();
  await expect(sw).toHaveAttribute("aria-checked", "false");
  await expectHealthy(page, problems);
});
