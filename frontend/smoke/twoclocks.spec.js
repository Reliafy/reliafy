// Two clocks (planning A15): a dataset of each unit's hours and landings (a second clock in its
// own unit, under the reading's "More columns") is fitted through New model, the model page
// answers in landings at the fleet's typical rate and at a rate typed in, and an RBD block on a
// model of hours and starts takes its starts per hour. At 1440 and 400 px, nothing scrolls sideways.
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name, fullPage = false) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

// A simulated fleet in three duties: one start is worth 20 hours; Weibull(30,000, 2.5) on the
// combined clock. A fixed generator, so every run fits the same data.
function fleetCsv(second = "starts") {
  let seed = 7;
  const rand = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
  const rows = [`hours,${second},status`];
  for (let i = 0; i < 160; i += 1) {
    const rate = [0.01, 0.05, 0.3][i % 3];
    const life = (30000 * (-Math.log(1 - rand())) ** (1 / 2.5)) / (1 + 20 * rate);
    const followed = 5000 + 20000 * rand();
    const failed = life < followed;
    const hours = Math.round(failed ? life : followed);
    rows.push(`${hours},${Math.round(rate * hours)},${failed ? 0 : 1}`);
  }
  return rows.join("\n");
}

async function fleetDataset(request, name, second = "starts") {
  const ds = await postOk(request, "/api/datasets/paste", { name, content: fleetCsv(second) });
  const res = await request.put(`/api/datasets/${ds.id}/reading`, {
    data: { reading: { x: "hours", x2: second, c: "status", unit: "Hours" } },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  return ds;
}

for (const width of [1440, 400]) {
  test(`fit a life on hours and landings and read it at a rate (${width} px)`, async ({ page, request, problems }) => {
    const ds = await fleetDataset(request, `Strut landings ${width} ${Date.now()}`, "landings");
    await page.setViewportSize({ width, height: 900 });
    await open(page, `/models/new?dataset=${ds.id}`);
    const reading = page.locator('[data-wt="reading-summary"]');
    await expect(reading).toContainText("second clock = landings");
    // The second clock lives under "More columns", open because it's in use, its unit from the column's name.
    await reading.getByRole("button", { name: "Change" }).click();
    const change = page.getByRole("region", { name: "Change how the columns are read" });
    const more = change.locator("details.rs-details", { hasText: "More columns" });
    await expect(more).toHaveAttribute("open", "");
    await expect(change.getByLabel("Unit of the second clock")).toHaveValue("landings");
    await change.getByLabel("Unit of the second clock").scrollIntoViewIfNeeded();
    await shot(page, `two-clocks-reading-${width}`, true);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await change.getByRole("button", { name: "Cancel" }).click();

    await page.locator('[data-wt="fit-run"]').click();
    await expect(page.getByText(/One landing wears it as much as [\d.]+ hours/)).toBeVisible({ timeout: 30_000 });
    const summary = page.locator(".tc-life .result-summary");
    await expect(summary).toContainText(/At 1 landing every [\d.]+ hours, its B10 life is [\d,]+ hours \(at least [\d,]+ hours, 90% one-sided\)/);
    await shot(page, `two-clocks-fit-${width}`, true);
    await page.getByLabel("Landings per hour").fill("1/8");
    await page.getByRole("button", { name: "Use this rate" }).click();
    await expect(summary).toContainText("1 landing every 8 hours");
    await expect(page.locator(".tc-panel")).not.toContainText(/start/i);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await expectHealthy(page, problems, { label: "two-clock fit", chart: true });

    await page.getByRole("tab", { name: "Model characteristics" }).click();
    await expect(page.getByText(/Landings clearly matter/)).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Landings per hour" })).toBeVisible();
    await shot(page, `two-clocks-characteristics-${width}`, true);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
  });

  test(`an RBD block on a life on hours and starts takes its starts per hour (${width} px)`, async ({ page, request, problems }) => {
    const ds = await fleetDataset(request, `Turbine starts block ${width} ${Date.now()}`);
    const res = await request.post("/api/models", {
      multipart: { name: `Turbine hot section ${width}`, distribution: "weibull_two_clock", dataset_id: ds.id,
                   x: "hours", x2: "starts", c: "status", unit: "Hours" },
    });
    expect(res.ok(), await res.text()).toBeTruthy();
    const saved = await res.json();
    const graph = {
      unit: "Hours",
      nodes: [
        { id: "input", type: "input", position: { x: 0, y: 0 }, data: {} },
        { id: "t1", type: "component", position: { x: 200, y: 0 },
          data: { label: "Turbine", model: { source: "saved", kind: "two_clock", modelId: saved.id, name: saved.name,
                                              distribution: saved.distribution, usage_rate: 0.125 } } },
        { id: "output", type: "output", position: { x: 400, y: 0 }, data: {} },
      ],
      edges: [{ id: "e1", source: "input", target: "t1" }, { id: "e2", source: "t1", target: "output" }],
    };
    const rbd = await request.post("/api/rbds", { data: { name: `Two-clock block ${width}`, graph, id: null,
                                                          expected_updated_at: null } });
    expect(rbd.ok(), await rbd.text()).toBeTruthy();
    const stored = await rbd.json();
    const id = stored.id;
    // The block analyses at its rate, saved with the diagram.
    const out = await request.post("/api/rbds/analyze", { data: { graph, rbd_id: id, evaluate_at: 1000 } });
    expect(out.ok(), await out.text()).toBeTruthy();
    await page.setViewportSize({ width, height: 900 });
    await open(page, `/systems/b/${id}`);
    await page.getByText("Turbine", { exact: true }).first().dblclick();
    await expect(page.getByLabel("Starts per hour")).toHaveValue("0.125");
    await shot(page, `two-clocks-rbd-block-${width}`, true);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await expectHealthy(page, problems, { label: "two-clock RBD block" });
  });
}
