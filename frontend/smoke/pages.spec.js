// Every page of the signed-in app opens and draws (auth-disabled build): one
// test per route in AppShell.jsx, and for a route with an id, every sample or
// seeded record it has (smoke/routes.js says where the ids come from).
import { test, expect, open, expectHealthy } from "./health.js";
import {
  appRoutes, hasParam, fill, idSource, landing, MAX_IDS, REDIRECTS_WITH_QUERY, expectsChart,
} from "./routes.js";
import { RBDS_LABEL, RBDS_PATH } from "../src/navigation.js";

let appConfig;
test.beforeAll(async ({ request }) => {
  appConfig = await (await request.get("/api/config")).json();
});

// The pages (and, for an earlier address, where it lands). A route with an id
// opens with every sample or seeded record it has.
for (const route of appRoutes()) {
  test(route.path, async ({ page, request, problems }) => {
    test.skip(Boolean(route.flag && !appConfig[route.flag]), `/api/config has ${route.flag} off`);
    // An earlier address of a Reliafy Maintenance page lands on a page that's off.
    test.skip(Boolean(route.target?.startsWith("/asset-register") && !appConfig.maintenance),
      "/api/config has maintenance off");
    let records = [{}];
    if (hasParam(route.path)) {
      const source = idSource(route);
      expect(source, `No id source for ${route.path}: add one to DETAIL_IDS in smoke/routes.js`).toBeTruthy();
      const [api, read] = source;
      records = read(api ? await (await request.get(api)).json() : {}).slice(0, MAX_IDS);
      expect(records.length, `${api} has no record to open ${route.path} with`).toBeGreaterThan(0);
    }
    for (const record of records) {
      const path = record.id ? fill(route.path, record.id) : route.path;
      await test.step(path, async () => {
        problems.length = 0;
        await open(page, path);
        if (route.redirect && route.target) {
          // An earlier address: on its new page, with its id.
          const want = landing(route, record.id);
          await expect.poll(() => new URL(page.url()).pathname, { message: `${path} → ${want}` }).toBe(want);
        } else if (!route.redirect) {
          // Not bounced elsewhere (the shell sends an unknown route to /home).
          expect(new URL(page.url()).pathname, `${path} redirected`).toBe(path);
        }
        await expectHealthy(page, problems, {
          label: path,
          root: route.root,
          chart: !route.redirect && expectsChart(route.path, record),
        });
        // Its own tab title ("RBDs · Reliafy"), not the app's generic one.
        if (!route.root && !route.redirect) {
          await expect.poll(() => page.title(), { message: `${path} tab title` }).toMatch(/\S · Reliafy$/);
        }
      });
    }
  });
}

test("tab titles: a record's page leads with its name", async ({ page, request }) => {
  const { rbds } = await (await request.get("/api/rbds")).json();
  const rbd = rbds.find((r) => r.name) || rbds[0];
  await open(page, RBDS_PATH);
  await expect.poll(() => page.title()).toBe(`${RBDS_LABEL} · Reliafy`);
  await open(page, `/systems/b/${encodeURIComponent(rbd.id)}`);
  const name = rbd.name.replace(/\s*\(sample\)\s*$/i, "");
  await expect.poll(() => page.title()).toBe(`${name} · ${RBDS_LABEL} · Reliafy`);
});

test("earlier addresses keep their query and #hash", async ({ page, problems }) => {
  for (const [from, to] of REDIRECTS_WITH_QUERY) {
    await test.step(`${from} → ${to}`, async () => {
      problems.length = 0;
      await open(page, from);
      await expect.poll(() => {
        const u = new URL(page.url());
        // The Explorer fills in its own view state once open (?arrange=, ?sel=); the move's query is what's checked.
        if (u.pathname === "/asset-register/explorer") {
          for (const k of ["arrange", "sel"]) if (!to.includes(`${k}=`)) u.searchParams.delete(k);
        }
        return u.pathname + u.search + u.hash;
      }).toBe(to);
      await expectHealthy(page, problems, { label: from });
    });
  }
});

// Every list row's name is a real link to its page, so it opens in a new tab,
// middle-clicks and copies (not only a row click handler).
const LIST_LINKS = [
  ["/models", /^\/models\/(m|recurrent|alt|degradation|joint)\/[^/]+$/],
  ["/data", /^\/data\/[^/]+$/],
  ["/models/life", /^\/models\/m\/[^/]+$/],
  ["/models/recurrent", /^\/models\/recurrent\/[^/]+$/],
  ["/models/alt", /^\/models\/alt\/[^/]+$/],
  ["/models/degradation", /^\/models\/degradation\/[^/]+$/],
  ["/models/joint", /^\/models\/joint\/[^/]+$/],
  ["/systems/rbds", /^\/systems\/b\/[^/]+$/],
  ["/systems/runs", /^\/systems\/runs\/[^/]+$/],
  ["/strategy", /^\/strategy\/analyses\/[^/]+$/],
  // Forecasts also lists the position classes (Reliafy Maintenance on).
  ["/forecasts", /^\/forecasts\/[^/]+$|^\/asset-register\/classes\/[^/]+$/],
  ["/risk", /^\/risk\/[^/]+$/],
  ["/asset-register/classes", /^\/asset-register\/classes\/[^/]+$/],
];

test("list rows link to their pages", async ({ page }) => {
  for (const [path, pattern] of LIST_LINKS) {
    await test.step(path, async () => {
      if (path.startsWith("/asset-register") && !appConfig.maintenance) return;
      await open(page, path);
      const rows = page.locator("tr.lib-row");
      const n = await rows.count();
      for (let i = 0; i < n; i++) {
        const href = await rows.nth(i).locator("a.lib-link").first().getAttribute("href");
        expect(href, `${path}: row ${i + 1} has no link`).toBeTruthy();
        expect(href, `${path}: row ${i + 1} links to ${href}`).toMatch(pattern);
      }
    });
  }
});
