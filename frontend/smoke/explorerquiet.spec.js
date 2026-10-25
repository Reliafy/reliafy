// The Explorer's RCM tab with no evidence linked (most RCM is done from
// judgement): calm. No orange "inconclusive" badge on the position, no "to
// check" on parents, no "No evidence" pill on each mode, and the Evidence
// check column hidden until some failure mode has evidence linked (it stays in
// the Columns menu, and ticking it on is remembered). The mode's panel still
// offers a gentle "Link evidence…". The Not analysed chip says what analysed
// means.
//
// The smoke server's workspace is shared by every spec (another one links
// evidence), so the workspace's RCM is read here as if nothing were linked.
// With SMOKE_SHOTS_DIR set, it also saves screenshots there (for the pull request).
import { test, expect, open, expectHealthy } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};

async function plant(request, tag) {
  const post = async (path, data) => {
    const res = await request.post(path, { data });
    expect(res.ok(), `${path}: ${res.status()} ${await res.text()}`).toBeTruthy();
    return res.json();
  };
  const top = await post(`${M}/positions`, { name: `Quiet pool ${tag}` });
  const pump = await post(`${M}/positions`, { name: `Quiet pump ${tag}`, parent_id: top.id });
  const fn = await post(`${M}/positions/${pump.id}/functions`, { text: `Circulate water ${tag}` });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `No flow ${tag}` });
  const decided = await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Bearing worn ${tag}`, functional_failure_id: ff.id });
  const res = await request.put(`${M}/failure-modes/${decided.id}/decision`, {
    data: { consequence: "operational", decision: { outcome: "fixed_interval", task: "Replace the bearings", interval: 2, interval_unit: "years" } },
  });
  expect(res.ok()).toBeTruthy();
  return { top, pump, fn, ff, decided };
}

// The workspace's RCM as if no decision had evidence linked.
async function nothingLinked(page) {
  await page.route(`**${M}/rcm`, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    const strip = (m) => {
      if (!m.decision) return;
      delete m.decision.evidence;
      for (const k of ["artifact_name", "artifact_link_path", "summary"]) delete m.decision[k];
      if (m.decision.status) m.decision.status = "unevidenced";
    };
    for (const p of body.positions || []) {
      for (const m of p.unassigned || []) strip(m);
      for (const fn of p.functions || []) for (const ff of fn.failures || []) for (const m of ff.modes || []) strip(m);
      if (p.rollup) p.rollup = { ...p.rollup, unevidenced: (p.rollup.unevidenced || 0) + (p.rollup.supported || 0) + (p.rollup.contradicted || 0) + (p.rollup.inconclusive || 0) + (p.rollup.stale || 0), supported: 0, contradicted: 0, inconclusive: 0, stale: 0 };
    }
    await route.fulfill({ response: res, json: body });
  });
}

const table = (page) => page.getByRole("treegrid", { name: /and their RCM/ });
const trow = (page, name) => table(page).getByRole("row", { name: new RegExp(name) });

test("no evidence linked: no warnings, no Evidence check column; the column comes back from Columns; Link evidence stays", async ({ page, request, problems }) => {
  const tag = `q${Date.now()}`;
  const p = await plant(request, tag);
  await nothingLinked(page);
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.addInitScript(() => {
    // Once (a reload keeps what was chosen): the usual columns.
    try {
      if (!sessionStorage.getItem("quiet-cleared")) {
        localStorage.removeItem("reliafy.rcmWorksheet");
        sessionStorage.setItem("quiet-cleared", "1");
      }
    } catch { /* fine */ }
  });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  await expect(table(page)).toBeVisible();
  const modeRow = trow(page, `Failure mode: Bearing worn ${tag}`);
  await expect(modeRow).toBeVisible();
  // Calm: no Evidence check column, no warning chips anywhere in the table or the heading.
  await expect(table(page).getByRole("columnheader", { name: "Evidence check" })).toHaveCount(0);
  await expect(table(page).getByRole("columnheader", { name: "Decision" })).toBeVisible();
  await expect(table(page).getByText("No evidence", { exact: true })).toHaveCount(0);
  await expect(table(page)).not.toContainText(/inconclusive|to check/i);
  await expect(page.locator(".tt-headslot .tt-rollup .chip")).toHaveCount(0);
  await expect(page.locator(".tt-headslot")).not.toContainText("inconclusive");
  await shot(page, "quiet-1-rcm-no-evidence-1280");

  // The Columns menu still has it: ticked on, it shows (each mode: a quiet dash), and stays on after a reload.
  await page.getByRole("button", { name: "Columns" }).click();
  const pop = page.getByRole("group", { name: "Columns to show" });
  await expect(pop.getByRole("checkbox", { name: "Evidence check" })).not.toBeChecked();
  await pop.getByRole("checkbox", { name: "Evidence check" }).check();
  await page.keyboard.press("Escape");
  await expect(table(page).getByRole("columnheader", { name: "Evidence check" })).toBeVisible();
  await expect(modeRow.getByTitle("No evidence linked yet")).toBeVisible();
  await expect(modeRow.getByText("No evidence", { exact: true })).toHaveCount(0);
  await page.waitForTimeout(400); // remembered a moment after the change
  await page.reload();
  await expect(table(page).getByRole("columnheader", { name: "Evidence check" })).toBeVisible();
  // Show the usual columns: back to following the evidence (none here: hidden).
  await page.getByRole("button", { name: "Columns" }).click();
  await page.getByRole("button", { name: "Show the usual columns" }).click();
  await page.keyboard.press("Escape");
  await expect(table(page).getByRole("columnheader", { name: "Evidence check" })).toHaveCount(0);

  // The mode's panel: no alarm, a gentle Link evidence… that opens the Decide dialog.
  await modeRow.locator(".tt-tree").click();
  await modeRow.press("Enter");
  const panel = page.locator("aside.rw-panel");
  await expect(panel).toBeVisible();
  await expect(panel).toContainText("No evidence linked yet");
  await expect(panel.locator(".chip")).toHaveCount(0);
  await panel.getByRole("button", { name: "Link evidence…" }).scrollIntoViewIfNeeded();
  await shot(page, "quiet-2-mode-panel-link-evidence");
  await panel.getByRole("button", { name: "Link evidence…" }).click();
  const dialog = page.getByRole("dialog").filter({ hasText: "Link the evidence" });
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);

  // The Not analysed chip says what analysed means, in words.
  await page.getByRole("button", { name: /^Tree options/ }).click();
  const chip = page.getByRole("menu", { name: "Tree options" }).getByRole("menuitemcheckbox", { name: "Not analysed" });
  await expect(chip).toHaveAttribute("title", /analysed when it has at least one function, every function has a functional failure, every functional failure has failure modes or is caused by failures on positions inside it that are answered in turn, and every failure mode has a decision/);
  await page.keyboard.press("Escape");
  // The pump is analysed (one function › one failure › one decided mode); the pool, with no function of its own, isn't.
  await expect(trow(page, `^Quiet pump ${tag}`).locator(".tp-mini.rcm")).toHaveCount(0);
  await expect(trow(page, `^Quiet pool ${tag}`).locator(".tp-mini.rcm")).toHaveAttribute("title", "1 position not analysed yet here and inside");
  // One rule everywhere: a functional failure with no failure mode leaves the pump not analysed.
  await request.post(`${M}/functions/${p.fn.id}/failures`, { data: { text: `Leaks ${tag}` } });
  await page.reload();
  await expect(trow(page, `^Quiet pump ${tag}`).locator(".tp-mini.rcm")).toHaveAttribute("title", "Not analysed yet (RCM)");
  await expect(trow(page, `^Quiet pool ${tag}`).locator(".tp-mini.rcm")).toHaveAttribute("title", "2 positions not analysed yet here and inside");
  await expectHealthy(page, problems, { label: "explorer quiet evidence" });
});
