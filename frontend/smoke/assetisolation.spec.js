// One asset opened on its own (Derryn, 14 Nov 2026: "assets and all their linkages needs to be
// completely isolated"). Two assets, each a place with positions, connected (the farm's bore feeds
// the house's hot water), one item class fitted in both, an RCM on each and a spare at each. Opened
// from the Assets page, or by a link naming a row inside it, the Explorer shows that asset alone: no
// name of the other asset in any arrangement, the filter, the RCM tab, Classes and its fleet, or the
// Add and Move pickers, at 1440 and 400 px. There's no whole register (Derryn, 14 Nov 2026: "They
// have to go out and view all the assets and select one at a time"): no "Show every asset", and an
// Explorer address with no asset in it (the bare address, an old ?all=1 link) lands on Assets.
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const row = (page, name) => page.getByRole("treeitem", { name: new RegExp(`^${name}`) });
const arrangeSwitch = (page) => page.getByRole("radiogroup", { name: "Arrange by" });
const query = (page) => new URL(page.url()).searchParams;

async function twoAssets(request, tag) {
  const post = (path, body) => postOk(request, `${M}${path}`, body);
  const cls = await post("/item-classes", { name: `Heater ${tag}` });
  const house = await post("/locations", { name: `Anthony ${tag}` });
  const kitchen = await post("/locations", { name: `Kitchen ${tag}`, parent_id: house.id });
  const farm = await post("/locations", { name: `Farm ${tag}` });
  const hws = await post("/positions", { name: `Hot water ${tag}`, location_id: kitchen.id });
  const elem = await post("/positions", { name: `Element ${tag}`, parent_id: hws.id });
  const bore = await post("/positions", { name: `Bore pump ${tag}`, location_id: farm.id });
  for (const [pos, name] of [[elem, `Element unit ${tag}`], [bore, `Bore unit ${tag}`]]) {
    const fit = await post(`/positions/${pos.id}/fit`, { new_item: { name, serial: `${name.slice(0, 4)}-${tag}` } });
    await post("/item-classes/assign", { target_id: fit.fitted.item.id, item_class_id: cls.id });
  }
  const spareA = await post("/items", { name: `House spare ${tag}`, serial: `HS-${tag}` });
  await post(`/items/${spareA.id}/place`, { location_id: kitchen.id });
  const spareB = await post("/items", { name: `Farm spare ${tag}`, serial: `FS-${tag}` });
  await post(`/items/${spareB.id}/place`, { location_id: farm.id });
  await post("/interfaces", { from_id: bore.id, to_id: hws.id, kind: "flow", medium: "water" });
  await post(`/positions/${hws.id}/failure-modes`, { text: `Tank corrodes ${tag}`, function: `Heat water ${tag}`, failure: `No hot water ${tag}` });
  await post(`/positions/${bore.id}/failure-modes`, { text: `Impeller wears ${tag}`, function: `Lift water ${tag}`, failure: `No water ${tag}` });
  return { cls, house, kitchen, farm, hws, elem, bore };
}

// Every name of the farm's asset: none may be on the page.
const farmNames = (tag) => [`Farm ${tag}`, `Bore pump ${tag}`, `Bore unit ${tag}`, `Farm spare ${tag}`, `Impeller wears ${tag}`, `Lift water ${tag}`];
async function noFarm(page, tag, where) {
  const text = await page.locator("body").innerText();
  for (const name of farmNames(tag)) expect(text.includes(name), `${where}: "${name}" shows`).toBe(false);
}

