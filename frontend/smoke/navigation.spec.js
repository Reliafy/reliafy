// The menu: one flat list (Home · Assets · Maintenance · Modelling ·
// Decisions · Reports), three levels deep, and roles as a lens over it —
// switching roles in Settings, Home for each role and for a user with no data,
// the collapsed rail, the phone drawer, the keyboard, and no sideways scroll
// at phone width. The roles are the single user's, so these run in order and
// put them back to none (everything) at the end.
import { test, expect, open, expectHealthy } from "./health.js";

test.describe.configure({ mode: "serial" });

const EVERYTHING = ["Home", "Products", "Assets", "Items", "Maintenance", "Modelling", "Decisions", "Reports"];

const setRoles = async (request, roles) => {
  const res = await request.put("/api/me/roles", { data: { roles } });
  expect(res.ok(), `PUT /api/me/roles ${res.status()}`).toBeTruthy();
};

const mainMenu = (page) => page.locator('nav[aria-label="Main"]');
// The entries shown (not under More), by name: links, and the entries that
// open their list in place (buttons).
const shown = (page) => mainMenu(page).locator(":scope > .side-group .side-item")
  .evaluateAll((els) => els.map((e) => e.getAttribute("title")));
const moreButton = (page) => mainMenu(page).getByRole("button", { name: "More" });

let agentOn = false;
test.beforeAll(async ({ request }) => {
  agentOn = Boolean((await (await request.get("/api/config")).json()).reliability_agent);
});
test.afterAll(async ({ request }) => {
  await setRoles(request, []);
});

test("a new user is asked once what they do", async ({ page, problems }) => {
  await open(page, "/home");
  const offer = page.locator(".roles-offer");
  await expect(offer.getByRole("heading", { name: "What do you do?" })).toBeVisible();
  await expectHealthy(page, problems, { label: "home with the question" });
  await offer.getByRole("button", { name: "Not now" }).click();
  await expect(offer).toHaveCount(0);
  await open(page, "/home");
  await expect(page.locator(".roles-offer")).toHaveCount(0);
  // Settings keeps the picker.
  await open(page, "/settings");
  await expect(page.getByRole("heading", { name: "What do you do?" })).toBeVisible();
});

