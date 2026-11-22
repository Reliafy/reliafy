// Optimise… on a maintenance task (the Explorer's Maintenance tab: a task row's ⋯, or its panel's
// How often): how often to do it, from the life model of the failure mode it prevents, in the table
// area beside the tree. The spark plug: a Weibull model on its position, $49 a planned change, $900 a
// failure → replace every 96 h; Use every 96 h sets the
// task's interval and its RCM evidence reads supported; the task then says which model it rests on,
// and the model's row which task it sets. At 400 px nothing scrolls the page sideways. Each run makes
// its own small mower through the API.
//
// With SMOKE_SHOTS_DIR set, it saves screenshots (for the pull request).
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const nameRow = (page, text) => page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: text }) });
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

async function mower(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const engine = await post(`${M}/positions`, { name: `Mower engine ${tag}` });
  const fn = await post(`${M}/positions/${engine.id}/functions`, { text: `Provide power ${tag}` });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `Misfires ${tag}` });
  const mode = await post(`${M}/positions/${engine.id}/failure-modes`, { text: `Spark plug worn ${tag}`, functional_failure_id: ff.id });
  const res = await request.put(`${M}/failure-modes/${mode.id}/decision`, {
    data: { consequence: "operational", hidden: false, decision: { outcome: "fixed_interval", task: `Replace spark plugs ${tag}`, interval: 100, interval_unit: "hours" } },
  });
  expect(res.ok()).toBeTruthy();
  const task = (await res.json()).decision.task_id;
  expect((await request.patch(`${M}/tasks/${task}`, { data: { cost: 49 } })).ok()).toBeTruthy();
  const model = await post("/api/models/from-params", {
    name: `Spark plug life ${tag}`, distribution: "weibull", unit: "hours",
    params: [{ name: "alpha", value: 345.8092446733276 }, { name: "beta", value: 2.5808620343628226 }],
  });
  await post(`${M}/positions/${engine.id}/models`, { model_id: model.id, failure_mode_ids: [mode.id] });
  return { engine, mode, task, model };
}

test("Optimise the plug's replacement → Use every 96 h → the evidence reads supported", async ({ page, request, problems }) => {
  const tag = `o${Date.now()}`;
  const p = await mower(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.engine.id}&sel=${p.engine.id}&tab=maintenance`);
  const row = nameRow(page, `Replace spark plugs ${tag}`);
  await expect(row).toBeVisible();
  // The task row's ⋯: Optimise… opens in the table area, the tree kept beside it.
  await row.locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menuitem", { name: "Optimise…" }).click();
  const pane = page.getByRole("region", { name: "Optimise" });
  await expect(pane).toBeVisible();
  await expect(new URL(page.url()).searchParams.get("optimise")).toBe(p.task);
  await expect(pane).toContainText(`Spark plug life ${tag}`);
  // No failure cost yet: it asks for one; typed, it works the answer out.
  await expect(pane).toContainText("what a failure costs");
  await pane.getByRole("spinbutton", { name: /A failure/ }).fill("900");
  await pane.getByRole("button", { name: "Work it out again" }).click();
  await expect(pane).toContainText("Replace every 96 hours");
  await shot(page, "optimise-desktop");
  await pane.getByRole("button", { name: "Use every 96 h" }).click();
  await expect(pane.getByRole("status").filter({ hasText: "The evidence reads supported" })).toBeVisible();

  // The RCM's evidence for the mode reads supported, on the saved analysis.
  const sheet = await (await request.get(`${M}/positions/${p.engine.id}/rcm?scope=this`)).json();
  const md = sheet.positions.flatMap((x) => x.functions).flatMap((f) => f.failures).flatMap((f) => f.modes).find((x) => x.id === p.mode.id);
  expect(md.decision.status).toBe("supported");
  expect(md.decision.interval).toBe(96);

  // Both places: the task says which model it rests on; the model's row which task it sets.
  await pane.getByRole("button", { name: "Close Optimise" }).click();
  await expect(row).toContainText("96 hours");
  await row.locator(".tp-nm").click();
  await expect(page.locator(".mt-rests")).toContainText(`rests on Spark plug life ${tag}`);
  const links = await (await request.get(`${M}/position-models?position_ids=${p.engine.id}`)).json();
  expect(links.links.find((x) => x.model_id === p.model.id).used_by.tasks[0].task_id).toBe(p.task);

  // At 400 px: the pane takes the screen; nothing scrolls sideways.
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.engine.id}&sel=${p.engine.id}&tab=maintenance&optimise=${p.task}&on=${p.engine.id}`);
  await expect(page.getByRole("region", { name: "Optimise" })).toContainText("Replace every 96 hours");
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "optimise-phone");
  await expectHealthy(page, problems);
});
