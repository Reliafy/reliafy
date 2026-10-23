// The asset tree pane (Operate › Assets › Positions and Locations): open and
// close, the levels, the filter that keeps the path to a match, the panel for
// the row picked, the Locations arrangement, and the phone's slide to the
// panel and back. Each test makes its own small plant through the API.
import { test, expect, open, expectHealthy } from "./health.js";

const M = "/api/maintenance";

async function plant(request, tag) {
  const post = async (path, data) => {
    const res = await request.post(path, { data });
    expect(res.ok(), `${path}: ${res.status()}`).toBeTruthy();
    return res.json();
  };
  const site = await post(`${M}/locations`, { name: `Tree site ${tag}` });
  const top = await post(`${M}/positions`, { name: `Tree plant ${tag}`, location_id: site.id });
  const line = await post(`${M}/positions`, { name: `Tree line ${tag}`, parent_id: top.id });
  const motor = await post(`${M}/positions`, { name: `Tree motor ${tag}`, parent_id: line.id, position_class: "Electric motor" });
  const seal = await post(`${M}/positions`, { name: `Tree seal ${tag}`, parent_id: motor.id, position_class: "Mechanical seal" });
  await post(`${M}/positions/${motor.id}/tasks`, { name: "Grease", interval: 1, unit: "months", last_done: "2020-01-01" });
  await post(`${M}/work-orders`, { position_id: seal.id, title: `Tree leak ${tag}` });
  return { site, top, line, motor, seal };
}

const row = (page, name) => page.getByRole("treeitem", { name: new RegExp(`^${name}`) });

test("the tree pane: open, close, levels, filter, and the panel for the row picked", async ({ page, request, problems }) => {
  const tag = `a${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/positions?sel=${p.top.id}`);
  await expect(page.getByRole("heading", { name: "Positions", exact: true })).toBeVisible();
  const tree = page.getByRole("tree", { name: "Positions" });
  await expect(tree).toBeVisible();

  // Picked from the address: the panel shows it, with what's inside rolled up.
  const top = row(page, `Tree plant ${tag}`);
  await expect(top).toHaveAttribute("aria-selected", "true");
  const panel = page.getByRole("region", { name: "Details" });
  await expect(panel.getByRole("heading", { name: `Tree plant ${tag}` })).toBeVisible();
  await expect(panel.getByText("1 overdue inside")).toBeVisible();
  await expect(panel.getByText("1 open work order inside")).toBeVisible();
  await expect(panel.getByRole("link", { name: "Open the full page" })).toHaveAttribute("href", `/asset-register/positions/${p.top.id}`);

  // Open and close with the arrow keys, and the levels.
  await top.focus();
  await expect(top).toHaveAttribute("aria-expanded", "true"); // the tops start open
  await page.keyboard.press("ArrowLeft");
  await expect(top).toHaveAttribute("aria-expanded", "false");
  await expect(row(page, `Tree line ${tag}`)).toHaveCount(0);
  await page.keyboard.press("ArrowRight");
  await expect(top).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("ArrowRight");
  await expect(row(page, `Tree line ${tag}`)).toBeFocused();
  await expect(row(page, `Tree line ${tag}`)).toHaveAttribute("aria-expanded", "false");
  await page.keyboard.press("ArrowLeft");
  await expect(top).toBeFocused();
  await page.getByRole("button", { name: "Open everything" }).click();
  await expect(row(page, `Tree seal ${tag}`)).toBeVisible();
  await expect(row(page, `Tree seal ${tag}`)).toHaveAttribute("aria-level", "4");
  await page.getByRole("button", { name: "Open to level 1" }).click();
  await expect(row(page, `Tree line ${tag}`)).toHaveCount(0);

  // The filter keeps the path down to a match.
  await page.getByLabel("Filter the tree").fill(`Tree seal ${tag}`);
  await expect(page.getByText("1 match, shown with what they're inside")).toBeVisible();
  for (const name of ["plant", "line", "motor", "seal"]) await expect(row(page, `Tree ${name} ${tag}`)).toBeVisible();
  await row(page, `Tree seal ${tag}`).click();
  await expect(panel.getByRole("heading", { name: `Tree seal ${tag}` })).toBeVisible();
  await expect(panel.getByRole("button", { name: `Tree motor ${tag}` })).toBeVisible(); // the breadcrumb
  await expect(panel.getByRole("link", { name: new RegExp(`Tree leak ${tag}`) })).toBeVisible();
  await page.getByLabel("Filter the tree").fill("");

  // A breadcrumb, then a row in "Directly inside", picks that row in the tree.
  await panel.getByRole("button", { name: `Tree line ${tag}` }).click();
  await expect(panel.getByRole("heading", { name: `Tree line ${tag}` })).toBeVisible();
  await panel.getByRole("button", { name: `Tree motor ${tag}` }).click();
  await expect(panel.getByRole("heading", { name: `Tree motor ${tag}` })).toBeVisible();
  await expect(panel.getByText("1 overdue task")).toBeVisible();
  await expect(row(page, `Tree motor ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expectHealthy(page, problems, { label: "the tree pane" });

  // Remembered: a reload comes back to the same row.
  await open(page, "/asset-register/positions");
  await expect(row(page, `Tree motor ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("region", { name: "Details" }).getByRole("heading", { name: `Tree motor ${tag}` })).toBeVisible();
});

