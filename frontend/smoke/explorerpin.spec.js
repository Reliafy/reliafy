// "Pin this branch" in the Explorer (Operate › Assets › Explorer): a row's
// menu or the pin in the panel's heading shows only that row and what's
// inside it; the pin's note in the tree's column header (no row of its own),
// its ✕ (Show everything), "Show whole tree" in the ⋯ menu, Reset; the levels, search and counts on the branch; a crumb
// above it moves the pin up; Back un-pins; the RCM tab with a pin; a row
// outside the branch, or a pinned row that's gone; full screen; 400 px (the
// pinned row itself carries the pin and the ✕).
// Each test makes its own small plant through the API.
//
// The names start "Works" so they sort after the other specs' plants ("Rcm",
// "Tree"), which share the server and expect their rows near the top.
// With SMOKE_SHOTS_DIR set, it also saves screenshots there (for the pull request).
import { test, expect, open, expectHealthy } from "./health.js";
import { details } from "./explorer.js";

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
  const site = await post(`${M}/locations`, { name: `Works site ${tag}` });
  const top = await post(`${M}/positions`, { name: `Works plant ${tag}`, location_id: site.id });
  const lineA = await post(`${M}/positions`, { name: `Works line A ${tag}`, parent_id: top.id });
  const pumpA = await post(`${M}/positions`, { name: `Works pump A ${tag}`, parent_id: lineA.id });
  const sealA = await post(`${M}/positions`, { name: `Works seal A ${tag}`, parent_id: pumpA.id });
  const lineB = await post(`${M}/positions`, { name: `Works line B ${tag}`, parent_id: top.id });
  const pumpB = await post(`${M}/positions`, { name: `Works pump B ${tag}`, parent_id: lineB.id });
  const other = await post(`${M}/positions`, { name: `Works other ${tag}` });
  const fn = await post(`${M}/positions/${pumpA.id}/functions`, { text: `Pump water ${tag}` });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `No flow ${tag}` });
  await post(`${M}/positions/${pumpA.id}/failure-modes`, { text: `Seal leaks ${tag}`, functional_failure_id: ff.id });
  return { site, top, lineA, pumpA, sealA, lineB, pumpB, other, fn };
}

// On a phone the pinned row's name starts "Pinned: ".
const row = (page, name) => page.getByRole("treeitem", { name: new RegExp(`^(Pinned: )?${name}`) });
// The pin's note: in the tree's column header, on both tabs (a wide screen).
const bar = (page) => page.locator(".tt-head").getByRole("group", { name: "Pinned branch" });
const panel = details;
const rowMenu = (page, name) => page.getByRole("menu", { name: new RegExp(`^Actions for ${name}`) });
const query = (page) => new URL(page.url()).searchParams;
async function treeMenu(page) {
  const menu = page.getByRole("menu", { name: "Tree options" });
  if (!(await menu.isVisible())) await page.getByRole("button", { name: /^Tree options/ }).click();
  await expect(menu).toBeVisible();
  return menu;
}
async function fromTreeMenu(page, role, name) {
  const menu = await treeMenu(page);
  await menu.getByRole(role, { name, exact: true }).click();
  if (await menu.isVisible()) await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
}

