// Every page of the signed-in app opens and draws (auth-disabled build): one
// test per route in AppShell.jsx, and for a route with an id, every sample or
// seeded record it has (smoke/routes.js says where the ids come from).
import { test, expect, open, expectHealthy } from "./health.js";
import {
  appRoutes, hasParam, fill, idSource, landing, MAX_IDS, REDIRECTS_WITH_QUERY, expectsChart,
} from "./routes.js";

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
      });
    }
  });
}

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
