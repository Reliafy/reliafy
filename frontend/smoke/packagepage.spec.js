// A work package's own page: its sentence, next visits and tasks, and Edit in a
// pane beside it (never a dialog), at desktop width and on a phone.
import { test, expect, open, expectHealthy, postOk } from "./health.js";

async function freshPackage(request) {
  const tag = `${Date.now() % 1000000}`;
  const p = await postOk(request, "/api/maintenance/positions", { name: `Smoke pump ${tag}` });
  const t1 = await postOk(request, `/api/maintenance/positions/${p.id}/tasks`, { name: `Check seal ${tag}`, interval: 1, unit: "weeks" });
  const t2 = await postOk(request, `/api/maintenance/positions/${p.id}/tasks`, { name: `Grease ${tag}`, interval: 1, unit: "months" });
  const pkg = await postOk(request, "/api/maintenance/packages", {
    name: `Smoke round ${tag}`, position_id: p.id, every: 1, unit: "weeks", weekday: "saturday",
    tasks: [t1.id, { task_id: t2.id, visit_rule: "nth", every_nth: 4 }] });
  return { pkg, tag, position: p };
}

for (const width of [1440, 400]) {
  test(`a package's page and its Edit pane at ${width} px`, async ({ page, request, problems }) => {
    const { pkg, tag, position } = await freshPackage(request);
    await page.setViewportSize({ width, height: 900 });
    await open(page, `/maintenance/packages/${pkg.id}`);
    await expect(page.getByRole("heading", { name: `Smoke round ${tag}`, level: 1 })).toBeVisible();
    await expect(page.locator(".maint-answer")).toContainText(/^Every Saturday, next visit /);
    await expect(page.getByRole("heading", { name: "Next visits" })).toBeVisible();
    await expect(page.getByRole("row", { name: new RegExp(`Grease ${tag}.*every 4th visit`) })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);

    await page.getByRole("button", { name: "Edit", exact: true }).click();
    const pane = page.getByRole("region", { name: "Edit package" });
    await expect(pane).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await pane.getByLabel("Trade (optional)").fill("Fitter");
    await pane.getByLabel(`Grease ${tag}: on which visits`).selectOption("every");
    await pane.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByRole("status")).toHaveText("Saved.");
    await expect(pane).toHaveCount(0);
    await expect(page.getByRole("row", { name: new RegExp(`Grease ${tag}.*every visit`) })).toBeVisible();
    const saved = await (await request.get(`/api/maintenance/packages/${pkg.id}`)).json();
    expect(saved.trade).toBe("Fitter");
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
    await expectHealthy(page, problems, { label: `package page at ${width} px` });
    await postOk(request, `/api/maintenance/packages/${pkg.id}/retire`, { reason: "smoke test" });
    await postOk(request, `/api/maintenance/positions/${position.id}/retire`, { reason: "smoke test" });
  });
}
