// The one search for everything (components/GlobalSearch.jsx): ⌘K / Ctrl-K from anywhere opens the
// search dialog, which finds a part by its number, a product by its name, a position by its tag, a
// feature by the words people use for it ("test planning") and a guide, each opening where it
// lives; Escape closes it and gives the focus back. At 1440 px and 400 px (full screen there), and
// nothing scrolls the page sideways.
//
// With SMOKE_SHOTS_DIR set, it also saves screenshots there (for the pull request).
import { test, expect, open, postOk } from "./health.js";
import { SMOKE_PRODUCT } from "./seed.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

test.describe.configure({ mode: "serial" });

for (const [width, height] of [[1440, 900], [400, 860]]) {
  test(`One search at ${width} px: a part, a product, a position, a feature and a guide`, async ({ page, request }) => {
    test.setTimeout(120000);
    await page.setViewportSize({ width, height });
    const w = width;
    // A part and a tagged position of this run's own, so the search has something unique to find.
    const run = `${w}${Date.now() % 100000}`;
    const part = await postOk(request, `${M}/parts`, { part_number: `GS-${run}`, name: "Oil filter element" });
    const site = await postOk(request, `${M}/locations`, { name: `Search yard ${run}` });
    const pos = await postOk(request, `${M}/positions`, { name: "Transfer pump", tag: `TP-${run}`, location_id: site.id });

    await open(page, "/home");
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await shot(page, `${w}-header`);
    const dialog = page.getByRole("dialog", { name: "Search" });
    const box = dialog.getByRole("combobox", { name: "Search everything" });
    const search = async (q) => {
      await page.keyboard.press("ControlOrMeta+k");
      await expect(box).toBeFocused();
      await box.fill(q);
    };
    const option = (name) => dialog.getByRole("option", { name });

    // ⌘K opens it from anywhere; Escape closes it and focus goes back.
    await page.locator("main").click({ position: { x: 5, y: 5 } });
    await search("x");
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    // The top bar's box opens it too, and takes the focus back when it closes.
    const trigger = page.getByRole("button", { name: "Search everything" });
    await trigger.click();
    await expect(box).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(trigger).toBeFocused();

    // A part by its number: in the Parts group, opening its page.
    await search(`gs-${run}`);
    await expect(dialog.locator(".gsearch-group-head").first()).toContainText("Parts");
    await expect(option(new RegExp(`GS-${run}`))).toBeVisible();
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await shot(page, `${w}-search-part`);
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(new RegExp(`/asset-register/parts/${part.id}$`));
    await expect(page.getByRole("heading", { level: 1 })).toContainText(`GS-${run}`);

    // A product by its name: its page.
    await search(SMOKE_PRODUCT.toLowerCase());
    await option(new RegExp(`^${SMOKE_PRODUCT}`)).first().click();
    await expect(page).toHaveURL(/\/products\/[^/?]+$/);

    // A position of a product's design: the product's page, with it picked.
    await search("drive");
    const designRow = dialog.getByRole("option").filter({ hasText: `In product ${SMOKE_PRODUCT}` }).first();
    await expect(designRow).toBeVisible();
    await designRow.click();
    await expect(page).toHaveURL(/\/products\/[^/?]+\?sel=/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Drive");

    // A position by its tag: the Explorer on its own asset, with it picked.
    await search(`TP-${run}`);
    await expect(option(new RegExp(`TP-${run} · Transfer pump`))).toBeVisible();
    await shot(page, `${w}-search-position`);
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(new RegExp(`/asset-register/explorer\\?.*root=${site.id}.*sel=${pos.id}`));
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Transfer pump");

    // A feature by what people call it: the page, with no record named so.
    await search("test planning");
    const groups = dialog.locator(".gsearch-group-head");
    await expect(groups.first()).toContainText("Pages and tabs");
    await shot(page, `${w}-search-feature`);
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/strategy\/test-planning$/);

    // ↓ and Tab move through the results; a guide opens in the help drawer.
    await search("rcm study");
    await expect(dialog.getByRole("group").filter({ hasText: "Guides" })).toBeVisible();
    const guide = dialog.getByRole("group").filter({ hasText: "Guides" }).getByRole("option").first();
    for (let i = 0; i < 8 && (await guide.getAttribute("aria-selected")) !== "true"; i++) await page.keyboard.press("Tab");
    await expect(guide).toHaveAttribute("aria-selected", "true");
    await shot(page, `${w}-search-guide`);
    await page.keyboard.press("Enter");
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole("dialog", { name: "Help" })).toBeVisible();

    // A near spelling still finds the part.
    await page.keyboard.press("Escape");
    await search("oil filtr element");
    await expect(option(new RegExp(`GS-${run}`))).toBeVisible();
    await page.keyboard.press("Escape");

    // The public guides page filters its list, as the Guides drawer does.
    await open(page, "/guides");
    await page.getByRole("searchbox", { name: "Filter guides…" }).fill("weibull");
    await expect(page.locator(".blog-card").first()).toBeVisible();
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await shot(page, `${w}-guides-filter`);
    await page.getByRole("searchbox", { name: "Filter guides…" }).fill("zzqqxx");
    await expect(page.getByText(/No guide matches/)).toBeVisible();
  });
}
