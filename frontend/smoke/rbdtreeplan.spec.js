// A repairable RBD's maintenance read from the tree (Derryn, 12 Nov 2026: "The RBD maintenance plan
// needs to come from the Explorer maintenance tasks"): a block standing for a position shows its
// position's task in the Maintenance plan, read only, with "Edit in the tree"; a position with no
// tasks runs to failure with "Add a task in the tree"; the position's Maintenance tab lists the
// RBDs that use its tasks. And New blank RBD… on a leaf's Modelling tab.
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { headMenu } from "./explorer.js";

const M = "/api/maintenance";
const SAMPLE = "sample-model-bearings-weibull";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

async function station(request, tag) {
  const plant = await postOk(request, `${M}/positions`, { name: `Tree plan station ${tag}` });
  const a = await postOk(request, `${M}/positions`, { name: `Pump A ${tag}`, parent_id: plant.id });
  const b = await postOk(request, `${M}/positions`, { name: `Pump B ${tag}`, parent_id: plant.id });
  for (const p of [a, b]) await postOk(request, `${M}/positions/${p.id}/models`, { model_id: SAMPLE });
  const task = await postOk(request, `${M}/positions/${a.id}/tasks`, {
    name: "Replace the seal", interval: 6, unit: "months", outcome: "fixed_interval",
  });
  const link = await postOk(request, `${M}/positions/${plant.id}/models`, { build_rbd: true });
  const rbd = await (await request.get(`/api/rbds/${link.model_id}`)).json();
  const graph = { ...rbd.graph, repairable: true, unit: "Hours" };
  for (const n of graph.nodes) {
    if (n.type === "component") n.data.repair = { distribution_id: "exponential", params: [{ name: "failure_rate", value: 0.1 }] };
  }
  await postOk(request, "/api/rbds", { id: rbd.id, name: rbd.name, graph });
  return { plant, a, b, task, rbdId: rbd.id };
}

for (const [w, h, label] of [[1440, 900, "desktop"], [400, 860, "phone"]]) {
  test(`the maintenance plan reads the tree (${label})`, async ({ page, request, problems }) => {
    const tag = `t${Date.now()}`;
    const { a, b, rbdId } = await station(request, tag);
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, `/systems/b/${rbdId}`);
    await page.locator('[data-wt="rbd-plan-chip"]').click();
    await page.setViewportSize({ width: w, height: h });
    const plan = page.getByRole("region", { name: "Maintenance plan" });
    await expect(plan.getByText(/take their maintenance from\s+that position's tasks/)).toBeVisible({ timeout: 15_000 });
    const rowA = plan.locator("tbody.is-tree", { hasText: `Pump A ${tag}` });
    await expect(rowA.getByText("Replace on age")).toBeVisible();
    await expect(rowA.getByText("“Replace the seal”")).toBeVisible();
    await expect(rowA.getByRole("link", { name: "Edit in the tree" })).toHaveAttribute("href", new RegExp(`sel=${a.id}.*tab=maintenance`));
    // Read only: no task picker on a tree row; duty is still the diagram's.
    await expect(rowA.getByRole("combobox", { name: /task/ })).toHaveCount(0);
    await expect(rowA.getByRole("textbox", { name: /duty/ })).toBeVisible();
    const rowB = plan.locator("tbody.is-tree", { hasText: `Pump B ${tag}` });
    await expect(rowB.getByText(`no maintenance tasks on Pump B ${tag}`)).toBeVisible();
    await expect(rowB.getByRole("link", { name: "Add a task in the tree" })).toHaveAttribute("href", new RegExp(`addtask=${b.id}`));
    await rowA.scrollIntoViewIfNeeded();
    await shot(page, `rbd-tree-plan-${w}`);
    expect(await sideways(page)).toBeLessThanOrEqual(1);
    await expectHealthy(page, problems, { label: `tree plan ${label}` });
  });
}

test("the position's Maintenance tab lists the RBDs that use its tasks", async ({ page, request, problems }) => {
  const tag = `u${Date.now()}`;
  const { a } = await station(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${a.id}&tab=maintenance`);
  const uses = page.getByRole("region", { name: "Used in RBDs" });
  await expect(uses).toBeVisible({ timeout: 15_000 });
  await expect(uses).toContainText("“Replace the seal” is its plan");
  await shot(page, "maintenance-tab-used-in-rbds-1440");
  await expectHealthy(page, problems, { label: "Maintenance tab, used in RBDs" });
});

test("New blank RBD… on a leaf: one block for itself, opened beside the tree", async ({ page, request, problems }) => {
  const tag = `n${Date.now()}`;
  const leaf = await postOk(request, `${M}/positions`, { name: `Leaf pump ${tag}` });
  await postOk(request, `${M}/positions/${leaf.id}/models`, { model_id: SAMPLE });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${leaf.id}&tab=models`);
  await headMenu(page);
  await page.getByRole("menuitem", { name: "RBD", exact: true }).click();
  const group = page.getByRole("menu", { name: "RBD" });
  await expect(group.getByRole("menuitem", { name: "Build from what's inside…" })).toBeDisabled();
  await group.getByRole("menuitem", { name: "New blank RBD…" }).click();
  const dialog = page.getByRole("dialog", { name: "New blank RBD" });
  await expect(dialog.getByRole("radio", { name: "Non-repairable" })).toHaveAttribute("aria-checked", "true");
  await expect(dialog.getByRole("radio", { name: new RegExp(`One block for Leaf pump ${tag}`) })).toBeChecked();
  await shot(page, "new-blank-rbd-1440");
  await dialog.getByRole("button", { name: "Start the RBD" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator(".rbd-pane .react-flow__node", { hasText: `Leaf pump ${tag}` })).toBeVisible({ timeout: 20_000 });
  await expectHealthy(page, problems, { label: "New blank RBD" });
});