test("no roles: every entry in one flat list, nothing under More", async ({ page, request, problems }) => {
  await setRoles(request, []);
  await open(page, "/home");
  expect(await shown(page)).toEqual(agentOn ? [...EVERYTHING, "Reliability Agent"] : EVERYTHING);
  // No section headings.
  await expect(mainMenu(page).locator(".side-section")).toHaveCount(0);
  await expect(moreButton(page)).toHaveCount(0);
  // The logo goes Home.
  await open(page, "/data");
  await page.locator("a.brand").click();
  await expect(page).toHaveURL(/\/home$/);
  // A group opens its list in place (no page of its own); its entries are links,
  // or toggles of their own where they have sub-pages.
  // Modelling is still open from /data (what's open lasts the session); it closes and opens again in place.
  const modelling = mainMenu(page).getByRole("button", { name: "Modelling", exact: true });
  await expect(modelling).toHaveAttribute("aria-expanded", "true");
  await modelling.click();
  await expect(modelling).toHaveAttribute("aria-expanded", "false");
  await expect(mainMenu(page).locator(".side-children")).toHaveCount(0);
  await modelling.click();
  await expect(page).toHaveURL(/\/home$/);
  await expect(mainMenu(page).locator(":scope > .side-group > div > .side-children > div > .side-subitem"))
    .toHaveText(["Data", "Models", "Reliability prediction", "Maintainability prediction", "System models"]);
  await mainMenu(page).getByRole("link", { name: "Data", exact: true }).click();
  await expect(page).toHaveURL(/\/data$/);
  await expect(mainMenu(page).locator(".side-subitem.active")).toHaveText("Data");
  // An entry with sub-pages opens its children in place; its own landing page
  // (/models) isn't in the menu, but still works, and lights the entry.
  await mainMenu(page).getByRole("button", { name: "Models", exact: true }).click();
  await expect(page).toHaveURL(/\/data$/);
  await expect(mainMenu(page).locator(".side-grandchildren .side-subitem")).toHaveText(["Non-repairable",
    "Repairable", "Accelerated life", "Degradation", "Condition and life", "Library"]);
  await open(page, "/models");
  await expect(page.getByRole("heading", { name: "Models", level: 1 })).toBeVisible();
  await expect(mainMenu(page).getByRole("button", { name: "Models", exact: true })).toHaveAttribute("aria-expanded", "true");
  await expect(mainMenu(page).locator(".side-subitem.active")).toHaveText("Models");
  // A child page: the child lit, and its entry (never the group) named above the title.
  await mainMenu(page).getByRole("link", { name: "Repairable", exact: true }).click();
  await expect(page).toHaveURL(/\/models\/recurrent$/);
  await expect(mainMenu(page).locator(".side-subitem.active")).toHaveText("Repairable");
  await expect(page.locator(".crumb")).toHaveText("Models");
  // A detail page lights its child too, and names entry and child.
  await open(page, "/models/m/sample-model-bearings-weibull");
  await expect(mainMenu(page).locator(".side-subitem.active")).toHaveText("Non-repairable");
  await expect(page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link"))
    .toHaveText(["Models", "Non-repairable"]);
  // System models lists its RBDs first (where it opens on the collapsed rail),
  // named the same in the menu and on the page; a diagram lights RBDs too.
  await mainMenu(page).getByRole("button", { name: "System models", exact: true }).click();
  await expect(mainMenu(page).locator("#side-list-systems .side-subitem")).toHaveText(["RBDs", "Fault trees", "Simulation runs"]);
  await mainMenu(page).getByRole("link", { name: "RBDs", exact: true }).click();
  await expect(page).toHaveURL(/\/systems\/rbds$/);
  await expect(mainMenu(page).locator(".side-subitem.active")).toHaveText("RBDs");
  await expect(page.getByRole("heading", { name: "Reliability block diagrams (RBDs)", level: 1 })).toBeVisible();
  await mainMenu(page).getByRole("link", { name: "Simulation runs", exact: true }).click();
  await expect(page).toHaveURL(/\/systems\/runs$/);
  await mainMenu(page).getByRole("link", { name: "RBDs", exact: true }).click();
  await expect(page).toHaveURL(/\/systems\/rbds$/);
  await expect(page.getByRole("row").filter({ hasText: "Pump station" }).first()).toBeVisible();
  await open(page, "/systems/b/sample-rbd-pump-station");
  await expect(mainMenu(page).locator(".side-subitem.active")).toHaveText("RBDs");
  await expect(page.locator(".crumb")).toHaveText("RBDs");
  // The old addresses land on the list and on the working FME(C)A; fault trees are a page of their own now.
  await open(page, "/systems");
  await expect(page).toHaveURL(/\/systems\/rbds$/);
  await open(page, "/systems/fault-trees");
  await expect(page).toHaveURL(/\/systems\/fault-trees$/);
  await open(page, "/systems/fmeca");
  await expect(page).toHaveURL(/\/asset-register\/explorer\?tab=fmea(&|$)/);
  await expect(mainMenu(page).locator(".side-item.active")).toHaveText("Assets");
  // RCM studies are a page under Maintenance.
  await open(page, "/maintenance/rcm");
  await expect(mainMenu(page).locator(".side-subitem.active")).toHaveText("RCM studies");
  await expect(page.locator(".crumb")).toHaveText("Maintenance");
  // Assets is one entry, lit on every page of the register.
  await open(page, "/asset-register/explorer?tab=rcm");
  await expect(mainMenu(page).locator(".side-item.active")).toHaveText("Assets");
  await mainMenu(page).getByRole("link", { name: "Assets", exact: true }).click();
  await expect(page).toHaveURL(/\/asset-register$/);
  // No sub-pages: a plain link, never a toggle.
  await expect(mainMenu(page).getByRole("button", { name: "Assets", exact: true })).toHaveCount(0);
  // Its landing page has no links line: Parts and stock and Classes are tabs of the tree, hidden for now.
  await expect(page.getByRole("navigation", { name: "The asset register" })).toHaveCount(0);
  await expect(mainMenu(page).getByRole("link", { name: /^(Parts and stock|Classes)$/ })).toHaveCount(0);
  // Their old addresses land on the Explorer's Summary (no tab), still under Assets: nothing dead.
  for (const old of ["/asset-register/parts", "/asset-register/classes", "/systems/structure"]) {
    await open(page, old);
    await expect(page).toHaveURL(/\/asset-register\/explorer(\?|$)/);
    await expect(page).not.toHaveURL(/tab=(parts|classes)/);
    await expect(page.getByRole("tab", { name: "Parts and stock" })).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "Classes" })).toHaveCount(0);
    await expect(mainMenu(page).locator(".side-item.active")).toHaveText("Assets");
  }
  // A stale address that names one of the hidden tabs shows Summary too.
  await open(page, "/asset-register/explorer?tab=parts&scope=all");
  await expect(page.getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "true");
  // Decisions and Strategy open in place. Risk lists Condition monitoring; a
  // tracked fleet's page lights it and names it.
  await mainMenu(page).getByRole("button", { name: "Decisions", exact: true }).click();
  await mainMenu(page).getByRole("button", { name: "Strategy", exact: true }).click();
  await expect(mainMenu(page).locator("#side-list-strategy .side-subitem")).toHaveText(["Optimal replacement",
    "Compare two models", "Failure finding", "Test planning"]);
  await mainMenu(page).getByRole("link", { name: "Failure finding", exact: true }).click();
  await expect(page).toHaveURL(/\/strategy\/failure-finding$/);
  await mainMenu(page).getByRole("button", { name: "Risk", exact: true }).click();
  await mainMenu(page).getByRole("link", { name: "Condition monitoring", exact: true }).click();
  await expect(page).toHaveURL(/\/risk$/);
  await expect(page.getByRole("heading", { name: "Condition monitoring", level: 1 })).toBeVisible();
  await expect(mainMenu(page).locator(".side-subitem.active")).toHaveText("Condition monitoring");
  await open(page, "/risk/sample-tracked-trucks");
  await expect(mainMenu(page).locator(".side-subitem.active")).toHaveText("Condition monitoring");
  await expect(page.locator(".crumb")).toHaveText("Condition monitoring");
  // Degradation tracking's old address lands there.
  await open(page, "/models/tracking/sample-tracked-trucks");
  await expect(page).toHaveURL(/\/risk\/sample-tracked-trucks$/);
  await expectHealthy(page, problems, { label: "models" });
});

