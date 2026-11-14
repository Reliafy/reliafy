// An operating plan in the Explorer's table area (?plan=), from the Measurements tab: saved from
// the pane with set runs on top of a rate, inherited by the position inside it ("From …"), and
// kept inside the asset opened (a plan above ?root= is never used). Also the shared "How often"
// control on a task: a pattern and its next dates.
import { test, expect, open, expectHealthy } from "./health.js";

const M = "/api/maintenance";

test("operating plan: set in the pane, inherited below, kept inside the asset", async ({ page, request, problems }) => {
  const tag = `op${Date.now()}`;
  const post = async (path, data) => {
    const res = await request.post(path, { data });
    expect(res.ok(), await res.text()).toBeTruthy();
    return res.json();
  };
  const top = await post(`${M}/positions`, { name: `Plan station ${tag}` });
  const pump = await post(`${M}/positions`, { name: `Plan pump ${tag}`, parent_id: top.id });
  const base = `/asset-register/explorer?arrange=positions&root=${top.id}&tab=measurements`;

  await open(page, `${base}&sel=${top.id}&plan=${top.id}`);
  const pane = page.getByRole("region", { name: "Operating plan" });
  await expect(pane.getByText(`Say how Plan station ${tag} runs`)).toBeVisible();
  await pane.getByLabel("Rate", { exact: true }).check();
  await pane.getByLabel("Hours", { exact: true }).fill("3");
  await expect(pane.getByText("About 21 hours a week")).toBeVisible();
  await pane.getByRole("button", { name: "Save" }).click();
  await expect(pane.getByText("About 3 hours a day")).toBeVisible();

  await open(page, `${base}&sel=${pump.id}&plan=${pump.id}`);
  await expect(pane.getByText(`From Plan station ${tag}`)).toBeVisible();
  await expect(pane.getByRole("button", { name: "Give this its own plan" })).toBeVisible();
  // Opened at the pump, the station's plan isn't looked for.
  await open(page, `/asset-register/explorer?arrange=positions&root=${pump.id}&tab=measurements&sel=${pump.id}&plan=${pump.id}`);
  await expect(pane.getByText(`Say how Plan pump ${tag} runs`)).toBeVisible();
  await expectHealthy(page, problems);
});

test("how often: a task on the first Saturday shows its next dates", async ({ page, request, problems }) => {
  const tag = `ho${Date.now()}`;
  const res = await request.post(`${M}/positions`, { data: { name: `How pump ${tag}` } });
  const pos = await res.json();
  const t = await (await request.post(`${M}/positions/${pos.id}/tasks`, { data: { name: "Grease", interval: 1, unit: "months" } })).json();
  await open(page, `/asset-register/explorer?arrange=positions&root=${pos.id}&sel=${pos.id}&tab=maintenance&mtask=${t.id}`);
  const how = page.getByRole("group", { name: "How often" });
  await how.getByLabel("Which day").selectOption("nth:1");
  await how.getByLabel("Day of the week").selectOption("Saturday");
  await expect(how.getByText(/^Next: Sat /)).toBeVisible();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("the first Saturday of every month").first()).toBeVisible();
  await expectHealthy(page, problems);
});
