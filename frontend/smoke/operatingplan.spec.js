// An operating plan on the Explorer's Operations tab (?plan=, beside the table): saved from
// the pane with set runs on top of a rate, inherited by the position inside it ("From …"), and
// kept inside the asset opened (a plan above ?root= is never used). Also the shared "How often"
// control on a task: a pattern and its next dates.
import { test, expect, open, expectHealthy } from "./health.js";
import { choose } from "./select.js";

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
  const base = `/asset-register/explorer?arrange=positions&root=${top.id}&tab=operations`;

  await open(page, `${base}&sel=${top.id}&plan=${top.id}`);
  const pane = page.getByRole("region", { name: "Operations" });
  await expect(pane.getByText(`Say how Plan station ${tag} runs`)).toBeVisible();
  // The "Reads as" line says what's entered, live; the date reads day first whatever the browser's language.
  await expect(pane.getByText("Monday to Friday, 06:00 to 22:00", { exact: true })).toBeVisible();
  await pane.getByRole("checkbox", { name: "Sat" }).check();
  await pane.getByRole("checkbox", { name: "Sun" }).check();
  await pane.getByLabel("Shift 1: start").fill("8");
  await pane.getByLabel("Shift 1: start").blur();
  await expect(pane.getByLabel("Shift 1: start")).toHaveValue("08:00");
  await expect(pane.getByText("Every day, 08:00 to 22:00", { exact: true })).toBeVisible();
  await expect(pane.getByLabel("From", { exact: true })).toHaveValue(/^\d{1,2} [A-Z][a-z]{2} \d{4}$/);
  await pane.getByRole("radio", { name: "Rate", exact: true }).click();
  await pane.getByLabel("Hours", { exact: true }).fill("3");
  await expect(pane.getByText("About 21 hours a week")).toBeVisible();
  await pane.getByRole("button", { name: "Save" }).click();
  // Shown in "How it runs now" and again in the list of its plans: check the summary.
  await expect(pane.getByRole("region", { name: "How it runs now" }).getByText("About 3 hours a day")).toBeVisible();

  // An old address on the Summary or Measurements tab moves to Operations, where the duty is now.
  await open(page, `/asset-register/explorer?arrange=positions&root=${top.id}&sel=${top.id}&plan=${top.id}`);
  await expect(page).toHaveURL(/tab=operations/);
  await expect(pane.getByText("About 3 hours a day").first()).toBeVisible();
  await open(page, `/asset-register/explorer?arrange=positions&root=${top.id}&tab=measurements&sel=${top.id}&plan=${top.id}`);
  await expect(page).toHaveURL(/tab=operations/);
  await expect(pane.getByText("About 3 hours a day").first()).toBeVisible();

  await open(page, `${base}&sel=${pump.id}&plan=${pump.id}`);
  await expect(pane.getByText(`From Plan station ${tag}`)).toBeVisible();
  await expect(pane.getByRole("button", { name: "Give this its own plan" })).toBeVisible();
  // Opened at the pump, the station's plan isn't looked for.
  await open(page, `/asset-register/explorer?arrange=positions&root=${pump.id}&tab=operations&sel=${pump.id}&plan=${pump.id}`);
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
  await choose(how.getByLabel("Which day"), "nth:1");
  await choose(how.getByLabel("Day of the week"), "Saturday");
  await expect(how.getByText(/^Next: Sat /)).toBeVisible();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("the first Saturday of every month").first()).toBeVisible();
  await expectHealthy(page, problems);
});
