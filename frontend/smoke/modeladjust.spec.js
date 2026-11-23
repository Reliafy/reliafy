// Adjust for conditions… (backend/services/model_adjust.py): a life model with a known hazard ratio,
// saved as a new model, the original unchanged. On the model page it opens in the page's body; in the
// Explorer, on a model row, in the table pane beside the tree. Never a modal. The hand check: a Weibull
// with alpha 1,000 h and beta 2 has a B10 of 325 h; at 1.5 times the hazard, 265 h.
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { subItem } from "./explorer.js";

// An item of a row's menu: at its top level, or under More › (the menu standard keeps ten a level).
async function menuPick(page, name) {
  const menu = page.getByRole("menu").last();
  await expect(menu).toBeVisible();
  const direct = menu.locator(":scope > [role='menuitem']").filter({ hasText: name });
  if (await direct.count()) return menu.getByRole("menuitem", { name }).first();
  return subItem(page, menu, "More", name, { exact: false });
}


const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` }); };
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

for (const width of [1440, 400]) {
  test(`a model adjusted for conditions from its page (${width} px)`, async ({ page, request, problems }) => {
    const name = `Pump ${Date.now()}`;
    const made = await postOk(request, "/api/models/from-params", {
      name, distribution: "weibull", unit: "hours", params: [{ name: "alpha", value: 1000 }, { name: "beta", value: 2 }],
    });
    await page.setViewportSize({ width, height: 900 });
    await open(page, `/models/m/${made.id}`);
    await page.getByRole("button", { name: "More actions" }).first().click();
    await page.getByRole("menuitem", { name: "Adjust for conditions…" }).or(page.locator(".ovm-item", { hasText: "Adjust for conditions…" })).first().click();
    await expect(page).toHaveURL(/adjust=1/);
    await expect(page.locator(".modal, [role=dialog]")).toHaveCount(0);
    const panel = page.locator(".adj");
    await expect(panel.getByLabel("Hazard ratio")).toHaveValue("1.5");
    const table = panel.locator(".adj-table");
    await expect(table).toContainText("325 hours");
    await expect(table).toContainText("265 hours");
    await expect(panel).toContainText("No confidence bounds"); // from parameters: nothing to base them on
    await expect(panel).toContainText("the shape stays the same");
    // By how long it lasts: a Weibull's life scale is exact.
    await panel.getByRole("radio", { name: "By how long it lasts" }).click();
    await expect(panel).toContainText(/hazard ratio of 2\.2/);
    await panel.getByRole("radio", { name: "By hazard ratio" }).click();
    await expect(table).toContainText("265 hours");
    await shot(page, `adjust-model-page-${width}`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await panel.getByRole("button", { name: "Save the adjusted model" }).click();
    await expect(page).not.toHaveURL(new RegExp(made.id));
    await expect(page.locator(".mf-notice.adj-from").first()).toContainText(`${name} is unchanged`);
    await expect(page.getByRole("link", { name })).toBeVisible();
    await expect(page.locator("h1")).toContainText(`${name} (×1.5 hazard)`);
    await expectHealthy(page, problems, { label: "Adjusted model page" });
  });

  test(`a position's model adjusted in the Explorer's table pane (${width} px)`, async ({ page, request, problems }) => {
    const tag = `a${Date.now()}`;
    const pump = await postOk(request, `${M}/positions`, { name: `Hot pump ${tag}` });
    const model = await postOk(request, "/api/models/from-params", {
      name: `Pump model ${tag}`, distribution: "weibull", unit: "hours",
      params: [{ name: "alpha", value: 1000 }, { name: "beta", value: 2 }],
    });
    await postOk(request, `${M}/positions/${pump.id}/models`, { model_type: "model", model_id: model.id });
    await page.setViewportSize({ width, height: 900 });
    await open(page, `/asset-register/explorer?arrange=positions&root=${pump.id}&sel=${pump.id}&tab=models`);
    const row = page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: `Pump model ${tag}` }) });
    await expect(row).toBeVisible();
    await row.locator(".tp-nm").click({ button: "right" });
    await (await menuPick(page, "Adjust for conditions…")).click();
    const pane = page.locator(".table-pane", { hasText: "Adjust for conditions" });
    await expect(pane).toBeVisible();
    await expect(page).toHaveURL(/adjust=/);
    await pane.getByLabel("Hazard ratio").fill("2");
    await expect(pane.locator(".adj-table")).toContainText("230 hours"); // 1000 * sqrt(-ln 0.9 / 2) = 229.5
    await expect(pane.getByRole("radio", { name: `Use it here in place of Pump model ${tag}` })).toBeChecked();
    await shot(page, `adjust-explorer-pane-${width}`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await pane.getByRole("button", { name: "Save and use it here" }).click();
    await expect(pane).toHaveCount(0);
    await expect(page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: `Pump model ${tag} (×2 hazard)` }) })).toBeVisible();
    const links = await (await request.get(`${M}/position-models?position_ids=${pump.id}`)).json();
    const names = links.links.map((l) => l.name);
    expect(names).toEqual([`Pump model ${tag} (×2 hazard)`]);
    await expectHealthy(page, problems, { label: "Explorer adjust pane" });
  });
}
