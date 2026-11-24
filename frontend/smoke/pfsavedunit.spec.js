// A task with a saved P-F calculation in flight hours: "Interval based on" opens in place showing
// the saved inputs and their unit (not empty, not weeks).
import { test, expect, open, postOk } from "./health.js";
import { choose, expectChosen } from "./select.js";

const M = "/api/maintenance";
const panel = (page) => page.getByRole("complementary", { name: "Details" });

async function plant(request, tag, unit) {
  const post = (path, data) => postOk(request, path, data);
  const jet = await post(`${M}/positions`, { name: `Jet ${tag}` });
  const fn = await post(`${M}/positions/${jet.id}/functions`, { text: `Fly ${tag}` });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `Does not fly ${tag}` });
  const mode = await post(`${M}/positions/${jet.id}/failure-modes`, { text: `Crack ${tag}`, functional_failure_id: ff.id });
  const analysis = await post("/api/strategy/analyses", {
    name: `Crack check ${tag}`, kind: "on_condition_interval",
    inputs: { pf_interval: 400, pf_unit: unit, act_time: 20, detection_probability: 0.9, unit },
  });
  const res = await request.put(`${M}/failure-modes/${mode.id}/decision`, {
    data: { consequence: "operational", hidden: false, decision: {
      outcome: "on_condition", task: `Check the crack ${tag}`, interval: 100, interval_unit: unit,
      evidence: { type: "strategy_analysis", id: analysis.id },
    } },
  });
  expect(res.ok()).toBeTruthy();
  return { jet, mode, task: (await res.json()).decision.task_id };
}

for (const unit of ["flight hours", "cycles"]) {
  test(`the saved P-F calculation in ${unit} opens with its inputs and unit`, async ({ page, request, problems }) => {
    const tag = `u${Date.now()}`;
    const p = await plant(request, tag, unit);
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, `/asset-register/explorer?arrange=positions&root=${p.jet.id}&sel=${p.jet.id}&tab=rcm&fm=T:${p.mode.id}:${p.task}`);
    const basis = panel(page).getByRole("group", { name: "Interval based on" });
    await expect(basis).toContainText(`from a P-F interval of 400 ${unit}`);
    await basis.getByRole("button", { name: /^Change: how often/ }).click();
    const calc = basis.getByRole("group", { name: "Work out the check interval" });
    await expect(calc.getByRole("spinbutton", { name: "P-F interval" })).toHaveValue("400");
    await expectChosen(calc.getByRole("combobox", { name: "P-F interval unit" }), unit);
    await expect(calc.getByRole("spinbutton", { name: "Time needed to act" })).toHaveValue("20");
  });
}

// A task every 25 hours of the position's Flight hours counter, nothing worked out yet: the unit
// list has flight hours (and starts there), the answer needs no costs, and it says how many
// warnings a check finds in time at the answer and at the task's 25 now. In calendar hours a cost
// of a check alone (the task's own, filled in) never stops the answer.
test("a task by its Flight hours counter: P-F in flight hours, warnings found at 25 and 60", async ({ page, request }) => {
  const tag = `m${Date.now()}`;
  const post = (path, data) => postOk(request, path, data);
  const jet = await post(`${M}/positions`, { name: `Jet ${tag}` });
  await post(`${M}/positions/${jet.id}/points`, { name: "Flight hours", kind: "counter", unit: "hours" });
  const fn = await post(`${M}/positions/${jet.id}/functions`, { text: `Fly ${tag}` });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `Does not fly ${tag}` });
  const mode = await post(`${M}/positions/${jet.id}/failure-modes`, { text: `Belt worn ${tag}`, functional_failure_id: ff.id });
  const res = await request.put(`${M}/failure-modes/${mode.id}/decision`, {
    data: { consequence: "operational", hidden: false, decision: {
      outcome: "on_condition", task: `Inspect the belt ${tag}`, interval: 25, interval_unit: "hours" } },
  });
  expect(res.ok()).toBeTruthy();
  const taskId = (await res.json()).decision.task_id;
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${jet.id}&sel=${jet.id}&tab=rcm&fm=T:${mode.id}:${taskId}`);
  const basis = panel(page).getByRole("group", { name: "Interval based on" });
  await basis.getByRole("button", { name: /^Work it out: how often/ }).click();
  const calc = basis.getByRole("group", { name: "Work out the check interval" });
  const unit = calc.getByRole("combobox", { name: "P-F interval unit" });
  await expectChosen(unit, "flight hours");
  await calc.getByRole("spinbutton", { name: "P-F interval" }).fill("120");
  await calc.getByRole("spinbutton", { name: /Chance a check finds the warning/ }).fill("90");
  await calc.getByRole("button", { name: "Work it out", exact: true }).click();
  const result = calc.getByRole("status");
  await expect(result).toContainText("Check every 60 flight hours");
  await expect(result).toContainText("99% at 60 flight hours; 99.99% at 25 flight hours, the task's now");

  // Calendar hours, a cost of a check typed and nothing else: the P-F answer still comes.
  await choose(unit, "hours");
  await calc.getByRole("spinbutton", { name: /Cost of a check/ }).fill("28.5");
  await calc.getByRole("button", { name: "Work it out", exact: true }).click();
  await expect(calc.getByRole("status")).toContainText("Check every 60 hours");
  await expect(calc.getByRole("alert")).toHaveCount(0);
});
