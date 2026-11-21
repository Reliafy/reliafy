// FRACAS is reliability work, so it runs whole with work management on or off
// (SMOKE_WORK_MANAGEMENT=off): a failure report raised, analysed (mode and root
// cause), given a corrective action that changes the task preventing that mode
// (the maintenance plan), the action marked done, verified and the report closed.
// With it off, only the action's work-order link is gone: raising one is refused
// and the page offers no work order. The plan's task shows its new interval.
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";

async function send(request, method, path, data) {
  const res = await request.fetch(path, { method, data });
  expect(res.ok(), `${method} ${path}: ${res.status()} ${await res.text()}`).toBeTruthy();
  return res.json();
}

test("FRACAS: report, analyse, change the plan, verify and close", async ({ page, request, problems }) => {
  const off = (await (await request.get("/api/config")).json()).work_management === false;
  const tag = `f${Date.now()}`;
  const pump = await postOk(request, `${M}/positions`, { name: `FRACAS pump ${tag}` });
  await postOk(request, `${M}/positions/${pump.id}/fit`, { new_item: { name: `FRACAS unit ${tag}`, serial: `FU-${tag}` } });
  const mode = await postOk(request, `${M}/positions/${pump.id}/failure-modes`, { text: "Bearing seized" });
  const task = await postOk(request, `${M}/positions/${pump.id}/tasks`, {
    name: "Grease bearings", interval: 6, unit: "months", failure_mode_id: mode.id });

  // Raised and analysed.
  const report = await postOk(request, `${M}/failure-reports`, {
    position_id: pump.id, title: `Seized bearing ${tag}`, consequence: "operational", failure_mode_id: mode.id });
  await send(request, "PUT", `${M}/failure-reports/${report.id}/investigation`, {
    notes: "Dry bearing", root_cause_category: "maintenance", root_cause: "Greased too seldom" });
  // A corrective action that changes the maintenance plan: the task's interval.
  const withAction = await postOk(request, `${M}/failure-reports/${report.id}/actions`, {
    what: "Grease every 3 months", owner: "Reliability engineer" });
  const action = withAction.actions[0];
  if (off) {
    const res = await request.post(`${M}/failure-reports/${report.id}/actions/${action.id}/work-order`, { data: {} });
    expect(res.status()).toBe(409);
    expect((await res.json()).detail).toMatch(/^Work management is turned off/);
  }
  const changed = await send(request, "PATCH", `${M}/tasks/${task.id}`, { interval: 3 });
  expect(changed.interval).toBe(3);
  await send(request, "PATCH", `${M}/failure-reports/${report.id}/actions/${action.id}`, { status: "done" });
  await send(request, "PUT", `${M}/failure-reports/${report.id}/verification`, { result: "worked", notes: "No repeat" });
  const closed = await postOk(request, `${M}/failure-reports/${report.id}/status`, { status: "closed", note: "Signed off" });
  expect(closed.status).toBe("closed");

  // The report on its page: closed, its action done, and no work order offered with it off.
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pump.id}&tab=reports&report=${report.id}`);
  const detail = page.locator(".fr-detail");
  await expect(detail.locator(".fr-h2 .td-pill")).toHaveText("Closed");
  await detail.getByRole("button", { name: "Corrective actions" }).click();
  await expect(detail).toContainText("Grease every 3 months");
  if (off) await expect(detail).not.toContainText(/work order/i);
  await expectHealthy(page, problems, { label: "FRACAS report" });
});
