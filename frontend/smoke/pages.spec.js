// Every page of the signed-in app opens and draws (auth-disabled build): one
// test per route in AppShell.jsx, and for a route with an id, every sample or
// seeded record it has (smoke/routes.js says where the ids come from).
import { test, expect, open, expectHealthy } from "./health.js";
import { appRoutes, hasParam, fill, DETAIL_IDS, MAX_IDS, expectsChart } from "./routes.js";

let appConfig;
test.beforeAll(async ({ request }) => {
  appConfig = await (await request.get("/api/config")).json();
});

for (const route of appRoutes()) {
  test(route.path, async ({ page, request, problems }) => {
    test.skip(Boolean(route.flag && !appConfig[route.flag]), `/api/config has ${route.flag} off`);
    let records = [{}];
    if (hasParam(route.path)) {
      const source = DETAIL_IDS[route.path];
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
        // Not bounced elsewhere (the shell sends an unknown route to /modelling).
        if (!route.redirect) expect(new URL(page.url()).pathname, `${path} redirected`).toBe(path);
        await expectHealthy(page, problems, {
          label: path,
          root: route.root,
          chart: expectsChart(route.path, record),
        });
      });
    }
  });
}
