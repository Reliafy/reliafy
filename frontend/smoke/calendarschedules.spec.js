// Calendar schedules on a task (Nov 2026): the task panel's How often picks a type (Running hours,
// Days, weeks or months, Calendar rule, At shutdowns), then a short sentence; the rule in words and
// its next five dates show under it as you choose, worked out on the server. Set "the first
// Saturday of every month", save, and the task's Next due on the Maintenance tab is the first of
// those dates (a rule gives a definite next date, even with no record of it being done). At 400 px the control wraps and nothing scrolls sideways.
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { choose } from "./select.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

async function pump(request, tag) {
  const top = await postOk(request, `${M}/positions`, { name: `Pump station ${tag}` });
  const pos = await postOk(request, `${M}/positions`, { name: `Pump ${tag}`, parent_id: top.id });
  const task = await postOk(request, `${M}/positions/${pos.id}/tasks`, { name: `Inspect the guard ${tag}`, interval: 1, unit: "months" });
  return { top, pos, task };
}

for (const width of [1440, 400]) {
  test(`the first Saturday of every month on a task: the dates show, and its Next due is the first (${width} px)`, async ({ page, request, problems }) => {
    const tag = `c${width}${Date.now()}`;
    const p = await pump(request, tag);
    await page.setViewportSize({ width, height: 900 });
    await open(page, `/asset-register/explorer?arrange=positions&root=${p.top.id}&sel=${p.pos.id}&tab=maintenance&mtask=${p.task.id}`);
    const how = page.getByRole("group", { name: "How often" });
    await expect(how).toBeVisible();
    await how.getByRole("radio", { name: "Calendar rule" }).click();
    await choose(how.getByRole("combobox", { name: "How often it repeats" }), "months:1");
    await choose(how.getByRole("combobox", { name: "Which day" }), "nth:1");
    await choose(how.getByRole("combobox", { name: "Day of the week" }), "Saturday");
    // The rule in words, then the next five dates (each a Saturday), from the server.
    const dates = how.locator(".ho-dates");
    await expect(dates).toContainText("The first Saturday of every month.");
    await expect(dates).toContainText(/Next: (Sat[^·]+ · ){4}Sat/);
    await shot(page, `calendar-rule-editor-${width}`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await page.getByRole("button", { name: "Save", exact: true }).click();

    // Saved: its next due is the first Saturday of a month.
    await expect.poll(async () => {
      const r = await request.get(`${M}/tasks/${p.task.id}/lsa`);
      return (await r.json()).task?.rule_text || "";
    }).toBe("the first Saturday of every month");
    const saved = (await (await request.get(`${M}/tasks/${p.task.id}/lsa`)).json()).task;
    const due = new Date(`${saved.next_due}T00:00:00Z`);
    expect(due.getUTCDay()).toBe(6);
    expect(due.getUTCDate()).toBeLessThanOrEqual(7);

    // The Maintenance tab: the interval column says the rule; Next due is its first date.
    await open(page, `/asset-register/explorer?arrange=positions&root=${p.top.id}&sel=${p.pos.id}&tab=maintenance`);
    const row = page.locator(`[id="tp-MT:${p.task.id}"]`);
    await expect(row).toBeVisible();
    const words = due.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
    if (width > 720) {
      await expect(row).toContainText("The first Saturday of every month");
      await expect(row.locator(".mt-c-due")).toHaveText(words);
    } else {
      await expect(row).toContainText(`Due ${words}`);
    }
    await shot(page, `calendar-rule-next-due-${width}`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await expectHealthy(page, problems, { label: `calendar schedules ${width}` });
  });
}
