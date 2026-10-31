// What a task by use counts, on the Explorer's RCM tab: the task's Edit…
// form (in the failure mode's details) shows its Measurement (what it counts,
// the latest reading, the last-done reading) and can change it; moving RCM
// whose task counts a measurement that isn't on the new position (Truck 12's
// engine hours, moved to Truck 14) asks what it should count there: the new
// position's counter (picked first, its reading when last done worked out
// from the date), the old one, or calendar time. Undo puts it back. At 400 px
// the question fits the screen. Each test makes its own small fleet through
// the API.
//
// With SMOKE_SHOTS_DIR set, it saves screenshots at 1280 and 400 px.
import { test, expect, open, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";

async function fleet(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const top = await post(`${M}/positions`, { name: `Fleet ${tag}` });
  const t12 = await post(`${M}/positions`, { name: `Truck 12 ${tag}`, parent_id: top.id });
  const t14 = await post(`${M}/positions`, { name: `Truck 14 ${tag}`, parent_id: top.id });
  const h12 = await post(`${M}/positions/${t12.id}/points`, { name: "Engine hours", kind: "counter", unit: "hours" });
  const h14 = await post(`${M}/positions/${t14.id}/points`, { name: "Engine hours", kind: "counter", unit: "hours" });
  for (const [on, a, b] of [["2026-01-01", 1000, 5000], ["2026-02-15", 1300, 5200], ["2026-03-15", 1900, 5600]]) {
    await post(`${M}/points/${h12.id}/readings`, { value: a, on });
    await post(`${M}/points/${h14.id}/readings`, { value: b, on });
  }
  const fn = await post(`${M}/positions/${t12.id}/functions`, { text: `Haul ore ${tag}` });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `Won't move ${tag}` });
  const mode = await post(`${M}/positions/${t12.id}/failure-modes`, { text: `Engine wears ${tag}`, functional_failure_id: ff.id });
  const task = await post(`${M}/failure-modes/${mode.id}/tasks`, { name: `Service ${tag}`, interval: 500, unit: "hours" });
  const done = await request.patch(`${M}/tasks/${task.id}`, { data: { last_done: "2026-03-01" } });
  expect(done.ok()).toBeTruthy();
  return { top, t12, t14, h12, h14, fn, ff, mode, task };
}

const table = (page) => page.getByRole("treegrid", { name: /and their RCM/ });
const trow = (page, name) => table(page).getByRole("row", { name: new RegExp(name) });
const toast = (page) => page.locator(".rcm-toast");
const settled = async (page) => {
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
  await page.waitForTimeout(250);
};
const measurementOf = async (request, id) => (await request.get(`${M}/tasks/${id}/measurement`)).json();
const overflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - innerWidth);

async function openFleet(page, p, width = 1280) {
  await page.setViewportSize({ width, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.top.id}&pin=${p.top.id}&tab=rcm`);
  await expect(table(page)).toBeVisible();
  await page.getByRole("button", { name: "Tree options" }).click();
  await page.getByRole("menuitemradio", { name: "Open everything" }).click();
  await page.keyboard.press("Escape");
  await settled(page);
}

test("a task's Edit… shows what it counts and can change it", async ({ page, request, problems }) => {
  const tag = `m${Date.now()}`;
  const p = await fleet(request, tag);
  await openFleet(page, p);
  await trow(page, `^Failure mode: Engine wears ${tag}`).locator(".tp-nm").dblclick();
  const dlg = page.getByRole("complementary", { name: "Details" });
  const tasks = dlg.getByRole("region", { name: "Tasks" });
  await tasks.getByRole("button", { name: `Edit Service ${tag}` }).click();
  const field = tasks.getByRole("group", { name: "Measurement" });
  await expect(field).toContainText(`Engine hours on Truck 12 ${tag}`);
  await expect(field).toContainText("Reads 1,900 hours");
  await expect(field).toContainText("at 1,600 hours");
  await field.getByRole("button", { name: "Change the measurement…" }).click();
  const pick = field.getByRole("combobox", { name: "Measurement to count" });
  await expect(pick).toBeVisible();
  await pick.selectOption(p.h12.id);
  // Chosen explicitly now: the last-done reading on it, worked out from the date (the same counter, so 1,600).
  await expect(field.getByRole("radio", { name: /Work it out from the date: about 1,600 hours/ })).toBeChecked();
  await field.getByRole("radio", { name: "Enter it" }).check();
  await field.getByRole("spinbutton", { name: /Reading when it was last done/ }).fill("1590");
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/task-measurement-1280.png` });
  await tasks.getByRole("button", { name: "Save task" }).click();
  await expect.poll(async () => {
    const v = await measurementOf(request, p.task.id);
    return [v.chosen, v.measurement?.id, v.last_done_reading, v.last_done_reading_estimated];
  }).toEqual([true, p.h12.id, 1590, false]);
  expect(problems.filter((x) => x.startsWith("uncaught"))).toEqual([]);
});

