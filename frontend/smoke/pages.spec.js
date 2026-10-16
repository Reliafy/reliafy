// Every page of the signed-in app opens and draws (auth-disabled build): one
// test per route in AppShell.jsx, and for a route with an id, every sample or
// seeded record it has (smoke/routes.js says where the ids come from). Every
// earlier address (#438) lands on its page's new place, with the same id.
import { test, expect, open, expectHealthy } from "./health.js";
import { appRoutes, hasParam, fill, idSource, MAX_IDS, expectsChart } from "./routes.js";

let appConfig;
test.beforeAll(async ({ request }) => {
  appConfig = await (await request.get("/api/config")).json();
});

for (const route of appRoutes()) {
  test(route.path, async ({ page, request, problems }) => {
    test.skip(Boolean(route.flag && !appConfig[route.flag]), `/api/config has ${route.flag} off`);
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
        const landed = new URL(page.url()).pathname;
        // Not bounced elsewhere (the shell sends an unknown route to /home);
        // a redirect lands where it says, with the same id.
        if (!route.redirect) expect(landed, `${path} redirected`).toBe(path);
        else if (route.target) {
          const want = hasParam(route.target) ? fill(route.target, record.id) : route.target;
          expect(landed, `${path} should land on ${want}`).toBe(want);
        }
        await expectHealthy(page, problems, {
          label: path,
          root: route.root,
          chart: expectsChart(route.redirect && route.target ? route.target : route.path, record),
        });
      });
    }
  });
}