test("pin a branch from a row's menu: only it shows; levels, search and counts on it; Show everything; Back", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.lineA.id}`);
  await expect(row(page, `Works line A ${tag}`)).toHaveAttribute("aria-level", "2");

  // Right-click the line: Pin this branch (after the changes to the tree, before Retire).
  await row(page, `Works line A ${tag}`).locator(".tp-nm").click({ button: "right" });
  const menu = rowMenu(page, `Works line A ${tag}`);
  await expect(menu.getByRole("menuitem", { name: "Pin this branch" })).toBeVisible();
  await shot(page, "1-row-menu-pin-this-branch");
  await menu.getByRole("menuitem", { name: "Pin this branch" }).click();
  await expect.poll(() => query(page).get("pin")).toBe(p.lineA.id);

  // Only the line and what's inside it; the column header says so (the whole
  // path in its tooltip), with no row of its own; the line is the top.
  await expect(bar(page)).toContainText(`Pinned: Works line A ${tag}`);
  await expect(bar(page).locator(".tt-pinned-nm")).toHaveAttribute("title", `Pinned: Works plant ${tag} › Works line A ${tag}`);
  await expect(page.locator(".tt-row3")).toHaveCount(0);
  await expect(row(page, `Works line A ${tag}`)).toHaveAttribute("aria-level", "1");
  await expect(row(page, `Works line A ${tag}`)).toHaveAttribute("aria-expanded", "true");
  await expect(row(page, `Works pump A ${tag}`)).toBeVisible();
  for (const gone of [`Works plant ${tag}`, `Works line B ${tag}`, `Works other ${tag}`]) await expect(row(page, gone)).toHaveCount(0);
  await expect(page.locator(".tp-status")).toHaveText("3 positions");
  await expect(page.getByRole("button", { name: "Tree options: 1 changed" })).toBeVisible();
  // The panel's heading: the pin is on; the way up still shows the plant.
  await expect(panel(page).getByRole("button", { name: "Pin this branch" })).toHaveAttribute("aria-pressed", "true");
  await expect(panel(page).getByRole("button", { name: `Works plant ${tag}` })).toBeVisible();
  await shot(page, "2-pinned-positions-tree");

  // The levels count from the pinned row.
  await fromTreeMenu(page, "menuitemradio", "Open to level 1");
  await expect(row(page, `Works pump A ${tag}`)).toHaveCount(0);
  await fromTreeMenu(page, "menuitemradio", "Open everything");
  await expect(row(page, `Works seal A ${tag}`)).toHaveAttribute("aria-level", "3");
  // The search looks inside the branch only.
  await page.getByLabel("Filter the tree").fill(`Works pump`);
  await expect(page.getByText("1 match, shown with what they're inside")).toBeVisible();
  await expect(row(page, `Works pump B ${tag}`)).toHaveCount(0);
  await page.getByLabel("Filter the tree").fill("");
  // Esc doesn't un-pin.
  await row(page, `Works seal A ${tag}`).click();
  await row(page, `Works seal A ${tag}`).press("Escape");
  await expect(bar(page)).toBeVisible();

  // A crumb above the pinned row moves the pin up to it.
  await panel(page).getByRole("button", { name: `Works plant ${tag}` }).click();
  await expect.poll(() => query(page).get("pin")).toBe(p.top.id);
  await expect(bar(page)).toContainText(`Pinned: Works plant ${tag}`);
  await expect(row(page, `Works line B ${tag}`)).toBeVisible();
  await expect(row(page, `Works line A ${tag}`)).toHaveAttribute("aria-expanded", "true"); // the branch just left stays open
  await expect(row(page, `Works other ${tag}`)).toHaveCount(0);

  // Back: the pin moves back down; again: the whole tree.
  await page.goBack();
  await expect.poll(() => query(page).get("pin")).toBe(p.lineA.id);
  await expect(bar(page)).toContainText(`Works line A ${tag}`);
  await page.goBack();
  await expect.poll(() => query(page).get("pin")).toBe(null);
  await expect(bar(page)).toHaveCount(0);
  await expect(row(page, `Works line A ${tag}`)).toHaveAttribute("aria-level", "2");

  // Forward pins again; "Show whole tree" at the top of the ⋯ menu un-pins.
  await page.goForward();
  await expect(bar(page)).toBeVisible();
  const opts = await treeMenu(page);
  await expect(opts.getByRole("menuitem").first()).toHaveText("Show whole tree");
  await opts.getByRole("menuitem", { name: "Show whole tree" }).click();
  await expect(bar(page)).toHaveCount(0);
  await expect(row(page, `Works line A ${tag}`)).toHaveAttribute("aria-level", "2");

  // The pin in the panel's heading: on, then off.
  await row(page, `Works pump A ${tag}`).click();
  const pin = panel(page).getByRole("button", { name: "Pin this branch" });
  await expect(pin).toHaveAttribute("aria-pressed", "false");
  await pin.click();
  await expect(bar(page)).toContainText(`Works pump A ${tag}`);
  await expect(page.locator(".tp-status")).toHaveText("2 positions");
  await expect(pin).toHaveAttribute("aria-pressed", "true");
  // Full screen keeps the pin, and its note.
  await page.locator(".td-title").click();
  await page.keyboard.press("f");
  await expect(page.locator(".tx.is-full")).toBeVisible();
  await expect(bar(page)).toBeVisible();
  await page.getByRole("button", { name: "Exit full screen" }).click();
  await expect(page.locator(".tx.is-full")).toHaveCount(0);
  await pin.click();
  await expect(bar(page)).toHaveCount(0);

  // Reset to the usual view un-pins too; and the ✕ (Show everything) in the column header.
  await row(page, `Works line A ${tag}`).locator(".tp-nm").click({ button: "right" });
  await rowMenu(page, `Works line A ${tag}`).getByRole("menuitem", { name: "Pin this branch" }).click();
  await expect(bar(page)).toBeVisible();
  await fromTreeMenu(page, "menuitem", "Reset to the usual view");
  await expect(bar(page)).toHaveCount(0);
  await row(page, `Works plant ${tag}`).locator(".tp-nm").click({ button: "right" });
  await rowMenu(page, `Works plant ${tag}`).getByRole("menuitem", { name: "Pin this branch" }).click();
  await expect(row(page, `Works other ${tag}`)).toHaveCount(0);
  await bar(page).getByRole("button", { name: "Show everything" }).click();
  await expect(bar(page)).toHaveCount(0);
  await expect.poll(() => query(page).get("pin")).toBe(null);
  await expect(page.locator(".tp-status")).not.toHaveText("6 positions");
  await expectHealthy(page, problems, { label: "pinned branch", root: ".tx" });
});

test("the RCM tab with a pin: the one table shows only the branch, its rows' menus as before", async ({ page, request, problems }) => {
  const tag = `r${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, `/asset-register/explorer?arrange=positions&tab=rcm&sel=${p.pumpA.id}&pin=${p.lineA.id}`);
  const table = page.getByRole("treegrid", { name: /and their RCM/ });
  const trow = (name) => table.getByRole("row", { name: new RegExp(name) });
  await expect(table).toBeVisible();
  await expect(bar(page)).toContainText(`Pinned: Works line A ${tag}`);
  // The column still says what it is, to a screen reader.
  await expect(table.getByRole("columnheader", { name: "Function, performance standard, failure or mode" })).toBeVisible();
  await expect(trow(`^Works line A ${tag}`)).toHaveAttribute("aria-level", "1");
  await expect(trow(`^Function: Pump water ${tag}`)).toBeVisible();
  await expect(trow(`Failure mode: Seal leaks ${tag}`)).toBeVisible();
  await expect(trow(`^Works plant ${tag}`)).toHaveCount(0);
  await expect(trow(`^Works line B ${tag}`)).toHaveCount(0);
  await expect(page.locator(".tt-top .tp-status")).toHaveText(/^3 positions · \d+ not analysed · RCM is by position$/);
  // A position's menu: Add function, the worksheet in and out, then Pin this branch (the pinned row: Show whole tree).
  await trow(`^Works pump A ${tag}`).locator(".tt-tree").click({ button: "right" });
  await expect(rowMenu(page, `Works pump A ${tag}`).getByRole("menuitem")).toHaveText(["Add function", "Import worksheet…", "Export CSV", "Isolate", "Pin this branch"]);
  await page.keyboard.press("Escape");
  await trow(`^Works line A ${tag}`).locator(".tt-tree").click({ button: "right" });
  await expect(rowMenu(page, `Works line A ${tag}`).getByRole("menuitem")).toHaveText(["Add function", "Import worksheet…", "Export CSV", "Isolate", "Show whole tree"]);
  await page.keyboard.press("Escape");
  // A function's menu (with the mouse: no moves, a drag does them; Isolate before Delete).
  await trow(`^Function: Pump water ${tag}`).locator(".tt-tree").click({ button: "right" });
  await expect(rowMenu(page, `Function: Pump water ${tag}`).getByRole("menuitem"))
    .toHaveText(["Open…", "Add a performance standard…", "Add functional failure", "Edit description", "Isolate", "Delete function"]);
  await page.keyboard.press("Escape");
  await trow(`^Works pump A ${tag}`).locator(".tt-tree").click();
  await shot(page, "3-pinned-rcm-tab");
  // The heading's pin, and its way up (the plant, above the pinned row).
  await expect(page.locator(".tt-headslot").getByRole("button", { name: "Pin this branch" })).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator(".tt-headslot").getByRole("button", { name: `Works plant ${tag}` })).toBeVisible();
  // Summary keeps the pin.
  await page.getByRole("tab", { name: "Summary" }).click();
  await expect(page.getByRole("tree", { name: "Positions" })).toBeVisible();
  await expect(bar(page)).toBeVisible();
  await expect(row(page, `Works plant ${tag}`)).toHaveCount(0);
  expect(query(page).get("pin")).toBe(p.lineA.id);
  await expectHealthy(page, problems, { label: "pinned RCM tab", root: ".tx" });
});

