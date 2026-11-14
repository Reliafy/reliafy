// The asset tree in a spreadsheet from the Explorer: the tree's ⋯ menu opens Excel import and
// export beside the tree (no dialog); a CSV is checked (what it will make, problems by row),
// imported (all or nothing), and importing it again makes nothing. A position's row menu exports
// its branch. A phone: the pane takes the screen, and nothing scrolls sideways at 400 px.
import { test, expect, open, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const csv = (tag, text) => ({ name: `plant-${tag}.csv`, mimeType: "text/csv", buffer: Buffer.from(text) });

async function treeMenu(page, item) {
  await page.getByRole("button", { name: /^Tree options/ }).click();
  await page.getByRole("menu", { name: "Tree options" }).getByRole("menuitem", { name: item }).click();
}

const pane = (page) => page.getByRole("region", { name: "Excel import and export" });

for (const [width, height, label] of [[1440, 900, "1440"], [400, 860, "400"]]) {
  test(`import a hierarchy from a sheet, then again: nothing new (${label} px)`, async ({ page, problems }) => {
    await page.setViewportSize({ width, height });
    const tag = `s${Date.now()}${label}`;
    const top = `Mine ${tag}`;
    const good = csv(tag, [
      "Path,Tag,Position class,Location,Fitted item,Item serial,Installed on,Item class",
      `${top},,,,,,,`,
      `${top} > Primary crusher,CR-101,Jaw crusher,Site ${tag} > Crusher pad,Jaw crusher JC-9,JC9-0042,2021-03-15,Fixed ${tag} > Crusher`,
      `${top} > Conveyor CV-1,CV-1,Conveyor,Site ${tag},,,,`,
      `${top} > Conveyor CV-1 > Drive pulley,CV-1-DP,Pulley,,,,,`,
      `${top} > Conveyor CV-1 > Tail pulley,CV-1-TP,Pulley,,,,,`,
    ].join("\n") + "\n");
    await open(page, "/asset-register/explorer?arrange=positions");
    await treeMenu(page, "Import from Excel…");
    await expect(pane(page)).toBeVisible();
    await expect(page.getByRole("heading", { name: /Excel import and export/ })).toBeVisible();
    await pane(page).locator("input[type=file]").setInputFiles(good);
    await expect(pane(page).locator(".ts-summary")).toHaveText(
      "Will create 5 positions, 2 locations, 2 classes and 1 item.");
    await expect(pane(page).getByText("5 new positions")).toBeVisible();
    await shot(page, `${label}-import-preview`);
    const noSideways = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
    expect(noSideways).toBe(true);
    await pane(page).getByRole("button", { name: "Import", exact: true }).click();
    await expect(pane(page).locator(".ts-done")).toContainText("Created 5 positions, 2 locations, 2 classes and 1 item.");
    // Again: matched by path, nothing new.
    await pane(page).locator("input[type=file]").setInputFiles(good);
    await expect(pane(page).locator(".ts-summary")).toHaveText(
      "Nothing to change: everything in the file is already in Reliafy.");
    await expect(pane(page).getByRole("button", { name: "Import", exact: true })).toBeDisabled();

    // Problems, by row: nothing is written.
    const bad = csv(`${tag}-bad`, [
      "Path,Installed on,Fitted item",
      `Nowhere ${tag} > Pump,,`,
      `${top} > Spare,2150-01-01,Pump`,
      `${top} > Twin,,`,
      `${top} > Twin,,`,
    ].join("\n") + "\n");
    await pane(page).locator("input[type=file]").setInputFiles(bad);
    await expect(pane(page).getByText("3 problems to fix in the file")).toBeVisible();
    await expect(pane(page).locator(".ts-table")).toContainText("Row 2");
    await expect(pane(page).locator(".ts-table")).toContainText(`Nowhere ${tag} isn't in the file or in Reliafy`);
    await expect(pane(page).getByRole("button", { name: "Import", exact: true })).toBeDisabled();
    await pane(page).locator(".ts-table").scrollIntoViewIfNeeded();
    await shot(page, `${label}-import-problems`);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    expect(problems).toEqual([]);
  });
}

test("export the whole tree or a branch from its row menu", async ({ page, request, problems }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const tag = `e${Date.now()}`;
  const plant = await postOk(request, `${M}/positions`, { name: `Plant ${tag}` });
  await postOk(request, `${M}/positions`, { name: "Feed pump A", parent_id: plant.id, tag: "P-101" });
  const csvText = await (await request.get(`${M}/hierarchy/export?format=csv&position_id=${plant.id}`)).text();
  expect(csvText).toContain(`Plant ${tag} > Feed pump A`);
  const book = await request.get(`${M}/hierarchy/export`);
  expect(book.headers()["content-type"]).toContain("spreadsheetml");

  await open(page, `/asset-register/explorer?all=1&arrange=positions&sel=${plant.id}`);
  await treeMenu(page, "Export to Excel…");
  await expect(pane(page)).toBeVisible();
  await expect(pane(page).getByRole("button", { name: "Download Excel" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(pane(page)).toHaveCount(0);

  await page.getByRole("treeitem", { name: new RegExp(`^Plant ${tag}`) }).locator(".tp-nm").click({ button: "right" });
  const menu = page.getByRole("menu", { name: new RegExp(`^Actions for Plant ${tag}`) });
  await expect(menu.getByRole("menuitem", { name: "Export this branch…" })).toBeVisible();
  await shot(page, "1440-export-row-menu");
  await menu.getByRole("menuitem", { name: "Export this branch…" }).click();
  await expect(pane(page).getByRole("radio", { name: `This branch: Plant ${tag}` })).toBeChecked();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    pane(page).getByRole("button", { name: "Download Excel" }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(new RegExp(`^Plant ${tag} \\d{4}-\\d{2}-\\d{2}\\.xlsx$`));
  await shot(page, "1440-export-pane");
  expect(problems).toEqual([]);
});
