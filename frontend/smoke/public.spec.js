// A deployed site, signed out and read-only (SMOKE_BASE_URL): every public
// route in App.jsx opens and draws (for a route with a slug, the first page
// of that kind in the site's sitemap.xml), and the app itself asks for sign-in.
import { test, expect, open, expectHealthy } from "./health.js";
import { publicRoutes, hasParam, fill } from "./routes.js";

// Routes with their own test below.
const OWN_TEST = new Set(["/p/:token", "/login", "/unsubscribe"]);

let sitemap = [];
test.beforeAll(async ({ request }) => {
  const res = await request.get("/sitemap.xml");
  expect(res.ok(), "/sitemap.xml").toBeTruthy();
  sitemap = [...(await res.text()).matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => new URL(m[1]).pathname);
});

// The first sitemap page a route with a parameter matches.
const pageFor = (route) => {
  const re = new RegExp(`^${route.replace(/:\w+/g, "[^/]+")}$`);
  return sitemap.find((p) => re.test(p));
};

for (const route of publicRoutes().filter((r) => !OWN_TEST.has(r.path))) {
  test(route.path, async ({ page, problems }) => {
    const path = hasParam(route.path) ? pageFor(route.path) : route.path;
    expect(path, `no page in sitemap.xml for ${route.path}`).toBeTruthy();
    const res = await open(page, path);
    expect(res.status(), path).toBeLessThan(400);
    if (!route.redirect) expect(new URL(page.url()).pathname, `${path} redirected`).toBe(path);
    await expectHealthy(page, problems, { label: path, root: "#root" });
  });
}

test("the app asks for sign-in", async ({ page, problems }) => {
  for (const path of ["/modelling", "/rbds/b/sample-rbd-pump-station", "/maintenance"]) {
    await open(page, path);
    await expect(page, `${path} without signing in`).toHaveURL(/\/login$/);
  }
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByLabel("Email")).toBeVisible();
  await expect(page.getByLabel("Password")).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue with Google" })).toBeVisible();
  // The page asks the API who's signed in and is told 401: expected here.
  const unexpected = problems.filter((p) => !/status of 401\b/.test(p));
  expect(unexpected).toEqual([]);
});

test("a share link that doesn't exist says so", async ({ page, problems }) => {
  const res = await open(page, fill("/p/:token", "not-a-real-link-smoke"));
  expect(res.status()).toBe(404);
  await expect(page.getByText("Link unavailable")).toBeVisible();
  // The page and its API lookup both answer 404, which the browser logs.
  expect(problems.filter((p) => !/status of 404\b/.test(p))).toEqual([]);
});

test("a live share link opens", async ({ page, problems }) => {
  // Optional: SMOKE_SHARE_TOKEN names a public share link that should stay up.
  const token = process.env.SMOKE_SHARE_TOKEN;
  test.skip(!token, "set SMOKE_SHARE_TOKEN to check a real share link");
  await open(page, fill("/p/:token", token));
  await expectHealthy(page, problems, { label: "/p/<token>", root: "#root" });
});

test("unsubscribe without a token", async ({ page, problems }) => {
  await open(page, "/unsubscribe");
  await expectHealthy(page, problems, { label: "/unsubscribe", root: "#root" });
});
