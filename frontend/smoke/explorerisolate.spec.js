// "Isolate ›" in the Explorer's row menus (Operate › Assets › Explorer): a
// one-off change to what's open. Every other branch closes (its rows still on
// show), the rows above stay open, and the row opens 1, 2 or 3 levels below
// it, or all of them; it's picked and in view; nothing is hidden, the address
// doesn't change, the frame doesn't move; rows open and close by hand after.
// From the mouse and the keyboard, on both tabs, inside a pinned branch, and
// at 400 px (the submenu opens in place). Also: the RCM tab's mouse menus
// have no moves (a drag does them); the keyboard's and the phone's do.
// Each test makes its own small plant through the API.
//
// The names start "Works" so they sort after the other specs' plants ("Rcm",
// "Tree"), which share the server and expect their rows near the top.
// With SMOKE_SHOTS_DIR set, it also saves screenshots there (for the pull request).
import { test, expect, open, expectHealthy } from "./health.js";

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
  const top = await post(`${M}/positions`, { name: `Works plant ${tag}` });
  const lineA = await post(`${M}/positions`, { name: `Works line A ${tag}`, parent_id: top.id });
  const pumpA = await post(`${M}/positions`, { name: `Works pump A ${tag}`, parent_id: lineA.id });
  const sealA = await post(`${M}/positions`, { name: `Works seal A ${tag}`, parent_id: pumpA.id });
  const lineB = await post(`${M}/positions`, { name: `Works line B ${tag}`, parent_id: top.id });
  const pumpB = await post(`${M}/positions`, { name: `Works pump B ${tag}`, parent_id: lineB.id });
  const fn = await post(`${M}/positions/${pumpA.id}/functions`, { text: `Pump water ${tag}` });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `No flow ${tag}` });
  await post(`${M}/positions/${pumpA.id}/failure-modes`, { text: `Seal leaks ${tag}`, functional_failure_id: ff.id });
  return { top, lineA, pumpA, sealA, lineB, pumpB, fn, ff };
}

const row = (page, name) => page.getByRole("treeitem", { name: new RegExp(`^${name}`) });
const rowMenu = (page, name) => page.getByRole("menu", { name: new RegExp(`^Actions for ${name}`) });
const spoken = (page) => page.locator(".sr-only[role='status']");
const box = async (loc) => {
  const b = await loc.boundingBox();
  return { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) };
};
// Right-click a row, then Isolate › the level asked for (the submenu beside the menu).
async function isolate(page, target, label) {
  await target.click({ button: "right" });
  await page.getByRole("menu").first().getByRole("menuitem", { name: "Isolate", exact: true }).hover();
  const sub = page.getByRole("menu", { name: "Isolate" });
  await expect(sub).toBeVisible();
  await sub.getByRole("menuitem", { name: label }).click();
  await expect(page.getByRole("menu")).toHaveCount(0);
}