test("a row outside the branch shows the whole tree again; a pin that's gone quietly goes", async ({ page, request, problems }) => {
  const tag = `o${Date.now()}`;
  const p = await plant(request, tag);
  // ?sel= outside the pinned branch: the whole tree, the row picked, and a note.
  await open(page, `/asset-register/explorer?arrange=positions&pin=${p.lineA.id}&sel=${p.other.id}`);
  await expect(page.locator(".tt-head").getByRole("status")).toHaveText("Showing the whole tree again");
  await expect(bar(page)).toHaveCount(0);
  await expect(row(page, `Works other ${tag}`)).toHaveAttribute("aria-selected", "true");
  expect(query(page).get("pin")).toBe(null);
  // A pinned row that isn't there (retired, deleted): no pin, no note.
  await open(page, `/asset-register/explorer?arrange=positions&pin=not-a-position-${tag}`);
  await expect.poll(() => query(page).get("pin")).toBe(null);
  await expect(page.getByRole("tree", { name: "Positions" })).toBeVisible();
  await expect(page.getByText("Showing the whole tree again")).toHaveCount(0);
  // Flat can't pin: the pin goes, and its rows' menus have no Pin this branch.
  await open(page, `/asset-register/explorer?arrange=flat&pin=${p.lineA.id}&sel=${p.lineA.id}`);
  await expect.poll(() => query(page).get("pin")).toBe(null);
  await expect(row(page, `Works line A ${tag}`)).toHaveAttribute("aria-selected", "true");
  await row(page, `Works line A ${tag}`).locator(".tp-nm").click({ button: "right" });
  await expect(rowMenu(page, `Works line A ${tag}`).getByRole("menuitem", { name: "Rename…" })).toBeVisible();
  await expect(rowMenu(page, `Works line A ${tag}`).getByRole("menuitem", { name: "Pin this branch" })).toHaveCount(0);
  await page.keyboard.press("Escape");
  // Locations: pin the site; its positions show inside it.
  await open(page, `/asset-register/explorer?arrange=locations&sel=${p.site.id}`);
  await row(page, `Works site ${tag}`).locator(".tp-nm").click({ button: "right" });
  await rowMenu(page, `Works site ${tag}`).getByRole("menuitem", { name: "Pin this branch" }).click();
  await expect(bar(page)).toContainText(`Works site ${tag}`);
  await expect(row(page, `Works plant ${tag}`)).toBeVisible();
  await expect(page.locator(".tp-status")).toHaveText(/^1 location · 6 positions$/);
  await expectHealthy(page, problems, { label: "pin outside and gone", root: ".tx" });
});