test("at 400 px, moving RCM whose task counts the old truck's hours asks, and Undo puts it back", async ({ page, request, problems }) => {
  const tag = `n${Date.now()}`;
  const p = await fleet(request, tag);
  await openFleet(page, p, 400);
  await trow(page, `^Function: Haul ore ${tag}`).getByRole("button", { name: "Actions", exact: true }).click();
  await page.getByRole("menu").getByRole("menuitem", { name: "Move to another position…" }).click();
  const move = page.getByRole("dialog", { name: `Move “Haul ore ${tag}”` });
  await move.getByRole("listbox", { name: "Where it goes" }).selectOption(p.t14.id);
  await expect(move.getByRole("status")).toContainText("It will ask what its tasks count there.");
  await move.getByRole("button", { name: "Move", exact: true }).click();

  const ask = page.getByRole("dialog", { name: `What should it count on Truck 14 ${tag}?` });
  await expect(ask).toBeVisible();
  await expect(ask).toContainText(`counts Engine hours on Truck 12 ${tag}, which isn't on Truck 14 ${tag}`);
  await expect(ask.getByRole("radio", { name: `Count a measurement on Truck 14 ${tag} instead` })).toBeChecked();
  await expect(ask.getByRole("combobox", { name: `Measurement for Service ${tag} to count` })).toHaveValue(p.h14.id);
  await expect(ask.getByRole("radio", { name: /Work it out from the date: about 5,400 hours/ })).toBeChecked();
  await expect(ask.getByRole("radio", { name: `Keep counting Engine hours on Truck 12 ${tag}` })).toBeVisible();
  await expect(ask.getByRole("radio", { name: "Go by calendar time instead" })).toBeVisible();
  expect(await overflow(page)).toBeLessThanOrEqual(0);
  const box = await ask.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(400);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/move-measurement-400.png` });
  await ask.getByRole("button", { name: "Move", exact: true }).click();
  await expect(ask).toHaveCount(0);
  await expect(toast(page)).toContainText("Moved");
  await expect.poll(async () => {
    const v = await measurementOf(request, p.task.id);
    return [v.subject.id, v.measurement?.id, v.last_done_reading, v.last_done_reading_estimated];
  }).toEqual([p.t14.id, p.h14.id, 5400, true]);
  await toast(page).getByRole("button", { name: "Undo" }).click();
  await expect(toast(page)).toContainText("Undone");
  await expect.poll(async () => {
    const v = await measurementOf(request, p.task.id);
    return [v.subject.id, v.chosen, v.measurement?.id, v.last_done_reading];
  }).toEqual([p.t12.id, false, p.h12.id, 1600]);
  expect(problems.filter((x) => x.startsWith("uncaught"))).toEqual([]);
});

test("the question can switch the task to calendar time instead", async ({ page, request }) => {
  const tag = `c${Date.now()}`;
  const p = await fleet(request, tag);
  await openFleet(page, p);
  await page.keyboard.press("Escape");
  const row = trow(page, `^Function: Haul ore ${tag}`);
  await row.locator(".tp-nm").click();
  await row.press("Shift+F10");
  await page.getByRole("menu").getByRole("menuitem", { name: "Move to another position…" }).click();
  const move = page.getByRole("dialog", { name: `Move “Haul ore ${tag}”` });
  await move.getByRole("listbox", { name: "Where it goes" }).selectOption(p.t14.id);
  await move.getByRole("button", { name: "Move", exact: true }).click();
  const ask = page.getByRole("dialog", { name: `What should it count on Truck 14 ${tag}?` });
  await ask.getByRole("radio", { name: "Go by calendar time instead" }).check();
  await ask.getByRole("button", { name: "Move", exact: true }).click();
  await expect(ask).toContainText("Say how often it falls due on the calendar.");
  await ask.getByRole("spinbutton", { name: `How often Service ${tag} falls due` }).fill("6");
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/move-measurement-calendar-1280.png` });
  await ask.getByRole("button", { name: "Move", exact: true }).click();
  await expect(toast(page)).toContainText("Moved");
  await expect.poll(async () => {
    const v = await measurementOf(request, p.task.id);
    return [v.by_use, v.subject.id];
  }).toEqual([false, p.t14.id]);
});