test("isolate at 1, 2, 3 levels and everything: the rest closed but on show, the row opened that far; by hand after", async ({ page, request, problems }) => {
  const tag = `i${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.top.id}`);
  const url = page.url();
  const frame = { tree: await box(page.locator(".tp-scroll")), head: await box(page.locator(".tt-head")) };
  // Everything open first, so the closing shows.
  const opts = page.getByRole("button", { name: /^Tree options/ });
  await opts.click();
  await page.getByRole("menu", { name: "Tree options" }).getByRole("menuitemradio", { name: "Open everything" }).click();
  if (await page.getByRole("menu", { name: "Tree options" }).isVisible()) await page.keyboard.press("Escape");
  await expect(row(page, `Works pump B ${tag}`)).toBeVisible();

  // The menu: Isolate › (the four levels beside it), before Pin this branch and Retire.
  await row(page, `Works line A ${tag}`).locator(".tp-nm").click({ button: "right" });
  const menu = rowMenu(page, `Works line A ${tag}`);
  await expect(menu.getByRole("menuitem")).toHaveText(["New position inside", "Rename…", "Move to…", "Isolate", "Pin this branch", /^Retire…/]);
  await expect(menu.getByRole("menuitem", { name: "Isolate" })).toHaveAttribute("aria-haspopup", "menu");
  await menu.getByRole("menuitem", { name: "Isolate" }).hover();
  const sub = page.getByRole("menu", { name: "Isolate" });
  await expect(sub.getByRole("menuitem")).toHaveText(["With 1 level open", "With 2 levels open", "With 3 levels open", "With everything open"]);
  const mb = await menu.boundingBox();
  expect((await sub.boundingBox()).x).toBeGreaterThanOrEqual(mb.x + mb.width - 10);
  await shot(page, "v2-1-row-menu-isolate-submenu-1280");

  // 1 level: line A open, its pump closed; line B closed but still there; the plant open (the way up).
  await sub.getByRole("menuitem", { name: "With 1 level open" }).click();
  await expect(row(page, `Works line A ${tag}`)).toHaveAttribute("aria-expanded", "true");
  await expect(row(page, `Works pump A ${tag}`)).toHaveAttribute("aria-expanded", "false");
  await expect(row(page, `Works seal A ${tag}`)).toHaveCount(0);
  await expect(row(page, `Works line B ${tag}`)).toHaveAttribute("aria-expanded", "false");
  await expect(row(page, `Works pump B ${tag}`)).toHaveCount(0);
  await expect(row(page, `Works plant ${tag}`)).toHaveAttribute("aria-expanded", "true");
  await expect(row(page, `Works line A ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expect(spoken(page)).toContainText(`Collapsed the rest of the tree; Works line A ${tag} opened 1 level.`);
  // Nothing hidden or filtered, no notice, the address as it was, the frame where it was.
  await expect(page.locator(".tt-head").getByRole("group", { name: "Pinned branch" })).toHaveCount(0);
  expect(page.url()).toBe(url);
  expect(await box(page.locator(".tp-scroll"))).toEqual(frame.tree);
  expect(await box(page.locator(".tt-head"))).toEqual(frame.head);
  await shot(page, "v2-2-isolated-1-level-1280");

  // 2 levels: the seal shows too.
  await isolate(page, row(page, `Works line A ${tag}`).locator(".tp-nm"), "With 2 levels open");
  await expect(row(page, `Works seal A ${tag}`)).toBeVisible();
  await expect(row(page, `Works line B ${tag}`)).toHaveAttribute("aria-expanded", "false");
  // The plant, 1 level: both lines show, closed (the seal's branch closes again).
  await isolate(page, row(page, `Works plant ${tag}`).locator(".tp-nm"), "With 1 level open");
  await expect(row(page, `Works line A ${tag}`)).toHaveAttribute("aria-expanded", "false");
  await expect(row(page, `Works line B ${tag}`)).toHaveAttribute("aria-expanded", "false");
  await expect(row(page, `Works pump A ${tag}`)).toHaveCount(0);
  // 3 levels and everything: down to the seals.
  await isolate(page, row(page, `Works plant ${tag}`).locator(".tp-nm"), "With 3 levels open");
  await expect(row(page, `Works seal A ${tag}`)).toBeVisible();
  await expect(row(page, `Works pump B ${tag}`)).toBeVisible();
  await isolate(page, row(page, `Works line B ${tag}`).locator(".tp-nm"), "With everything open");
  await expect(row(page, `Works pump B ${tag}`)).toBeVisible();
  await expect(row(page, `Works line A ${tag}`)).toHaveAttribute("aria-expanded", "false");
  await expect(spoken(page)).toContainText("opened every level.");
  // By hand after, as usual.
  await row(page, `Works line A ${tag}`).locator(".tp-chev").click();
  await expect(row(page, `Works pump A ${tag}`)).toBeVisible();

  // From the keyboard: Shift+F10, → into Isolate, ↓, Enter.
  await row(page, `Works line B ${tag}`).click();
  await row(page, `Works line B ${tag}`).press("Shift+F10");
  const kmenu = rowMenu(page, `Works line B ${tag}`);
  await kmenu.getByRole("menuitem", { name: "Isolate" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(sub.getByRole("menuitem", { name: "With 1 level open" })).toBeFocused();
  await page.keyboard.press("ArrowLeft"); // back to Isolate
  await expect(kmenu.getByRole("menuitem", { name: "Isolate" })).toBeFocused();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Enter"); // With 1 level open
  await expect(row(page, `Works line B ${tag}`)).toHaveAttribute("aria-expanded", "true");
  await expect(row(page, `Works pump B ${tag}`)).toBeVisible();
  await expect(row(page, `Works line A ${tag}`)).toHaveAttribute("aria-expanded", "false");
  await expect(row(page, `Works line B ${tag}`)).toBeFocused();
  expect(page.url()).toBe(url);
  await expectHealthy(page, problems, { label: "isolate", root: ".tx" });
});

test("the RCM tab: isolate a function; inside a pinned branch; the mouse menus have no moves, the keyboard's do", async ({ page, request, problems }) => {
  const tag = `r${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, `/asset-register/explorer?arrange=positions&tab=rcm&sel=${p.pumpA.id}&pin=${p.lineA.id}`);
  const table = page.getByRole("treegrid", { name: /and their RCM/ });
  const trow = (name) => table.getByRole("row", { name: new RegExp(name) });
  const fnRow = trow(`^Function: Pump water ${tag}`);
  await expect(fnRow).toBeVisible();
  const frame = { tree: await box(page.locator(".tp-scroll")), head: await box(page.locator(".tt-head")) };

  // The function's menu with the mouse: no Move to… / Move up / Move down.
  await fnRow.locator(".tt-tree").click({ button: "right" });
  const fmenu = rowMenu(page, `Function: Pump water ${tag}`);
  await expect(fmenu.getByRole("menuitem")).toHaveText(["Open…", "Add a performance standard…", "Add functional failure", "Edit description", "Isolate", "Delete function"]);
  await shot(page, "v2-3-rcm-function-menu-no-moves-1280");
  await page.keyboard.press("Escape");
  // Its ⋯: the same.
  await fnRow.hover();
  await fnRow.getByRole("button", { name: "Actions", exact: true }).click();
  await expect(fmenu.getByRole("menuitem", { name: /^Move/ })).toHaveCount(0);
  await page.keyboard.press("Escape");
  // A failure mode with the mouse: no Move to… nor Move a task…; a plain Isolate (nothing inside it).
  await trow(`Failure mode: Seal leaks ${tag}`).locator(".tt-tree").click({ button: "right" });
  await expect(page.getByRole("menu").getByRole("menuitem", { name: /^Move/ })).toHaveCount(0);
  await expect(page.getByRole("menu").getByRole("menuitem", { name: "Isolate", exact: true })).not.toHaveAttribute("aria-haspopup", "menu");
  await page.keyboard.press("Escape");
  // From the keyboard: the moves are there.
  await fnRow.locator(".tt-tree").click();
  await fnRow.press("Shift+F10");
  await expect(fmenu.getByRole("menuitem")).toHaveText(["Open…", "Add a performance standard…", "Add functional failure", "Edit description", "Move to another position…", "Move up", "Move down", "Isolate", "Delete function"]);
  await page.keyboard.press("Escape");

  // Isolate the function, 1 level: its failure shows, closed; line B closed, still on show; the pin stays.
  await isolate(page, fnRow.locator(".tt-tree"), "With 1 level open");
  await expect(trow(`^Functional failure: No flow ${tag}`)).toHaveAttribute("aria-expanded", "false");
  await expect(trow(`Failure mode: Seal leaks ${tag}`)).toHaveCount(0);
  await expect(trow(`^Works pump A ${tag}`)).toHaveAttribute("aria-expanded", "true"); // the way up stays open
  await expect(fnRow).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".tt-head").getByRole("group", { name: "Pinned branch" })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("pin")).toBe(p.lineA.id);
  // The tree's top and the header where they were (the details beside the table take its right side).
  const now = { tree: await box(page.locator(".tp-scroll")), head: await box(page.locator(".tt-head")) };
  expect([now.tree.x, now.tree.y, now.head.x, now.head.y]).toEqual([frame.tree.x, frame.tree.y, frame.head.x, frame.head.y]);
  await shot(page, "v2-4-rcm-function-isolated-1280");
  // 2 levels: the mode shows.
  await isolate(page, fnRow.locator(".tt-tree"), "With 2 levels open");
  await expect(trow(`Failure mode: Seal leaks ${tag}`)).toBeVisible();
  // Switching tabs moves nothing.
  await page.getByRole("tab", { name: "Summary" }).click();
  await expect(page.getByRole("tree", { name: "Positions" })).toBeVisible();
  expect((await box(page.locator(".tp-scroll"))).y).toBe(frame.tree.y);
  await page.getByRole("tab", { name: "RCM" }).click();
  await expect(table).toBeVisible();
  expect((await box(page.locator(".tp-scroll"))).y).toBe(frame.tree.y);
  await expectHealthy(page, problems, { label: "isolate on the RCM tab", root: ".tx" });
});