test("at 400 px: the pinned row carries the pin and an easy-to-tap ✕; the row's ⋯ pins; nothing scrolls sideways", async ({ page, request, problems }) => {
  const tag = `w${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.top.id}`);
  const treeTop = (await page.locator(".tp-scroll").boundingBox()).y;
  const more = row(page, `Works line A ${tag}`).getByRole("button", { name: "Actions", exact: true });
  await expect(more).toHaveCSS("opacity", "1");
  await more.click();
  await rowMenu(page, `Works line A ${tag}`).getByRole("menuitem", { name: "Pin this branch" }).click();
  // No row of its own: the tree starts where it did; the pinned row says it.
  const pinned = row(page, `Works line A ${tag}`);
  await expect(pinned).toHaveAccessibleName(new RegExp(`^Pinned: Works line A ${tag}`));
  await expect(pinned.locator(".tp-pinmark")).toBeVisible();
  expect((await page.locator(".tp-scroll").boundingBox()).y).toBe(treeTop);
  const x = pinned.getByRole("button", { name: "Show everything" });
  await expect(x).toBeVisible();
  const xb = await x.boundingBox();
  expect(xb.height).toBeGreaterThanOrEqual(36);
  expect(xb.width).toBeGreaterThanOrEqual(36);
  expect(xb.x + xb.width).toBeLessThanOrEqual(400);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await expect(row(page, `Works plant ${tag}`)).toHaveCount(0);
  await shot(page, "4-phone-400px-pinned");
  // The RCM tab: the same on its two-line rows.
  await page.getByRole("tab", { name: "RCM" }).click();
  const trow = page.getByRole("row", { name: new RegExp(`^Pinned: Works line A ${tag}`) });
  await expect(trow.getByRole("button", { name: "Show everything" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await shot(page, "5-phone-400px-pinned-rcm");
  await page.getByRole("tab", { name: "Summary" }).click();
  // The panel, and back to the pinned tree.
  await row(page, `Works pump A ${tag}`).locator(".tp-nm").click();
  await expect(panel(page).getByRole("heading", { name: `Works pump A ${tag}` })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await page.goBack();
  await expect(x).toBeVisible();
  await x.click();
  await expect(x).toHaveCount(0);
  await expect.poll(() => query(page).get("pin")).toBe(null);
  await expect(row(page, `Works line A ${tag}`)).toHaveAttribute("aria-level", "2");
  await expectHealthy(page, problems, { label: "pinned at 400 px", root: ".tx" });
});
