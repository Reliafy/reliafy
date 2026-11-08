// A work order's "Readings and settings": the points its task asks for (a tool
// the task uses reads one, a setting on its position) each get a value box, a
// setting's prefilled with its value. Record saves one now; closing records the
// rest, and the setting's history names the work order.
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";

async function changeOver(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const pool = await post(`${M}/positions`, { name: `WO pool ${tag}` });
  const chl = await post(`${M}/positions/${pool.id}/points`, { name: `Chlorinator ${tag}`, kind: "setting", unit: "%" });
  await post(`${M}/points/${chl.id}/readings`, { value: 45, on: new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10) });
  const salt = await post(`${M}/positions/${pool.id}/points`, { name: `Salt ${tag}`, kind: "condition", unit: "ppm" });
  const task = await post(`${M}/positions/${pool.id}/tasks`, { name: `Change-over ${tag}`, interval: 6, unit: "months" });
  const r = await request.patch(`${M}/tasks/${task.id}`, { data: { resources: { tools: [{ name: "Salt meter", point_id: salt.id }] } } });
  expect(r.ok(), await r.text()).toBeTruthy();
  const wo = await post(`${M}/work-orders`, { position_id: pool.id, title: `Change-over ${tag}`, type: "preventive", task_id: task.id });
  return { pool, chl, salt, task, wo };
}

test("a work order records a reading now and a new setting when it closes", async ({ page, request, problems }) => {
  const tag = `w${Date.now()}`;
  const p = await changeOver(request, tag);
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/maintenance/work-orders/${p.wo.id}`);
  const section = page.getByRole("region", { name: "Readings and settings" });
  await expect(section).toBeVisible();
  await expect(section.getByText("Readings: 0 of 2 recorded")).toBeVisible();
  const setting = section.getByLabel(new RegExp(`^Chlorinator ${tag}`));
  await expect(setting).toHaveValue("45");
  // Record one now.
  await section.getByLabel(new RegExp(`^Salt ${tag}`)).fill("3200");
  await section.getByRole("button", { name: "Record", exact: true }).click();
  await expect(section.getByText("Readings: 1 of 2 recorded")).toBeVisible();
  await expect(section.locator(".maint-list li")).toContainText([`Salt ${tag} 3200 ppm`]);
  // The new setting goes in with the close.
  await setting.fill("60");
  await page.getByLabel("What was done").selectOption("other");
  await page.getByRole("button", { name: "Close work order" }).click();
  await expect(section.locator(".maint-list li")).toContainText([`Chlorinator ${tag} set to 60% (from 45%)`]);
  await expectHealthy(page, problems, { label: "work order with readings" });
  const point = await (await request.get(`${M}/points/${p.chl.id}`)).json();
  expect(point.changes[0]).toMatchObject({ value: 60, from: 45, work_order_id: p.wo.id, task_id: p.task.id });
});

test("the readings section at 400 px: nothing scrolls sideways", async ({ page, request }) => {
  const p = await changeOver(request, `n${Date.now()}`);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/maintenance/work-orders/${p.wo.id}`);
  await expect(page.getByRole("region", { name: "Readings and settings" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
});