test("switching roles in Settings: technician, then every role, then none", async ({ page, problems }) => {
  await open(page, "/settings");
  const card = page.locator(".card", { has: page.getByRole("heading", { name: "What do you do?" }) });
  await card.getByRole("checkbox", { name: "Technician" }).check();
  await card.getByRole("button", { name: "Save" }).click();
  await expect(card.getByRole("status")).toHaveText("Saved.");

  // Home, Assets, Items and Maintenance (work orders); the rest one click away.
  expect(await shown(page)).toEqual(["Home", "Assets", "Items", "Maintenance"]);
  await expect(page.locator("#side-more")).toHaveCount(0);
  await moreButton(page).click();
  const more = page.locator("#side-more");
  await expect(more.getByRole("button", { name: "Modelling", exact: true })).toBeVisible();
  await expect(more.getByRole("button", { name: "Decisions", exact: true })).toBeVisible();
  // Maintenance has pages under it, so it opens its list in place: its own
  // page is the first of them, then RCM studies.
  const maintenance = mainMenu(page).getByRole("button", { name: "Maintenance", exact: true });
  await maintenance.click();
  await expect(maintenance).toHaveAttribute("aria-expanded", "true");
  await expect(mainMenu(page).getByRole("link", { name: "RCM studies", exact: true })).toBeVisible();
  await mainMenu(page).getByRole("link", { name: "Overview", exact: true }).click();
  await expect(page).toHaveURL(/\/maintenance$/);
  await expect(page.getByRole("heading", { name: "Open work orders" })).toBeVisible();
  await expect(mainMenu(page).locator(".side-subitem.active")).toHaveText("Overview");
  // A page under More keeps More open, with that page lit.
  await open(page, "/models");
  await expect(page.locator("#side-more").getByRole("button", { name: "Models", exact: true }))
    .toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("#side-more .side-subitem.active")).toHaveText("Models");

  // Home leads with today's work orders.
  await open(page, "/home");
  await expect(page.locator(".home-slot h2").first()).toHaveText("Today's work orders");
  await expectHealthy(page, problems, { label: "technician home" });

  // Every role: everything shown, nothing under More.
  await open(page, "/settings");
  for (const box of await card.getByRole("checkbox").all()) await box.check();
  await card.getByRole("button", { name: "Save" }).click();
  await expect(card.getByRole("status")).toHaveText("Saved.");
  expect(new Set(await shown(page))).toEqual(new Set(agentOn ? [...EVERYTHING, "Reliability Agent"] : EVERYTHING));
  await expect(moreButton(page)).toHaveCount(0);

  // "Show everything" clears them.
  await card.getByRole("button", { name: "Show everything" }).click();
  await expect(card.getByRole("checkbox", { checked: true })).toHaveCount(0);
  await expectHealthy(page, problems, { label: "settings" });
});

const LEADS = {
  analyst: "Your recent models",
  design: "Your recent RBDs",
  planner: "Due and at risk",
  technician: "Today's work orders",
  fleet: "Your fleets",
  logistics: "Critical spares short",
  manager: "Targets and what's waiting",
};

