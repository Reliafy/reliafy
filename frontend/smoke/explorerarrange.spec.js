// The Explorer's arrangement switch (Positions, Locations, Classes) works from any state: on a
// tab whose tree is by positions it is locked and says why; everywhere else a click on Positions
// or Locations changes the tree and the address. The Maintenance tab once forced the positions
// tree with the switch still live, so clicking Locations there changed nothing.
// Each test makes its own small plant through the API.
import { test, expect, open, postOk } from "./health.js";
import { pickTab } from "./explorer.js";

const M = "/api/maintenance";

async function plant(request, tag) {
  const site = await postOk(request, `${M}/locations`, { name: `Arrange site ${tag}` });
  const bay = await postOk(request, `${M}/locations`, { name: `Arrange bay ${tag}`, parent_id: site.id });
  const top = await postOk(request, `${M}/positions`, { name: `Arrange plant ${tag}`, location_id: site.id });
  const line = await postOk(request, `${M}/positions`, { name: `Arrange line ${tag}`, parent_id: top.id });
  await postOk(request, `${M}/positions`, { name: `Arrange pump ${tag}`, parent_id: line.id, location_id: bay.id });
  return { site, bay, top, line };
}

const arrange = (page) => page.locator(".tp-arrange");
const query = (page) => new URL(page.url()).searchParams;

// Click `want` on the switch: the address and the switch both say it, and the tree's top row is
// that arrangement's (a place for Locations, a position for Positions).
async function switchTo(page, want, p) {
  await arrange(page).locator(`[data-value=${want}]`).click();
  await expect.poll(() => query(page).get("arrange")).toBe(want);
  await expect(arrange(page).locator(`[data-value=${want}]`)).toHaveAttribute("aria-checked", "true");
  const first = page.locator(".tp-body [role=treeitem]").first();
  await expect(first).toContainText(want === "locations" ? p.site.name : p.top.name);
}

// Whatever the state, the switch either works both ways or is locked on Positions, saying why.
async function expectSwitchWorks(page, p, label) {
  if (!(await arrange(page).count())) return; // not on the Explorer (Back past it)
  if ((await arrange(page).getAttribute("aria-disabled")) === "true") {
    await expect(arrange(page).locator("[data-value=positions]"), label).toHaveAttribute("aria-checked", "true");
    await expect(arrange(page), label).toHaveAttribute("title", /positions tree$/);
    return;
  }
  const on = await arrange(page).locator("[aria-checked=true]").getAttribute("data-value");
  for (const want of on === "locations" ? ["positions", "locations"] : ["locations", "positions"]) {
    await test.step(`${label}: ${want}`, () => switchTo(page, want, p));
  }
}

test("on the Maintenance tab the switch is locked on Positions and says why; back on Summary it works", async ({ page, request, problems }) => {
  const tag = `a${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?root=${p.site.id}`);
  await switchTo(page, "locations", p);
  await pickTab(page, "Maintenance");
  await expect(arrange(page)).toHaveAttribute("aria-disabled", "true");
  await expect(arrange(page)).toHaveAttribute("title", /^Tasks hang under their positions/);
  await expect(arrange(page).locator("[data-value=positions]")).toHaveAttribute("aria-checked", "true");
  // A click on Locations is refused, and the address keeps saying Positions.
  // (`force`: a button marked aria-disabled is one Playwright would otherwise wait on.)
  await arrange(page).locator("[data-value=locations]").click({ force: true });
  await expect.poll(() => query(page).get("arrange")).toBe("positions");
  await pickTab(page, "Summary");
  await switchTo(page, "locations", p);
  await switchTo(page, "positions", p);
  expect(problems).toEqual([]);
});

// A short walk with a fixed seed: tabs, arrangements, row clicks, double-clicks (details across
// the table), Escape, Back and Forward; after every step the switch still works.
test("a seeded walk through tabs, arrangements and rows never leaves the switch stuck", async ({ page, request, problems }) => {
  const tag = `w${Date.now()}`;
  const p = await plant(request, tag);
  let s = 20261123;
  const rnd = () => (s = (s * 1103515245 + 12345) % 2147483648) / 2147483648;
  const pick = (a) => a[Math.floor(rnd() * a.length)];
  const tabs = ["Summary", "Operations", "Maintenance", "RCM", "FME(C)A", "Models", "Missions", "History"];
  await open(page, `/asset-register/explorer?root=${p.site.id}`);
  for (let i = 0; i < 14; i += 1) {
    const kind = pick(["tab", "tab", "arrange", "row", "dbl", "esc", "back"]);
    const rows = page.locator(".tp-body [role=treeitem]");
    let label = kind;
    if (kind === "tab") {
      const name = pick(tabs);
      label = `tab ${name}`;
      if (await page.getByRole("tab", { name, exact: true }).isVisible()) await page.getByRole("tab", { name, exact: true }).click();
    } else if (kind === "arrange") {
      const v = pick(["positions", "locations", "classes"]);
      label = `arrange ${v}`;
      const b = arrange(page).locator(`[data-value=${v}]`);
      if (await b.count()) await b.click({ force: true });
    } else if ((kind === "row" || kind === "dbl") && (await rows.count())) {
      const r = rows.nth(Math.floor(rnd() * Math.min(await rows.count(), 5))).locator(".tp-nm").first();
      // A row under the details across the table (a double-click's) can't be clicked: a no-op.
      if (kind === "row") await r.click({ timeout: 3_000 }).catch(() => {});
      else await r.dblclick({ timeout: 3_000 }).catch(() => {});
    } else if (kind === "esc") await page.keyboard.press("Escape");
    else if (kind === "back" && i > 0) {
      await page.goBack();
      if (!(await arrange(page).count())) await page.goForward();
    }
    await page.waitForTimeout(200);
    await expectSwitchWorks(page, p, `step ${i} (${label})`);
  }
  expect(problems).toEqual([]);
});
