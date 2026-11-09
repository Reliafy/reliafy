// Every input a library record needs is a covariate of the record (Derryn, 9 Nov 2026), set in the
// one input component wherever the record is used: an NRC/INL component's page (a motor-driven pump on
// standby, its failure modes together, its chance of failing over a period); a record attached at a
// position with some covariates fixed there and the rest set in the RBD; and the Fit dialog's record
// prior, a pipe's rate for the pipe's length. Nothing scrolls the page sideways at 400 px.
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { headMenu } from "./explorer.js";

const M = "/api/maintenance";
const PUMP = "Motor-driven pump (normally standby)";
const PIPE = "Pipe: external leak, small (service water)";
const RUN = "Motor-driven pump: fails to run, after the first hour";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name, full = false) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: full });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
// After a resize the phone layout settles over a frame or two: ask until it has.
const noSideways = (page) => expect.poll(() => sideways(page), { timeout: 5_000 }).toBeLessThanOrEqual(0);
const re = (text) => new RegExp(text.replace(/[()]/g, "\\$&"));

async function headPick(page, group, item) {
  await headMenu(page);
  await page.getByRole("menuitem", { name: group, exact: true }).click();
  await page.getByRole("menu", { name: group }).getByRole("menuitem", { name: item }).click();
}

async function pickRecord(page, words, label) {
  const picker = page.getByRole("dialog", { name: "Pick a library record" });
  await expect(picker).toBeVisible();
  // The published source (a library of the user's own, made by another test, would come first).
  await picker.getByRole("combobox", { name: "Library", exact: true }).selectOption("nrc-inl-2020");
  await picker.getByRole("combobox", { name: "Search the data library" }).fill(words);
  await picker.getByRole("listbox").getByRole("option", { name: re(label) }).first().click();
  await expect(picker).toHaveCount(0);
}

test("a component: a standby pump's failure modes together, and its chance of failing over a period", async ({ page, problems }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, "/models/library/nrc-inl-2020");
  await page.getByRole("button", { name: "By component" }).click();
  await page.getByRole("searchbox", { name: "Search the components" }).fill("motor-driven pump");
  await page.getByRole("link", { name: PUMP, exact: true }).click();
  await expect(page).toHaveURL(/\/models\/library\/nrc-inl-2020\/components\/motor-driven-pump-normally-standby$/);
  await expect(page.getByRole("heading", { name: PUMP })).toBeVisible();
  await expect(page.getByRole("heading", { name: "How its modes combine" })).toBeVisible();
  const modes = page.locator(".lib-table tbody tr");
  await expect(modes).toHaveCount(5);
  await expect(modes.first()).toContainText("Fails to start");
  // Try it: 12 starts and 24 running hours over a year (the defaults filled in).
  const out = page.locator(".cov-out");
  await expect(out).toContainText("chance it fails over the period");
  await expect(out).toContainText("The plain sum of the modes");
  await page.getByLabel("Demands in the period").fill("1");
  await page.getByLabel("Running hours in the period").fill("24");
  await page.getByLabel("Calendar hours in the period").fill("24");
  await expect(out).toContainText("× 1 demand");
  await expect(out).not.toContainText("updating");
  await shot(page, "component-standby-pump-1440", true);
  await page.setViewportSize({ width: 400, height: 860 });
  await page.reload();
  await expect(page.locator(".cov-out")).toContainText("chance it fails over the period");
  await noSideways(page);
  await shot(page, "component-standby-pump-400", true);
  await page.setViewportSize({ width: 1440, height: 900 });
  // A mode's record lists the component it's part of.
  await page.getByRole("link", { name: "Fails to start" }).first().click();
  await expect(page.getByRole("heading", { name: /^Part of/ })).toBeVisible();
  await expect(page.getByRole("link", { name: PUMP })).toBeVisible();
  await expectHealthy(page, problems, { label: "a library component" });
});

