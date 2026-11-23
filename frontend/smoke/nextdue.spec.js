// Next due on the Explorer's Maintenance tab (Derryn, 23 Nov 2026: "Next due" is a column, blank when
// we don't know). A task by running hours, last done at a reading, on a position with a duty: the
// reading it falls due at and a date from the duty, saying so. A weekly task with no record of when
// it was last done: a dash saying why, never a date counted from today. The task's details say the
// same. Nothing from another asset.
import { test, expect, open, expectHealthy } from "./health.js";

const M = "/api/maintenance";

function daysAgo(n) {
  const d = new Date(Date.now() - n * 86_400_000);
  return d.toISOString().slice(0, 10);
}

test("next due: hours and a date from the duty, a dash with why when it isn't known", async ({ page, request, problems }) => {
  const tag = `nd${Date.now()}`;
  const post = async (path, data, method = "post") => {
    const res = await request[method](path, { data });
    expect(res.ok(), await res.text()).toBeTruthy();
    return res.json();
  };
  const pump = await post(`${M}/positions`, { name: `Due pump ${tag}` });
  const other = await post(`${M}/positions`, { name: `Other site ${tag}` });
  await post(`${M}/positions/${pump.id}/operating-plan`, { plan: { background: { kind: "shifts", shifts: [
    { days: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], start: "06:00", stop: "22:00" }] } } }, "put");
  const meter = await post(`${M}/positions/${pump.id}/points`, { name: "Hour meter", kind: "counter", unit: "hours" });
  await post(`${M}/points/${meter.id}/readings`, { value: 12000, on: daysAgo(120) });
  await post(`${M}/points/${meter.id}/readings`, { value: 12340, on: daysAgo(2) });
  const service = await post(`${M}/positions/${pump.id}/tasks`, { name: `Service ${tag}`, interval: 2000, unit: "hours", last_done: daysAgo(120) });
  const inspect = await post(`${M}/positions/${pump.id}/tasks`, { name: `Inspect ${tag}`, interval: 1, unit: "weeks" });
  await post(`${M}/positions/${other.id}/tasks`, { name: `Elsewhere ${tag}`, interval: 1, unit: "months" });

  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${pump.id}&sel=${pump.id}&tab=maintenance`);
  const svc = page.locator(`[id="tp-MT:${service.id}"] .mt-c-due span`);
  await expect(svc).toHaveText(/^\d{1,2} \w{3} \d{4}$/);
  await expect(svc).toHaveAttribute("title", /Due at 14,000 h\. Hours from the operating plan/);
  const ins = page.locator(`[id="tp-MT:${inspect.id}"] .mt-c-due span`);
  await expect(ins).toHaveText("—");
  await expect(ins).toHaveAttribute("title", "No record of when this was last done");
  // The pump's own row: the soonest beneath it (the service).
  await expect(page.locator(`[id="tp-${pump.id}"] .mt-c-due`)).toHaveText(await svc.textContent());
  await expect(page.getByText(`Elsewhere ${tag}`)).toHaveCount(0);
  // The details say the same.
  await page.locator(`[id="tp-MT:${inspect.id}"] .tp-nm`).click();
  await expect(page.locator(".mt-due-basis")).toContainText("Next due: not known. No record of when this was last done.");
  await expectHealthy(page, problems, { label: "next due" });
});
