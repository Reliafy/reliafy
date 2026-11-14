// Merge into another asset… (Derryn, 14 Nov 2026: the Explorer is always one asset; "Alternately, they
// can merge one asset into another"). From the Assets list's row menu: the Explorer opens on that asset
// with the merge pane beside its tree (not a dialog); pick the asset it joins, where in it, read the
// preview, Merge: the other asset opens with the merged part picked, and the Assets list no longer has
// it. Make this its own asset… on its row splits it off again. At 1440 and 400 px.
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const row = (page, name) => page.getByRole("treeitem", { name: new RegExp(`^${name}`) });
const pane = (page) => page.getByRole("region", { name: "Merge into another asset" });

async function twoAssets(request, tag) {
  const post = (path, body) => postOk(request, `${M}${path}`, body);
  const site = await post("/locations", { name: `Site A ${tag}` });
  const hall = await post("/locations", { name: `Pump hall ${tag}`, parent_id: site.id });
  await post("/positions", { name: `Main pump ${tag}`, location_id: hall.id });
  const station = await post("/locations", { name: `Pump station 2 ${tag}` });
  const booster = await post("/positions", { name: `Booster ${tag}`, location_id: station.id });
  await post(`/positions/${booster.id}/fit`, { new_item: { name: `Booster unit ${tag}`, serial: `BU-${tag}` } });
  await post(`/positions/${booster.id}/failure-modes`, { text: `Seal leaks ${tag}`, function: `Boost ${tag}`, failure: `No boost ${tag}` });
  return { site, hall, station, booster };
}

test("merge an asset into another from the Assets list, then make it its own asset again", async ({ page, request, problems }) => {
  const tag = `mg${Date.now()}`;
  const a = await twoAssets(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });

  // The Assets list's row menu.
  await open(page, "/asset-register");
  const stationRow = page.getByRole("row").filter({ has: page.getByRole("link", { name: `Pump station 2 ${tag}`, exact: true }) });
  await stationRow.getByRole("button", { name: `Actions for Pump station 2 ${tag}` }).click();
  await page.getByRole("menuitem", { name: "Merge into another asset…" }).click();
  await expect(page).toHaveURL(new RegExp(`root=${a.station.id}.*merge=1`));
  await expect(pane(page)).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(row(page, `Pump station 2 ${tag}`)).toBeVisible(); // the tree beside it

  // 1. The asset it joins (searched); 2. where in it; the preview says what comes along.
  await pane(page).getByRole("searchbox", { name: "Search assets" }).fill(`Site A ${tag}`);
  await pane(page).getByRole("option", { name: new RegExp(`^Site A ${tag}`) }).click();
  await expect(pane(page).getByRole("button", { name: "Merge", exact: true })).toBeDisabled();
  await pane(page).getByRole("option", { name: new RegExp(`^Pump hall ${tag}`) }).click();
  await expect(pane(page).getByRole("status")).toHaveText(
    `Pump station 2 ${tag} and its 1 position and 1 item will become part of Site A ${tag}, at Pump hall ${tag}.`);
  await expect(pane(page).getByRole("button", { name: "Merge", exact: true })).toBeEnabled();
  await expect(pane(page).getByRole("button", { name: "Merge", exact: true })).toHaveCSS("opacity", "1"); // its fade-in done
  await shot(page, "merge-pane-1440");
  expect(await sideways(page)).toBeLessThanOrEqual(1);
  await pane(page).getByRole("button", { name: "Merge", exact: true }).click();

  // Site A opens with the merged station picked; its booster and RCM came along.
  await expect(page).toHaveURL(new RegExp(`root=${a.site.id}`));
  await expect(page).toHaveURL(new RegExp(`sel=${a.station.id}`));
  await expect(row(page, `Pump station 2 ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText(`Merged. Pump station 2 ${tag} is part of Site A ${tag} now.`)).toBeVisible();
  await shot(page, "merge-done-1440");
  await open(page, `/asset-register/explorer?arrange=positions&root=${a.site.id}&tab=rcm&sel=${a.booster.id}`);
  await expect(page.getByText(`Seal leaks ${tag}`).first()).toBeVisible();
  await open(page, "/asset-register");
  await expect(page.getByRole("link", { name: `Site A ${tag}`, exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: `Pump station 2 ${tag}`, exact: true })).toHaveCount(0);

  // Make this its own asset… on its row: it leaves Site A and opens on its own.
  await open(page, `/asset-register/explorer?arrange=locations&root=${a.site.id}&sel=${a.station.id}`);
  await row(page, `Pump station 2 ${tag}`).locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menu", { name: new RegExp(`^Actions for Pump station 2 ${tag}`) })
    .getByRole("menuitem", { name: "Make this its own asset…" }).click();
  const dialog = page.getByRole("alertdialog", { name: `Make Pump station 2 ${tag} its own asset?` });
  await expect(dialog).toContainText(`leave Site A ${tag}`);
  await dialog.getByRole("button", { name: "Make it its own asset" }).click();
  await expect(page).toHaveURL(new RegExp(`root=${a.station.id}`));
  await expect(page.getByText(`Site A ${tag}`)).toHaveCount(0);
  await expect(row(page, `Pump station 2 ${tag}`)).toBeVisible();
  await open(page, "/asset-register");
  await expect(page.getByRole("link", { name: `Pump station 2 ${tag}`, exact: true })).toBeVisible();
  await expectHealthy(page, problems, { label: "merge and split an asset" });
});

test("the merge pane on a phone: its own screen, nothing sideways, Back closes it", async ({ page, request, problems }) => {
  const tag = `mp${Date.now()}`;
  const a = await twoAssets(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  // The asset's top row menu in the Explorer opens it too.
  await open(page, `/asset-register/explorer?arrange=locations&root=${a.station.id}&sel=${a.station.id}`);
  await row(page, `Pump station 2 ${tag}`).getByRole("button", { name: /^Actions for / }).click();
  await page.getByRole("menuitem", { name: "Merge into another asset…" }).click();
  await expect(pane(page)).toBeVisible();
  await pane(page).getByRole("option", { name: new RegExp(`^Site A ${tag}`) }).click();
  await pane(page).getByRole("option", { name: new RegExp(`^Pump hall ${tag}`) }).click();
  await expect(pane(page).getByRole("status")).toContainText("will become part of");
  await expect(pane(page).getByRole("button", { name: "Merge", exact: true })).toHaveCSS("opacity", "1");
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "merge-pane-400");
  await pane(page).getByRole("button", { name: "Back to the table" }).click();
  await expect(pane(page)).toHaveCount(0);
  await expect(page).not.toHaveURL(/merge=1/);
  await expectHealthy(page, problems, { label: "merge pane on a phone" });
});
