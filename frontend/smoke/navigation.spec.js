// The menu: Design · Operate · Analyse, and roles as a lens over it —
// switching roles in Settings, Home for each role and for a user with no data,
// the collapsed rail, the phone drawer, the keyboard, and no sideways scroll
// at phone width. The roles are the single user's, so these run in order and
// put them back to none (everything) at the end.
import { test, expect, open, expectHealthy } from "./health.js";

test.describe.configure({ mode: "serial" });

const EVERYTHING = ["Home", "Systems", "Assets", "Maintenance", "Data", "Model", "Strategy", "Forecasts", "Reports"];

const setRoles = async (request, roles) => {
  const res = await request.put("/api/me/roles", { data: { roles } });
  expect(res.ok(), `PUT /api/me/roles ${res.status()}`).toBeTruthy();
};

const mainMenu = (page) => page.locator('nav[aria-label="Main"]');
// The entries shown (not under More), by name.
const shown = (page) => mainMenu(page).locator(":scope > .side-group a.side-item")
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

test("no roles: every entry under Design, Operate and Analyse, nothing under More", async ({ page, request, problems }) => {
  await setRoles(request, []);
  await open(page, "/home");
  expect(await shown(page)).toEqual(agentOn ? [...EVERYTHING, "Reliability Agent"] : EVERYTHING);
  for (const heading of ["Design", "Operate", "Analyse"]) {
    await expect(mainMenu(page).getByRole("group", { name: heading })).toBeVisible();
  }
  await expect(moreButton(page)).toHaveCount(0);
  // The logo goes Home.
  await open(page, "/data");
  await page.locator("a.brand").click();
  await expect(page).toHaveURL(/\/home$/);
  // A section shows its pages while it's open; the landing page isn't one of them.
  await mainMenu(page).getByRole("link", { name: "Model", exact: true }).click();
  await expect(page).toHaveURL(/\/models$/);
  const kids = mainMenu(page).locator(".side-children .side-subitem");
  await expect(kids).toHaveText(["Non-repairable", "Repairable", "Accelerated life", "Degradation",
    "Condition monitoring", "Degradation tracking"]);
  await expect(mainMenu(page).getByRole("link", { name: "Model", exact: true })).toHaveAttribute("aria-current", "page");
  // A child page: the child lit, and its entry named above the title.
  await mainMenu(page).getByRole("link", { name: "Repairable", exact: true }).click();
  await expect(page).toHaveURL(/\/models\/recurrent$/);
  await expect(mainMenu(page).locator(".side-subitem.active")).toHaveText("Repairable");
  await expect(page.locator(".crumb")).toHaveText("Model");
  // A detail page lights its child too.
  await open(page, "/models/m/sample-model-bearings-weibull");
  await expect(mainMenu(page).locator(".side-subitem.active")).toHaveText("Non-repairable");
  // Operate: Maintenance (due and work orders), with RCM studies under it.
  await open(page, "/maintenance/rcm");
  await expect(mainMenu(page).locator(".side-subitem.active")).toHaveText("RCM studies");
  await expect(page.locator(".crumb")).toHaveText("Maintenance");
  await expectHealthy(page, problems, { label: "models" });
});

test("switching roles in Settings: technician, then every role, then none", async ({ page, problems }) => {
  await open(page, "/settings");
  const card = page.locator(".card", { has: page.getByRole("heading", { name: "What do you do?" }) });
  await card.getByRole("checkbox", { name: "Technician" }).check();
  await card.getByRole("button", { name: "Save" }).click();
  await expect(card.getByRole("status")).toHaveText("Saved.");

  // Home, Maintenance (work orders) and Assets; the rest one click away.
  expect(await shown(page)).toEqual(["Home", "Maintenance", "Assets"]);
  await expect(page.locator("#side-more")).toHaveCount(0);
  await moreButton(page).click();
  const more = page.locator("#side-more");
  await expect(more.getByRole("link", { name: "Systems" })).toBeVisible();
  await expect(more.getByRole("link", { name: "Model", exact: true })).toBeVisible();
  await mainMenu(page).getByRole("link", { name: "Maintenance" }).click();
  await expect(page).toHaveURL(/\/maintenance$/);
  await expect(page.getByRole("heading", { name: "Open work orders" })).toBeVisible();
  // A page under More keeps More open, with that page lit.
  await open(page, "/models");
  await expect(page.locator("#side-more").getByRole("link", { name: "Model", exact: true })).toBeVisible();
  await expect(page.locator("#side-more .side-item.active")).toHaveText("Model");

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
  design: "Your recent systems",
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
  "/api/rcm/studies": { studies: [] },
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
  await expectHealthy(page, problems, { label: "empty home" });
});

test("the collapsed menu and the keyboard", async ({ page, request, problems }) => {
  await setRoles(request, ["technician"]);
  await open(page, "/home");
  await page.getByRole("button", { name: "Collapse menu" }).click();
  await expect(mainMenu(page).locator(".side-label")).toHaveCount(0);
  // Icons only, each named; headings become hairlines, still named groups.
  expect(await shown(page)).toEqual(["Home", "Maintenance", "Assets"]);
  await expect(mainMenu(page).getByRole("group", { name: "Operate" })).toBeVisible();
  await moreButton(page).click();
  await expect(page.locator("#side-more").getByRole("link", { name: "Forecasts" })).toBeVisible();

  // Keyboard: Tab from Home reaches Maintenance; Enter opens it.
  await mainMenu(page).getByRole("link", { name: "Home" }).focus();
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

  await page.getByRole("button", { name: "Expand menu" }).click();
  await expect(mainMenu(page).locator(".side-label").first()).toBeVisible();
  await expectHealthy(page, problems, { label: "collapsed menu" });
});

const PHONE_PAGES = [
  "/home", "/systems", "/asset-register", "/asset-register/parts", "/maintenance", "/maintenance/rcm", "/data",
  "/models", "/strategy", "/forecasts", "/reports", "/settings",
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
  await expect(drawer.getByRole("group", { name: "Operate" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(menuButton).toBeFocused();

  // A link in the drawer opens its page and closes the drawer; More stays inside it.
  await menuButton.click();
  await drawer.getByRole("button", { name: "More" }).click();
  await expect(drawer).toBeVisible();
  await drawer.locator("#side-more").getByRole("link", { name: "Systems" }).click();
  await expect(page).toHaveURL(/\/systems$/);
  await expect(drawer).toHaveCount(0);

  for (const path of PHONE_PAGES) {
    await open(page, path);
    const [scroll, width] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    expect(scroll, `${path} scrolls sideways at 400 px`).toBeLessThanOrEqual(width);
  }
  await expectHealthy(page, problems, { label: "phone" });
});