test("records at positions: some covariates fixed there, the rest set in the RBD", async ({ page, request, problems }) => {
  const tag = `rc${Date.now()}`;
  const loop = await postOk(request, `${M}/positions`, { name: `Cooling loop ${tag}` });
  const pipe = await postOk(request, `${M}/positions`, { name: `Header pipe ${tag}`, parent_id: loop.id });
  const pump = await postOk(request, `${M}/positions`, { name: `Spare pump ${tag}`, parent_id: loop.id });
  await page.setViewportSize({ width: 1440, height: 900 });

  // The pipe: its length is design, ticked to fix here; the clock is left to the RBD.
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pipe.id}&tab=models`);
  await headPick(page, "Life model", "From the data library…");
  await pickRecord(page, "pipe external leak small service water", PIPE);
  const pane = page.getByRole("region", { name: "Fix covariates" });
  await expect(pane).toBeVisible();
  await expect(page).toHaveURL(/[?&]bind=library/);
  await expect(pane.getByRole("checkbox", { name: "Fix Pipe length at this position" })).toBeChecked();
  await expect(pane.getByRole("checkbox", { name: "Fix Clock at this position" })).not.toBeChecked();
  await expect(pane.getByLabel("Running hours a year", { exact: true })).toHaveCount(0); // only when the clock changes
  await expect(pane.getByRole("button", { name: "Save at this position" })).toBeDisabled();
  await pane.getByLabel("Pipe length (L)", { exact: true }).fill("300");
  await expect(pane.getByRole("status")).toContainText("1 of 2 fixed here");
  await shot(page, "fix-covariates-nrc-1440");
  await page.setViewportSize({ width: 400, height: 860 });
  await noSideways(page);
  await shot(page, "fix-covariates-nrc-400");
  await page.setViewportSize({ width: 1440, height: 900 });
  await pane.getByRole("button", { name: "Save at this position" }).click();
  await expect(pane).toHaveCount(0);
  await expect(page.locator(".tp-row", { hasText: "1 of 2 covariates fixed here" }).first()).toBeVisible();

  // The pump's fails-to-run rate in calendar time: the clock fixed here, its running hours left to the RBD.
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pump.id}&tab=models`);
  await headPick(page, "Life model", "From the data library…");
  await pickRecord(page, "motor-driven pump fails to run after", RUN);
  await expect(pane).toBeVisible();
  await pane.getByRole("checkbox", { name: "Fix Clock at this position" }).check();
  await pane.getByLabel("Clock", { exact: true }).selectOption("calendar");
  await expect(pane.getByLabel("Running hours a year", { exact: true })).toBeVisible();
  await expect(pane.getByRole("checkbox", { name: "Fix Running hours a year at this position" })).not.toBeChecked();
  await pane.getByRole("button", { name: "Save at this position" }).click();
  await expect(pane).toHaveCount(0);

  // The RBD built from the tree: the pump's block needs its running hours; the diagram's Use value fills it.
  const built = await postOk(request, `${M}/positions/${loop.id}/models`, { build_rbd: true });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${loop.id}&tab=models&rbd=${built.model_id}&on=${loop.id}`);
  const rbd = page.getByRole("region", { name: "RBD", exact: true });
  await expect(rbd).toBeVisible();
  await rbd.getByRole("tab", { name: "Calculator" }).click();
  const bar = rbd.locator(".rbd-bound-bar");
  await expect(bar).toContainText(`Spare pump ${tag} needs Running hours a year (Use, hours a year)`);
  await expect(bar).not.toContainText(`Header pipe ${tag} needs`);
  await bar.getByRole("button", { name: "Covariates…" }).click();
  const dlg = page.getByRole("dialog", { name: "Covariates for the blocks" });
  await dlg.getByRole("button", { name: "+ Add a value" }).click();
  await dlg.getByLabel("Name of value 1").fill("Running hours a year");
  await dlg.getByLabel("What value 1 is").selectOption("use");
  await dlg.getByLabel("Unit of value 1").fill("hours a year");
  await dlg.getByLabel("Value 1", { exact: true }).fill("876");
  await expect(dlg).toContainText("Using 876 from the diagram's Use: Running hours a year");
  await dlg.getByRole("button", { name: "Apply" }).click();
  await expect(bar).toContainText("every one has a value");
  await rbd.locator('[data-wt="rbd-calculate"]').click();
  await expect(rbd.locator(".rbd-calc-panel").first().getByText(/MTTF/).first()).toBeVisible({ timeout: 30_000 });
  await expectHealthy(page, problems, { label: "library records at positions and in the RBD" });
});

test("the Fit dialog's record prior takes the pipe's length", async ({ page, request, problems }) => {
  const tag = `rp${Date.now()}`;
  const ago = (d) => new Date(Date.now() - d * 864e5).toISOString().slice(0, 10);
  const pipe = await postOk(request, `${M}/positions`, { name: `Service water pipe ${tag}` });
  await postOk(request, `${M}/positions/${pipe.id}/fit`, { new_item: { name: `P1 ${tag}` }, on: ago(900) });
  await postOk(request, `${M}/positions/${pipe.id}/remove`, { on: ago(400), reason: "failure" });
  await postOk(request, `${M}/positions/${pipe.id}/fit`, { new_item: { name: `P2 ${tag}` }, on: ago(400) });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pipe.id}&tab=models`);
  await headPick(page, "Life model", "Fit a life model…");
  const fit = page.getByRole("region", { name: "Fit a life model" });
  await fit.getByRole("radio", { name: "With a prior" }).click();
  await fit.getByRole("combobox", { name: "Prior", exact: true }).selectOption("library");
  await pickRecord(page, "pipe external leak small service water", PIPE);
  await expect(fit.getByRole("group", { name: "The library record" })).toContainText(PIPE);
  // Its covariates under it: the pipe's length is needed before the prior is anything (never one foot).
  const cov = fit.getByRole("group", { name: "Its covariates" });
  await expect(cov).toBeVisible();
  await expect(fit).toContainText("Give the record's Pipe length.");
  await cov.getByLabel("Pipe length (L)").fill("20000");
  await expect(cov.locator(".cov-out")).toContainText("failures per calendar hour");
  await fit.getByRole("combobox", { name: "Distribution" }).selectOption("exponential");
  await expect(fit.locator("p.ml-lead[role=status]")).toContainText("Pipe length 20000 ft", { timeout: 30_000 });
  await shot(page, "fit-pipe-prior-1440");
  await expectHealthy(page, problems, { label: "a record prior with its covariates" });
  // At 400 px the pane fits (the fit's chart, unchanged here, logs a Plotly legend warning when it's
  // squeezed: the page's health is checked above, before the resize).
  await page.setViewportSize({ width: 400, height: 860 });
  await noSideways(page);
  await fit.getByRole("group", { name: "Its covariates" }).scrollIntoViewIfNeeded();
  await shot(page, "fit-pipe-prior-400");
});