test("at 400 px: Isolate opens in place in the ⋯ menu; the rest closes; the RCM menus keep the moves; nothing scrolls sideways", async ({ page, request, problems }) => {
  const tag = `w${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.top.id}&pin=${p.top.id}`);
  const treeTop = (await page.locator(".tp-scroll").boundingBox()).y;
  await row(page, `Works line B ${tag}`).locator(".tp-chev").click();
  await expect(row(page, `Works pump B ${tag}`)).toBeVisible();
  await row(page, `Works line A ${tag}`).getByRole("button", { name: "Actions", exact: true }).click();
  const menu = rowMenu(page, `Works line A ${tag}`);
  await menu.getByRole("menuitem", { name: "Isolate" }).click();
  await expect(menu.getByRole("menuitem", { name: "Isolate" })).toHaveAttribute("aria-expanded", "true");
  const group = menu.getByRole("group", { name: "Isolate" });
  await expect(group.getByRole("menuitem")).toHaveText(["With 1 level open", "With 2 levels open", "With 3 levels open", "With everything open"]);
  const mb = await menu.boundingBox();
  expect(mb.x + mb.width).toBeLessThanOrEqual(400);
  await shot(page, "v2-5-phone-400px-isolate-menu");
  await group.getByRole("menuitem", { name: "With 2 levels open" }).click();
  await expect(row(page, `Works seal A ${tag}`)).toBeVisible();
  await expect(row(page, `Works line B ${tag}`)).toHaveAttribute("aria-expanded", "false");
  await expect(row(page, `Works pump B ${tag}`)).toHaveCount(0);
  expect((await page.locator(".tp-scroll").boundingBox()).y).toBe(treeTop);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await shot(page, "v2-6-phone-400px-isolated");
  // The RCM tab: the phone's menus keep the moves (no dragging here).
  await page.getByRole("tab", { name: "RCM" }).click();
  const fnRow = page.getByRole("row", { name: new RegExp(`^Function: Pump water ${tag}`) });
  await expect(fnRow).toBeVisible(); // its pump was opened 2 levels below the line
  await fnRow.getByRole("button", { name: "Actions", exact: true }).click();
  await expect(page.getByRole("menu").getByRole("menuitem", { name: "Move to another position…" })).toBeVisible();
  await expect(page.getByRole("menu").getByRole("menuitem", { name: "Move up" })).toBeVisible();
  await expect(page.getByRole("menu").getByRole("menuitem", { name: "Isolate" })).toBeVisible();
  await shot(page, "v2-7-phone-400px-rcm-menu-moves");
  await page.keyboard.press("Escape");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await expectHealthy(page, problems, { label: "isolate at 400 px", root: ".tx" });
});