for (const [role, heading] of Object.entries(LEADS)) {
  test(`Home leads with the ${role}'s cards`, async ({ page, request, problems }) => {
    await setRoles(request, [role]);
    await open(page, "/home");
    await expect(page.locator(".home-slot h2").first()).toHaveText(heading);
    await expectHealthy(page, problems, { label: `${role} home` });
  });
}

// Every list Home reads, empty: a workspace with nothing in it.
const EMPTY = {
  "/api/models": { models: [] },
  "/api/joint/models": { models: [] },
  "/api/fleet/fleets": { fleets: [] },
  "/api/fleet/tracked": { fleets: [] },
  "/api/degradation/models": { models: [] },
  "/api/alt/models": { models: [] },
  "/api/recurrent/models": { models: [] },
  "/api/datasets": { datasets: [] },
  "/api/rbds": { rbds: [] },
  "/api/strategy/analyses": { analyses: [] },
  "/api/maintenance/overview": {
    summary: { positions: 0, items: 0, tasks: 0 }, time_zone: null, today: "2026-10-16", tree: [], due: [],
    open_work_orders: [], proposals: [], critical_spares: [],
  },
};

test("Home for a user with no data, every role's cards", async ({ page, request, problems }) => {
  await setRoles(request, Object.keys(LEADS));
  await page.route((url) => url.pathname in EMPTY, (route) =>
    route.request().method() === "GET" ? route.fulfill({ json: EMPTY[new URL(route.request().url()).pathname] }) : route.continue());
  await open(page, "/home");
  for (const text of [
    "No models of your own yet.", "No datasets of your own yet.", "No block diagrams of your own yet.",
    "Nothing due in the next 30 days.", "No open work orders.", "Every critical spare is stocked.",
    "No fleets of your own yet.",
  ]) {
    await expect(page.getByText(text)).toBeVisible();
  }
  await expect(page.getByRole("heading", { name: "Targets and what's waiting" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Start here" })).toBeVisible();
  await expect(page.locator(".first-run").getByRole("link", { name: "Test planning" })).toHaveAttribute("href", "/strategy/test-planning");
  await expectHealthy(page, problems, { label: "empty home" });
});

test("the collapsed menu and the keyboard", async ({ page, request, problems }) => {
  await setRoles(request, ["technician"]);
  await open(page, "/home");
  await page.getByRole("button", { name: "Hide the menu" }).click();
  await expect(mainMenu(page).locator(".side-label")).toHaveCount(0);
  // Icons only, each named; no headings and nothing below an entry.
  expect(await shown(page)).toEqual(["Home", "Assets", "Items", "Maintenance"]);
  await expect(mainMenu(page).locator(".side-section, .side-children")).toHaveCount(0);
  await moreButton(page).click();
  await expect(page.locator("#side-more").getByRole("link", { name: "Decisions" })).toBeVisible();
  // A group's page lights the group on the rail.
  await page.locator("#side-more").getByRole("link", { name: "Decisions" }).click();
  await expect(page).toHaveURL(/\/strategy$/);
  await expect(page.locator("#side-more .side-item.active")).toHaveAttribute("title", "Decisions");

  // Keyboard: Tab from Home reaches Assets, then Items, then Maintenance; Enter opens it.
  await mainMenu(page).getByRole("link", { name: "Home" }).focus();
  await page.keyboard.press("Tab");
  await expect(mainMenu(page).getByRole("link", { name: "Assets" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(mainMenu(page).getByRole("link", { name: "Items" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(mainMenu(page).getByRole("link", { name: "Maintenance" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/maintenance$/);
  // More opens and closes from the keyboard.
  await moreButton(page).focus();
  await page.keyboard.press("Enter");
  await expect(moreButton(page)).toHaveAttribute("aria-expanded", "false");
  await page.keyboard.press("Space");
  await expect(moreButton(page)).toHaveAttribute("aria-expanded", "true");

  await page.getByRole("button", { name: "Show the menu" }).click();
  await expect(mainMenu(page).locator(".side-label").first()).toBeVisible();
  await expectHealthy(page, problems, { label: "collapsed menu" });
});

// Home → Models › Repairable: open Modelling and Models in place (the URL and,
// on a phone, the drawer stay), then the leaf navigates.
for (const [width, phone] of [[400, true], [1440, false]]) {
  test(`menu entries open in place at ${width} px`, async ({ page, request, problems }) => {
    await setRoles(request, []);
    await page.setViewportSize({ width, height: 860 });
    await open(page, "/home");
    let menu = mainMenu(page);
    if (phone) {
      await page.getByRole("button", { name: "Menu", exact: true }).click();
      menu = page.getByRole("dialog", { name: "Menu" });
    }
    const modelling = menu.getByRole("button", { name: "Modelling", exact: true });
    await expect(modelling).toHaveAttribute("aria-expanded", "false");
    await expect(menu.getByRole("link", { name: "Data", exact: true })).toHaveCount(0);
    await modelling.click();
    await expect(modelling).toHaveAttribute("aria-expanded", "true");
    await expect(page).toHaveURL(/\/home$/);
    if (phone) await expect(menu).toBeVisible();
    for (const name of ["Data", "Reliability prediction", "Maintainability prediction"]) {
      await expect(menu.getByRole("link", { name, exact: true })).toBeVisible();
    }
    // Decisions stays closed: opening one doesn't open (or close) another.
    await expect(menu.getByRole("button", { name: "Decisions", exact: true })).toHaveAttribute("aria-expanded", "false");
    const models = menu.getByRole("button", { name: "Models", exact: true });
    await models.click();
    await expect(models).toHaveAttribute("aria-expanded", "true");
    await expect(page).toHaveURL(/\/home$/);
    for (const name of ["Non-repairable", "Repairable", "Condition and life"]) {
      await expect(menu.getByRole("link", { name, exact: true })).toBeVisible();
    }
    await menu.getByRole("link", { name: "Repairable", exact: true }).click();
    await expect(page).toHaveURL(/\/models\/recurrent$/);
    if (phone) await expect(page.getByRole("dialog", { name: "Menu" })).toHaveCount(0);
    else await expect(mainMenu(page).locator(".side-subitem.active")).toHaveText("Repairable");
    // Keyboard: Enter and Space toggle a list.
    if (!phone) {
      const decisions = mainMenu(page).getByRole("button", { name: "Decisions", exact: true });
      await decisions.focus();
      await page.keyboard.press("Enter");
      await expect(decisions).toHaveAttribute("aria-expanded", "true");
      await page.keyboard.press("Space");
      await expect(decisions).toHaveAttribute("aria-expanded", "false");
      // What's open survives a reload in the same session.
      await models.click();
      await expect(models).toHaveAttribute("aria-expanded", "false");
      await page.reload();
      await expect(mainMenu(page).getByRole("button", { name: "Modelling", exact: true })).toHaveAttribute("aria-expanded", "true");
    }
    await expectHealthy(page, problems, { label: `menu at ${width} px` });
  });
}

const PHONE_PAGES = [
  "/home", "/systems/rbds", "/asset-register", "/asset-register/explorer?arrange=positions", "/asset-register/explorer?arrange=locations",
  "/items", "/asset-register/explorer?tab=rcm", "/asset-register/parts",
  "/asset-register/classes", "/products", "/maintenance", "/maintenance/rcm", "/data",
  "/models", "/models/recurrent", "/strategy", "/risk", "/forecasts", "/reports", "/settings",
];

test("the phone drawer, and no sideways scroll at 400 px", async ({ page, request, problems }) => {
  await setRoles(request, ["planner"]);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, "/home");
  const menuButton = page.getByRole("button", { name: "Menu", exact: true });
  await menuButton.click();
  const drawer = page.getByRole("dialog", { name: "Menu" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("button", { name: "Close menu" })).toBeFocused();
  await expect(drawer.getByRole("link", { name: "Assets", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(menuButton).toBeFocused();

  // A link in the drawer opens its page and closes the drawer; More and the
  // entries that open in place stay inside it.
  await menuButton.click();
  await drawer.getByRole("button", { name: "More" }).click();
  await expect(drawer).toBeVisible();
  await drawer.locator("#side-more").getByRole("button", { name: "Modelling" }).click();
  await expect(drawer).toBeVisible();
  await expect(page).toHaveURL(/\/home$/);
  await drawer.getByRole("link", { name: "Data", exact: true }).click();
  await expect(page).toHaveURL(/\/data$/);
  await expect(drawer).toHaveCount(0);
  // Three levels in the drawer: the group's entries, then the current entry's children.
  await open(page, "/models/recurrent");
  await menuButton.click();
  await expect(drawer.locator(".side-subitem.active")).toHaveText("Repairable");
  await expect(drawer.getByRole("button", { name: "System models", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");

  for (const path of PHONE_PAGES) {
    await open(page, path);
    const [scroll, width] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    expect(scroll, `${path} scrolls sideways at 400 px`).toBeLessThanOrEqual(width);
  }
  await expectHealthy(page, problems, { label: "phone" });
});

test("Skip to content is the first Tab stop and moves focus to the page", async ({ page }) => {
  await open(page, "/home");
  await page.locator("body").focus();
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to content" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();
  await expect(page).toHaveURL(/\/home$/);
});
