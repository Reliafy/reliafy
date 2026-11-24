// The Explorer's Operations tab: each position's duty as a column of the tree-table, "Own" or
// "From <the position above>", a click opening the position's operating plan beside the table,
// Clear going back to the duty above, an outage planned and inherited below, and the Summary's one
// line linking here. Phone width too: the rows carry the same words.
import { test, expect, open, expectHealthy } from "./health.js";

const M = "/api/maintenance";

test("operations: a duty at the site is inherited below, overridden and cleared", async ({ page, request, problems }) => {
  const tag = `ops${Date.now()}`;
  const post = async (path, data, method = "post") => {
    const res = await request[method](path, { data });
    expect(res.ok(), await res.text()).toBeTruthy();
    return res.json();
  };
  const site = await post(`${M}/positions`, { name: `Ops site ${tag}` });
  const line = await post(`${M}/positions`, { name: `Ops line ${tag}`, parent_id: site.id });
  const pump = await post(`${M}/positions`, { name: `Ops pump ${tag}`, parent_id: line.id });
  await post(`${M}/positions/${site.id}/operating-plan`, { plan: { background: { kind: "rate", amount: 8, per: "day" } } }, "put");
  const day = (n) => new Date(Date.now() + n * 86400000).toISOString().slice(0, 10);
  await post(`${M}/positions/${line.id}/out-of-service`, { reason: "Relining", start: day(20), until: day(34) });

  await open(page, `/asset-register/explorer?arrange=positions&root=${site.id}&sel=${pump.id}&tab=operations`);
  const tree = page.getByRole("treegrid").first();
  const row = (name) => tree.getByRole("row").filter({ hasText: name });
  await expect(row(`Ops site ${tag}`).getByText("Own", { exact: true })).toBeVisible();
  await expect(row(`Ops pump ${tag}`).getByText(`From Ops site ${tag}`, { exact: true })).toBeVisible();
  await expect(row(`Ops pump ${tag}`).getByText(/About 8 hours a day/)).toBeVisible();
  // The line's outage shows on the pump below it, saying where it's set.
  await expect(row(`Ops pump ${tag}`).getByText(new RegExp(`Relining · \\d{1,2} [A-Z][a-z]{2} \\d{4} to .* · from Ops line ${tag}`))).toBeVisible();

  // A click opens its operations beside the table: the plan, then the shutdowns.
  await row(`Ops line ${tag}`).getByText(`Ops line ${tag}`, { exact: true }).click();
  const pane = page.getByRole("region", { name: "Operations" });
  await expect(pane.getByText(`From Ops site ${tag}: it has no plan of its own`)).toBeVisible();
  await expect(pane.getByRole("region", { name: "Shutdowns and outages" }).getByText("Set here")).toBeVisible();
  await expect(pane.getByRole("button", { name: "Cancel the outage…" })).toBeVisible();

  // Its own duty, then Clear (use the site's).
  await post(`${M}/positions/${line.id}/operating-plan`, { plan: { background: { kind: "continuous" } } }, "put");
  await open(page, `/asset-register/explorer?arrange=positions&root=${site.id}&sel=${pump.id}&tab=operations&plan=${line.id}`);
  await expect(row(`Ops pump ${tag}`).getByText(`From Ops line ${tag}`, { exact: true })).toBeVisible();
  await pane.getByRole("button", { name: `Clear (use Ops site ${tag}'s)…` }).click();
  await page.getByRole("button", { name: `Clear (use Ops site ${tag}'s)`, exact: true }).click();
  await expect(row(`Ops pump ${tag}`).getByText(`From Ops site ${tag}`, { exact: true })).toBeVisible();

  // The Summary keeps one line, linking here.
  await open(page, `/asset-register/explorer?arrange=positions&root=${site.id}&sel=${pump.id}`);
  await page.getByRole("link", { name: "Open in Operations" }).click();
  await expect(page).toHaveURL(/tab=operations/);
  await expect(pane).toBeVisible();
  await expectHealthy(page, problems);
});

test("operations at phone width: each row says where its duty comes from", async ({ page, request, problems }) => {
  await page.setViewportSize({ width: 400, height: 800 });
  const tag = `opsp${Date.now()}`;
  const site = await (await request.post(`${M}/positions`, { data: { name: `Phone site ${tag}` } })).json();
  await request.post(`${M}/positions`, { data: { name: `Phone pump ${tag}`, parent_id: site.id } });
  await request.put(`${M}/positions/${site.id}/operating-plan`, { data: { plan: { background: { kind: "continuous" } } } });
  await open(page, `/asset-register/explorer?arrange=positions&root=${site.id}&sel=${site.id}&tab=operations`);
  await expect(page.getByText(`From Phone site ${tag} · All the time`)).toBeVisible();
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width).toBeLessThanOrEqual(400);
  await expectHealthy(page, problems);
});
