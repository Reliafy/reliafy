// Browser smoke tests (#123): does every page open and draw? Run with
// `npm run smoke` (CONTRIBUTING.md, "Browser smoke tests"):
//
// - locally / in CI: against an auth-disabled build served by a local
//   backend (smoke/serve.mjs, started here) with the samples seeded;
// - with SMOKE_BASE_URL set: against a deployed site, read-only — the public
//   pages, the sign-in gate and the API's routes, nothing signed in.
import { defineConfig, devices } from "@playwright/test";

const deployed = process.env.SMOKE_BASE_URL?.replace(/\/+$/, "");
const port = process.env.SMOKE_PORT || "8765";
const baseURL = deployed || `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "smoke",
  // Local: the whole app. Deployed: only what works signed out.
  testMatch: deployed ? ["public.spec.js", "api.spec.js"] : ["pages.spec.js", "navigation.spec.js", "menuloading.spec.js", "rbd.spec.js", "actions.spec.js", "datasplit.spec.js", "typedlives.spec.js", "lifetimes.spec.js", "assettree.spec.js", "assetisolation.spec.js", "assetmerge.spec.js", "explorerclasses.spec.js", "exploreroverflow.spec.js", "explorerrcm.spec.js", "rcmworksheet.spec.js", "explorerfmea.spec.js", "explorerpin.spec.js", "explorerisolate.spec.js", "explorertabfocus.spec.js", "explorerlevels.spec.js", "explorersteady.spec.js", "explorerquiet.spec.js", "explorerrowmenu.spec.js", "explorertreesheet.spec.js", "explorerdelete.spec.js", "explorerreports.spec.js", "explorerlsa.spec.js", "explorermaintenance.spec.js", "taskoptimise.spec.js", "explorertaskpackage.spec.js", "explorermaintenancetree.spec.js", "explorermeasurements.spec.js", "explorermodelling.spec.js", "overhaulreplace.spec.js", "twoclocks.spec.js", "rbdtreeplan.spec.js", "library.spec.js", "nswc.spec.js", "covariatebind.spec.js", "reccov.spec.js", "missions.spec.js", "missiontree.spec.js", "plainmissions.spec.js", "tvc.spec.js", "rbdcalcquestions.spec.js", "workorderreadings.spec.js", "packagepage.spec.js", "operatingplan.spec.js", "forecast.spec.js", "forecastcosts.spec.js", "explorerfit.spec.js", "explorerbasis.spec.js", "explorerrcmimport.spec.js", "explorerrcmpanel.spec.js", "explorerrcmtasks.spec.js", "explorerrcmstandards.spec.js", "explorerrcmstdtree.spec.js", "explorerrcmdrag.spec.js", "explorerrcmmeasure.spec.js", "explorersticky.spec.js", "signals.spec.js", "time-to-limit.spec.js", "testplanning.spec.js", "modelframe.spec.js", "altextrapolation.spec.js", "notfound.spec.js", "datamodel.spec.js", "products.spec.js", "globalsearch.spec.js", "sharepage.spec.js", "api.spec.js"],
  globalSetup: "./smoke/seed.js",
  fullyParallel: true,
  workers: process.env.CI ? 4 : undefined,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  forbidOnly: Boolean(process.env.CI),
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"], ["html", { open: "on-failure" }]],
  use: {
    baseURL,
    viewport: { width: 1280, height: 900 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } } }],
  webServer: deployed
    ? undefined
    : {
        command: "node smoke/serve.mjs",
        url: `${baseURL}/api/health`,
        timeout: 120_000,
        reuseExistingServer: !process.env.CI,
        stdout: process.env.SMOKE_SERVER_LOG ? "pipe" : "ignore",
        stderr: "pipe",
      },
});