test("arranged by locations, and the menu follows", async ({ page, request, problems }) => {
  const tag = `b${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/positions?sel=${p.line.id}`);
  await page.getByRole("radio", { name: "Locations" }).click();
  await expect(page).toHaveURL(/\/asset-register\/locations$/);
  await expect(page.getByRole("heading", { name: "Locations", exact: true })).toBeVisible();
  await expect(page.locator(".side-subitem.active")).toHaveText("Locations");
  // The position picked stays picked, shown inside its location.
  await expect(row(page, `Tree line ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expect(row(page, `Tree site ${tag}`)).toHaveAttribute("aria-expanded", "true");
  await row(page, `Tree site ${tag}`).click();
  const panel = page.getByRole("region", { name: "Details" });
  await expect(panel.getByRole("heading", { name: `Tree site ${tag}` })).toBeVisible();
  await expect(panel.getByRole("link", { name: "Open the full page" })).toHaveAttribute("href", `/asset-register/locations/${p.site.id}`);
  await expectHealthy(page, problems, { label: "arranged by locations" });

  await page.getByRole("radio", { name: "Flat" }).click();
  await expect(page).toHaveURL(/\/asset-register\/positions\?arrange=flat$/);
  await expect(page.locator(".side-subitem.active")).toHaveText("Positions");
  await expectHealthy(page, problems, { label: "flat" });
});

test("on a phone: the tree, then the panel, and back", async ({ page, request, problems }) => {
  const tag = `c${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/positions?sel=${p.top.id}`);
  const panel = page.getByRole("region", { name: "Details" });
  await expect(page.getByRole("tree", { name: "Positions" })).toBeVisible();
  await expect(panel.getByRole("heading", { name: `Tree plant ${tag}` })).toHaveCount(0);
  await row(page, `Tree plant ${tag}`).locator(".tp-nm").click();
  await expect(panel.getByRole("heading", { name: `Tree plant ${tag}` })).toBeVisible();
  await expect(page.getByRole("tree")).toBeHidden();
  const wide = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(wide, "the page scrolls sideways").toBeLessThanOrEqual(400);
  await page.goBack();
  await expect(page.getByRole("tree", { name: "Positions" })).toBeVisible();
  await expect(row(page, `Tree plant ${tag}`)).toBeVisible();
  // The arrow closes and opens a row without leaving the tree.
  await row(page, `Tree plant ${tag}`).locator(".tp-chev").click();
  await expect(row(page, `Tree line ${tag}`)).toHaveCount(0);
  await row(page, `Tree plant ${tag}`).locator(".tp-chev").click();
  await expect(row(page, `Tree line ${tag}`)).toBeVisible();
  await expect(page.getByRole("tree")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await expectHealthy(page, problems, { label: "the tree on a phone" });
});
