// A fleet forecast (Forecasts › a forecast): "Use the … still-running units" takes every unit in the
// model's data, a row with a count standing for that many units, so a warranty table's 2,872 units in the
// field forecast about 720 returns in six months (not the first 500's). A model typed from parameters has
// no running units, and its forecast page logs no error. A horizon that isn't a whole number of a new
// period stays as typed, and the page says why. Each test makes its own model through the API.
import { test, expect, open, expectHealthy } from "./health.js";

// (age in months, returned, still in the field): six monthly shipments.
const WARRANTY = [
  [1, 4, 0], [2, 7, 0], [3, 9, 0], [4, 10, 0], [5, 14, 0], [6, 12, 450],
  [1, 3, 0], [2, 6, 0], [3, 9, 0], [4, 12, 0], [5, 11, 470],
  [1, 5, 0], [2, 4, 0], [3, 7, 0], [4, 10, 460],
  [1, 3, 0], [2, 9, 0], [3, 11, 480],
  [1, 4, 0], [2, 5, 515],
  [1, 2, 497],
];

function warrantyCsv() {
  const rows = ["age_months,status,count"];
  for (const [age, failed, running] of WARRANTY) {
    if (failed) rows.push(`${age},0,${failed}`);
    if (running) rows.push(`${age},1,${running}`);
  }
  return `${rows.join("\n")}\n`;
}

async function fleetOn(request, modelId, name) {
  const res = await request.post("/api/fleet/fleets", { data: { name, model_id: modelId } });
  expect(res.ok(), await res.text()).toBeTruthy();
  return (await res.json()).id;
}

test("forecast: every still-running unit in the model's data is forecast", async ({ page, request, problems }) => {
  const tag = `w${Date.now()}`;
  const res = await request.post("/api/models", {
    multipart: {
      name: `Warranty ${tag}`, distribution: "weibull", x: "age_months", c: "status", n: "count", unit: "months",
      file: { name: "warranty.csv", mimeType: "text/csv", buffer: Buffer.from(warrantyCsv()) },
    },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  const fid = await fleetOn(request, (await res.json()).id, `Warranty fleet ${tag}`);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/forecasts/${fid}`);
  await page.getByRole("button", { name: /^Use the 2872 still-running units/ }).first().click();
  await expect(page.getByText("6 items · 2,872 units")).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Units" })).toBeVisible();
  await page.getByLabel(/^Usage per month/).fill("1");
  await page.getByLabel("Horizon").fill("6");
  await page.getByRole("button", { name: /Save & forecast/ }).first().click();
  // The hand figure: each unit's chance of failing in six months given its age, added up, about 720.
  const answer = page.getByText(/≈ [\d,]+ failures in the next/).first();
  await expect(answer).toBeVisible({ timeout: 30_000 });
  const n = Number((await answer.innerText()).match(/≈ ([\d,]+)/)[1].replace(/,/g, ""));
  expect(n).toBeGreaterThan(680);
  expect(n).toBeLessThan(780);
  await expectHealthy(page, problems, { label: "fleet forecast, every unit" });
});

test("forecast: a model typed from parameters has no running units and logs no error", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const res = await request.post("/api/models/from-params", {
    data: { name: `Typed ${tag}`, distribution: "weibull", unit: "months",
            params: [{ name: "alpha", value: 16 }, { name: "beta", value: 2 }] },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  const fid = await fleetOn(request, (await res.json()).id, `Typed fleet ${tag}`);
  const answers = [];
  page.on("response", (r) => { if (r.url().includes("/running-units")) answers.push(r.status()); });
  await open(page, `/forecasts/${fid}`);
  await expect.poll(() => answers.length).toBeGreaterThan(0);
  expect(answers.every((s) => s === 200)).toBeTruthy();
  await expect(page.getByRole("button", { name: /still-running units/ })).toHaveCount(0);

  // A horizon of 5 months isn't a whole number of years: it stays 5 months, and the page says why.
  await page.getByLabel(/^Usage per month/).fill("1");
  await page.getByLabel("Horizon").fill("5");
  const period = page.getByLabel("Period");
  await period.fill("years");
  await expect(page.getByTestId("fleet-period-note")).toContainText("5 months isn't a whole number of years");
  await period.blur();
  await expect(period).toHaveValue("months");
  await expect(page.getByLabel("Horizon")).toHaveValue("5");
  await expect(page.getByLabel(/^Usage per month/)).toHaveValue("1");
  // 12 months is exactly 1 year (singular), with the usage a year exact.
  await page.getByLabel("Horizon").fill("12");
  await period.fill("years");
  await expect(page.getByLabel("Horizon")).toHaveValue("1");
  await expect(page.getByLabel(/^Usage per year/)).toHaveValue("12");
  await expect(page.getByText(/1 year ·|· 1 year\b/).first()).toBeVisible();
  await expectHealthy(page, problems, { label: "fleet forecast, typed model" });
});
