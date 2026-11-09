// A covariate model at a position, some covariates fixed there and the rest set in an RBD (Derryn,
// 9 Nov 2026: "the user can choose to fix some, all, or none of the covariates ... If they are use
// or env one can set them in the RBD"): an NSWC-11 bearing picked from the data library opens
// "Fix covariates" in the table area (design ticked, use and environment open); saved, the RBD
// built from the tree says which block needs what; the diagram's Use values fill them; a block's
// own value overrides one, and the result changes. Nothing scrolls sideways at 400 px.
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { headMenu } from "./explorer.js";

const M = "/api/maintenance";
const BEARING = "Bearing, rolling element (from its load rating)";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name, full = false) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: full });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

async function headPick(page, group, item) {
  await headMenu(page);
  await page.getByRole("menuitem", { name: group, exact: true }).click();
  await page.getByRole("menu", { name: group }).getByRole("menuitem", { name: item }).click();
}

test("covariates: fix some at a position from the library, set the rest in the RBD, the result changes", async ({ page, request, problems }) => {
  const tag = `cb${Date.now()}`;
  const box = await postOk(request, `${M}/positions`, { name: `Gearbox ${tag}` });
  const brg = await postOk(request, `${M}/positions`, { name: `Input bearing ${tag}`, parent_id: box.id });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${brg.id}&tab=models`);

  // Life model › From the data library…: an NSWC-11 covariate model opens Fix covariates in the pane.
  await headPick(page, "Life model", "From the data library…");
  const picker = page.getByRole("dialog", { name: "Pick a library record" });
  await picker.getByRole("combobox", { name: "Library", exact: true }).selectOption("nswc-11");
  await picker.getByRole("combobox", { name: "Search the data library" }).fill("bearing load rating");
  await picker.getByRole("listbox").getByRole("option", { name: new RegExp(BEARING.replace(/[()]/g, "\\$&")) }).first().click();
  const pane = page.getByRole("region", { name: "Fix covariates" });
  await expect(pane).toBeVisible();
  await expect(page).toHaveURL(/[?&]bind=nswc/);
  await expect(pane.getByRole("checkbox", { name: "Fix Dynamic load rating (catalogue) at this position" })).toBeChecked();
  await expect(pane.getByRole("checkbox", { name: "Fix Radial load at this position" })).not.toBeChecked();
  await expect(pane.getByRole("button", { name: "Save at this position" })).toBeDisabled();  // L_S ticked, no value
  await pane.getByLabel("Dynamic load rating (catalogue) (L_S)").fill("5000");
  await expect(pane.getByRole("status")).toContainText("fixed here");
  await shot(page, "bind-pane-1440");
  await page.setViewportSize({ width: 400, height: 860 });
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "bind-pane-400");
  await page.setViewportSize({ width: 1440, height: 900 });
  await pane.getByRole("button", { name: "Save at this position" }).click();
  await expect(pane).toHaveCount(0);
  await expect(page.locator(".tp-row", { hasText: "covariates fixed here" }).first()).toBeVisible();

  // The RBD built from the tree: the block takes the covariates its position left open.
  const built = await postOk(request, `${M}/positions/${box.id}/models`, { build_rbd: true });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${box.id}&tab=models&rbd=${built.model_id}&on=${box.id}`);
  const rbd = page.getByRole("region", { name: "RBD", exact: true });
  await expect(rbd).toBeVisible();
  await rbd.getByRole("tab", { name: "Calculator" }).click();
  const bar = rbd.locator(".rbd-bound-bar");
  await expect(bar).toContainText(`Still needed: Input bearing ${tag} needs Radial load (Use, lbf), Operating speed (Use, rpm)`);

  // At 400 px the dialog fits, nothing sideways (before any result is drawn).
  const dlg = page.getByRole("dialog", { name: "Covariates for the blocks" });
  await page.setViewportSize({ width: 400, height: 860 });
  await bar.getByRole("button", { name: "Covariates…" }).click();
  await expect(dlg).toBeVisible();
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "rbd-covariates-400");
  await dlg.getByRole("button", { name: "Cancel" }).click();
  await page.setViewportSize({ width: 1440, height: 900 });

  // The diagram's Use values: every block with those covariates takes them.
  await bar.getByRole("button", { name: "Covariates…" }).click();
  await dlg.getByRole("button", { name: "+ Add a value" }).click();
  await dlg.getByLabel("Name of value 1").fill("Radial load");
  await dlg.getByLabel("What value 1 is").selectOption("use");
  await dlg.getByLabel("Unit of value 1").fill("lbf");
  await dlg.getByLabel("Value 1", { exact: true }).fill("1000");
  await dlg.getByRole("button", { name: "+ Add a value" }).click();
  await dlg.getByLabel("Name of value 2").fill("Operating speed");
  await dlg.getByLabel("What value 2 is").selectOption("use");
  await dlg.getByLabel("Unit of value 2").fill("rpm");
  await dlg.getByLabel("Value 2", { exact: true }).fill("1800");
  await expect(dlg).toContainText("Using 1000 from the diagram's Use: Radial load");
  await shot(page, "rbd-covariates-1440");
  await dlg.getByRole("button", { name: "Apply" }).click();
  await expect(bar).toContainText("every one has a value");
  await rbd.locator('[data-wt="rbd-calculate"]').click();
  const answer = rbd.locator(".rbd-calc-panel").first().getByText(/MTTF/).first();
  await expect(answer).toBeVisible({ timeout: 30_000 });
  const before = await rbd.locator(".rbd-calc-panel").first().innerText();

  // This block runs faster than the diagram's speed: its own value wins, and the result changes.
  await bar.getByRole("button", { name: "Covariates…" }).click();
  await dlg.getByLabel("Operating speed (n)").fill("3600");
  await dlg.getByRole("button", { name: "Apply" }).click();
  await rbd.locator('[data-wt="rbd-calculate"]').click();
  await expect.poll(async () => rbd.locator(".rbd-calc-panel").first().innerText(), { timeout: 30_000 }).not.toBe(before);
  await shot(page, "rbd-covariates-result-1440");
  await expectHealthy(page, problems, { label: "covariates fixed at a position and set in the RBD" });
});
