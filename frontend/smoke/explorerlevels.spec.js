// The panel's tabs at every level of the tree (Derryn, 21 Nov 2026: "the tabs on the explorer
// tree vanish when you click on a position higher in the tree that doesn't have anything ... The
// tabs should be available at all levels of the tree"). A place opened by Positions shows the
// positions above its own (House > Outdoor & grounds, at no place) as rows over them; picking one
// took the tab bar away. Here: on the RCM tab, picking the parent position (no RCM of its own; its
// child's has a failure mode) keeps the tab bar with RCM picked, and so does its parent; the other
// tabs open on it too. At 1440 and 400 px.
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const query = (page) => new URL(page.url()).searchParams;
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

async function placeWithParents(request, tag) {
  const post = (path, body) => postOk(request, `${M}${path}`, body);
  const addr = await post("/locations", { name: `Street ${tag}` });
  const yard = await post("/locations", { name: `Pool area ${tag}`, parent_id: addr.id });
  const house = await post("/positions", { name: `House ${tag}` });
  const outdoor = await post("/positions", { name: `Outdoor ${tag}`, parent_id: house.id });
  const pool = await post("/positions", { name: `Pool ${tag}`, parent_id: outdoor.id, location_id: yard.id });
  await post(`/positions/${pool.id}/failure-modes`, { text: `Pump seizes ${tag}`, function: `Circulate water ${tag}`, failure: `No flow ${tag}` });
  return { addr, yard, house, outdoor, pool };
}

for (const width of [1440, 400]) {
  test(`a parent position with no RCM of its own keeps the tab bar on the RCM tab (${width} px)`, async ({ page, request, problems }) => {
    const tag = `lvl${width}${Date.now()}`;
    const a = await placeWithParents(request, tag);
    await page.setViewportSize({ width, height: 900 });
    await open(page, `/asset-register/explorer?arrange=positions&root=${a.addr.id}&tab=rcm&sel=${a.pool.id}`);
    // The tab bar: over the tree beside the panel on a wide screen, over the tree on a phone.
    const bar = page.getByRole("tablist", { name: width > 600 ? "What to show for this row" : new RegExp("^What to show for ") });
    const rcmTab = bar.getByRole("tab", { name: "RCM", exact: true });
    await expect(rcmTab).toHaveAttribute("aria-selected", "true");
    await expect(page.getByText(`Pump seizes ${tag}`).first()).toBeVisible();

    for (const p of [a.outdoor, a.house]) {
      await page.locator(`.tp-row[data-key="${p.id}"] .tp-nm`).first().click();
      await expect(page).toHaveURL(new RegExp(`sel=${p.id}`));
      await expect(bar).toBeVisible();
      await expect(rcmTab).toHaveAttribute("aria-selected", "true");
      expect(query(page).get("tab")).toBe("rcm");
      // A phone folds the tabs that don't fit into "⋯ N": the ones on show at either width.
      for (const name of width > 600 ? ["Summary", "Maintenance", "RCM", "FME(C)A"] : ["Summary", "RCM"]) await expect(bar.getByRole("tab", { name, exact: true })).toHaveCount(1);
      // The table stays: the child's failure mode is still in it.
      await expect(page.getByText(`Pump seizes ${tag}`).first()).toBeVisible();
    }
    await shot(page, `levels-rcm-parent-${width}`);
    expect(await sideways(page)).toBeLessThanOrEqual(0);

    // The parent's other tabs open on it (a wide screen: the panel beside the tree).
    if (width > 600) {
      await page.locator(`.tp-row[data-key="${a.outdoor.id}"] .tp-nm`).first().click();
      await bar.getByRole("tab", { name: "Maintenance", exact: true }).click();
      await expect(page).toHaveURL(/tab=maintenance/);
      await expect(bar.getByRole("tab", { name: "Maintenance", exact: true })).toHaveAttribute("aria-selected", "true");
      expect(query(page).get("sel")).toBe(a.outdoor.id);
      await expect(page.locator(".tt-headslot")).toContainText(`Outdoor ${tag}`);
      // The tasks there and below, in the tree: the level's roll-up beside its name.
      await expect(page.locator(".tt-headslot")).toContainText(/tasks? |No tasks here or below/);
      await shot(page, `levels-maintenance-parent-${width}`);
      await bar.getByRole("tab", { name: "Summary", exact: true }).click();
      await expect(bar.getByRole("tab", { name: "Summary", exact: true })).toHaveAttribute("aria-selected", "true");
      await expect(page.getByRole("region", { name: "Details" })).toContainText(`Pool ${tag}`);
      await shot(page, `levels-summary-parent-${width}`);
    }
    await expectHealthy(page, problems);
  });
}
