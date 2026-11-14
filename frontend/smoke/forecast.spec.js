// The Maintenance tab's Forecast view (?mview=forecast) on a position: tasks by use put on dates
// through the operating plan, the answer first, the month table, and nothing from another asset.
import { test, expect, open, expectHealthy } from "./health.js";

const M = "/api/maintenance";

function daysAgo(n) {
  const d = new Date(Date.now() - n * 86_400_000);
  return d.toISOString().slice(0, 10);
}

test("forecast: the answer first, tasks by use on dates from the plan, kept inside the asset", async ({ page, request, problems }) => {
  const tag = `fc${Date.now()}`;
  const post = async (path, data, method = "post") => {
    const res = await request[method](path, { data });
    expect(res.ok(), await res.text()).toBeTruthy();
    return res.json();
  };
  const pump = await post(`${M}/positions`, { name: `Forecast pump ${tag}` });
  const other = await post(`${M}/positions`, { name: `Other site ${tag}` });
  await post(`${M}/positions/${pump.id}/operating-plan`, { plan: { background: { kind: "shifts", shifts: [
    { days: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], start: "06:00", stop: "22:00" }] } } }, "put");
  const meter = await post(`${M}/positions/${pump.id}/points`, { name: "Hour meter", kind: "counter", unit: "hours" });
  await post(`${M}/points/${meter.id}/readings`, { value: 12000, on: daysAgo(120) });
  await post(`${M}/points/${meter.id}/readings`, { value: 12340, on: daysAgo(2) });
  await post(`${M}/positions/${pump.id}/tasks`, { name: "Service", interval: 2000, unit: "hours", last_done: daysAgo(120) });
  await post(`${M}/positions/${pump.id}/tasks`, { name: "Inspect", interval: 1, unit: "weeks" });
  await post(`${M}/positions/${other.id}/tasks`, { name: `Elsewhere ${tag}`, interval: 1, unit: "months" });

  await open(page, `/asset-register/explorer?arrange=positions&root=${pump.id}&sel=${pump.id}&tab=maintenance&mview=forecast`);
  const view = page.getByRole("region", { name: "Forecast" });
  await expect(view.getByText(/^To \d+ \w+ \d{4}: \d+ tasks/)).toBeVisible();
  await expect(view.getByText(/Hours from the operating plan \(Monday to Friday, 06:00 to 22:00\)/).first()).toBeVisible();
  await expect(view.getByRole("table").first()).toBeVisible();
  await expect(view.getByText(/^Service \(/).first()).toBeVisible();
  await expect(page.getByText(`Elsewhere ${tag}`)).toHaveCount(0);
  await view.getByRole("radio", { name: "Quarters" }).click();
  await expect(view.getByRole("columnheader", { name: "Quarter" })).toBeVisible();
  await expectHealthy(page, problems);
});
