// Open in › (Hours, Spares, Cost forecast) inside an asset opened with ?root=: a task row with a
// place opened forecasts, as does a position carried by a fitted item; a node outside the asset is
// refused once, saying what to do (one message, not a note and a box).
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";

test("Open in › from a task with a place opened forecasts; outside the asset it's refused once", async ({ page, request, problems }) => {
  const tag = `i${Date.now()}`;
  const post = (path, data) => postOk(request, path, data);
  const room = await post(`${M}/locations`, { name: `Plant room ${tag}` });
  const top = await post(`${M}/positions`, { name: `Boiler house ${tag}`, location_id: room.id });
  const boiler = await post(`${M}/positions`, { name: `Boiler ${tag}`, parent_id: top.id });
  const task = await post(`${M}/positions/${boiler.id}/tasks`, { name: `Service the burner ${tag}`, interval: 3, unit: "months" });
  const other = await post(`${M}/positions`, { name: `Elsewhere ${tag}` });
  const away = await post(`${M}/positions/${other.id}/tasks`, { name: `Not here ${tag}`, interval: 1, unit: "months" });
  await page.setViewportSize({ width: 1440, height: 900 });

  await open(page, `/forecasts/hours?from=task%3A${task.id}&root=${room.id}`);
  await expect(page.locator(".ft-from")).toContainText(`Service the burner ${tag}`, { timeout: 30_000 });
  await expect(page.locator(".ft-lines")).toContainText(`Service the burner ${tag}`);
  await expect(page.locator(".load-failed")).toHaveCount(0);
  await expectHealthy(page, problems, { label: "forecast from a place" });

  await open(page, `/forecasts/costs?from=task%3A${away.id}&root=${room.id}`);
  const box = page.locator(".load-failed");
  await expect(box).toHaveCount(1, { timeout: 30_000 });
  await expect(box).toContainText("Open the Explorer on the whole register to forecast it.");
  await expect(page.getByText("isn't inside the asset opened")).toHaveCount(1);
  await expect(page.locator(".ft-from")).toHaveCount(0);
});