for (const width of [1440, 400]) {
  test(`an asset opened from Assets shows nothing of another asset (${width} px)`, async ({ page, request, problems }) => {
    const tag = `iso${width}${Date.now()}`;
    const a = await twoAssets(request, tag);
    await page.setViewportSize({ width, height: 900 });

    // From the Assets page: the asset's name opens it alone.
    await open(page, "/asset-register");
    await page.getByRole("link", { name: `Anthony ${tag}` }).click();
    await expect(page).toHaveURL(new RegExp(`root=${a.house.id}`));
    // Always one asset: nothing offers the whole register.
    await expect(page.getByText("Show every asset")).toHaveCount(0);
    await expect(page.getByText("One asset", { exact: true })).toHaveCount(0);
    const sw = arrangeSwitch(page);
    const tree = page.getByRole("tree");
    // Locations (as it opens), then Positions, then Classes.
    await expect(tree.getByRole("treeitem", { name: new RegExp(`^Kitchen ${tag}`) })).toBeVisible();
    await noFarm(page, tag, "by Locations");
    await shot(page, `isolation-locations-${width}`);
    await shot(page, `one-asset-header-${width}`);
    if (width > 600) {
      await sw.getByRole("radio", { name: "Positions" }).click();
      await expect(page).toHaveURL(new RegExp(`root=${a.house.id}`));
      await expect(row(page, `Hot water ${tag}`)).toBeVisible();
      await noFarm(page, tag, "by Positions");
      await sw.getByRole("radio", { name: "Classes" }).click();
      await expect(page).toHaveURL(new RegExp(`root=${a.house.id}`));
      const clsRow = row(page, `Heater ${tag}`);
      await expect(clsRow.locator(".tp-cnt")).toHaveText("1 position");
      await clsRow.click();
      await expect(page.locator(".cf-answer")).toContainText("1 position");
      await noFarm(page, tag, "by Classes and its fleet");
      await shot(page, `isolation-classes-${width}`);
      // Back to Positions on the Summary tab (the add row is the Summary's).
      await open(page, `/asset-register/explorer?arrange=positions&root=${a.house.id}`);

      // The filter finds nothing of the farm, and this asset's rows still.
      const filter = page.getByRole("searchbox", { name: "Filter the tree" });
      await filter.fill("Bore");
      await expect(row(page, `Hot water ${tag}`)).toHaveCount(0);
      await expect(row(page, `Bore pump ${tag}`)).toHaveCount(0);
      await filter.fill(tag);
      await expect(row(page, `Element ${tag}`)).toBeVisible();
      await noFarm(page, tag, "filtered");
      await filter.fill("");

      // The Add pickers: a new position's places and a move's targets are this asset's.
      // A new top position is at this asset's place, and its places are this asset's.
      await page.getByRole("button", { name: `New position at Anthony ${tag}` }).click();
      const add = page.getByRole("dialog").first();
      const opts = (await add.locator("option").allTextContents()).join("|");
      for (const name of farmNames(tag)) expect(opts.includes(name), `New position: ${name}`).toBe(false);
      expect(opts.includes(`Kitchen ${tag}`)).toBe(true);
      await add.getByRole("button", { name: "Cancel" }).click();
      await row(page, `Element ${tag}`).locator(".tp-nm").click({ button: "right" });
      const menu = page.getByRole("menu", { name: new RegExp(`^Actions for Element ${tag}`) });
      await menu.getByRole("menuitem", { name: "Move to…" }).click();
      const move = page.getByRole("dialog", { name: `Move “Element ${tag}”` });
      const targets = (await move.getByRole("combobox").locator("option").allTextContents()).join("|");
      expect(targets.includes(`Hot water ${tag}`)).toBe(true);
      expect(targets.includes(`Bore pump ${tag}`)).toBe(false);
      await move.getByRole("button", { name: "Cancel" }).click();
    }

    // The RCM tab: this asset's RCM alone.
    await open(page, `/asset-register/explorer?arrange=positions&root=${a.house.id}&tab=rcm&sel=${a.hws.id}`);
    await expect(page.getByText(`Tank corrodes ${tag}`).first()).toBeVisible();
    await noFarm(page, tag, "the RCM tab");
    await shot(page, `isolation-rcm-${width}`);
    expect(await sideways(page)).toBeLessThanOrEqual(1);

    // The Explorer with no asset in its address: the Assets list, to pick one; picking opens it alone,
    // with the tab the address asked for.
    await open(page, "/asset-register/explorer?arrange=positions&tab=rcm");
    await expect(page).toHaveURL(/\/asset-register$/);
    await expect(page.getByRole("heading", { name: "Assets", level: 1 })).toBeVisible();
    await expect(page.getByText("Pick an asset to open it in the Explorer.")).toBeVisible();
    await shot(page, `one-asset-landing-${width}`);
    expect(await sideways(page)).toBeLessThanOrEqual(1);
    await page.getByRole("link", { name: `Farm ${tag}` }).click();
    await expect(page).toHaveURL(new RegExp(`root=${a.farm.id}`));
    await expect(page).toHaveURL(/tab=rcm/);
    await expect(page.getByRole("treegrid").getByRole("row", { name: new RegExp(`^Bore pump ${tag}`) })).toBeVisible();
    expect((await page.locator("body").innerText()).includes(`Hot water ${tag}`)).toBe(false);
    await expectHealthy(page, problems, { label: `one asset opened from Assets at ${width}` });
  });
}

test("links that name a row inside an asset land on that asset alone; anything else lands on Assets", async ({ page, request, problems }) => {
  const tag = `isl${Date.now()}`;
  const a = await twoAssets(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });

  // A link naming a position deep inside (a work order's, a failure report's): its asset, that row picked.
  await open(page, `/asset-register/explorer?arrange=positions&sel=${a.elem.id}`);
  await expect(page).toHaveURL(new RegExp(`root=${a.house.id}`));
  await expect(row(page, `Element ${tag}`)).toHaveAttribute("aria-selected", "true");
  await noFarm(page, tag, "a link to a position");
  // The farm's own link: the farm alone.
  await open(page, `/asset-register/explorer?arrange=positions&tab=rcm&sel=${a.bore.id}`);
  await expect(page).toHaveURL(new RegExp(`root=${a.farm.id}`));
  await expect(page.getByText(`Impeller wears ${tag}`).first()).toBeVisible();
  expect((await page.locator("body").innerText()).includes(`Tank corrodes ${tag}`)).toBe(false);

  // Back and forward keep each address as it was.
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`root=${a.house.id}`));
  await page.goForward();
  await expect(page).toHaveURL(new RegExp(`root=${a.farm.id}`));

  // The bare address and an old whole-register link (?all=1, even naming a row): the Assets list,
  // never a tree with both assets in it.
  for (const to of ["/asset-register/explorer", "/asset-register/explorer?arrange=locations",
    `/asset-register/explorer?arrange=locations&all=1&sel=${a.kitchen.id}`]) {
    await open(page, to);
    await expect(page, to).toHaveURL(/\/asset-register$/);
    await expect(page.getByRole("tree")).toHaveCount(0);
    await expect(page.getByRole("link", { name: `Anthony ${tag}` })).toBeVisible();
    await expect(page.getByRole("link", { name: `Farm ${tag}` })).toBeVisible();
  }
  await expectHealthy(page, problems, { label: "links into one asset" });
  // An asset that isn't there (deleted, an old link): said so, with the way to the Assets list
  // (the 404 behind it is the browser's console line, so after the health check).
  await open(page, "/asset-register/explorer?arrange=locations&root=no-such-asset");
  await expect(page.getByRole("heading", { name: "That asset isn't here" })).toBeVisible();
  await expect(page.getByRole("link", { name: "See the assets" }).first()).toBeVisible();
});
