// What "the page works" means for the smoke tests, shared by every spec:
// no error boundary ("Something went wrong"), no uncaught page errors, no
// console errors (bar the known benign ones below), the page's content on
// screen, and a rendered chart where one is expected.
import { test as base, expect } from "@playwright/test";

export { expect };

export const DEPLOYED = Boolean(process.env.SMOKE_BASE_URL);

// Console errors that don't mean the page is broken, matched against the
// message and the URL it's about. Keep each one narrow and say why it's
// harmless. (The browser logs every 4xx response as a console error.)
const BENIGN_CONSOLE = [
  // A sample diagram's Outage history tab: the list answers 403 with code
  // "sample", and the tab says to duplicate the sample first.
  /status of 403 \(Forbidden\) \(\S+\/api\/rbds\/sample-[\w-]+\/outage-logs\)$/,
  // Pageview analytics, throttled per address (120 a minute): the whole suite
  // opening pages from one address can pass that. The page doesn't wait on it.
  /status of 429 \(Too Many Requests\) \(\S+\/api\/metrics\/event\)$/,
];

export const test = base.extend({
  // Problems seen while the test ran: uncaught errors, console errors and
  // server errors.
  problems: async ({ page }, use) => {
    const problems = [];
    page.on("pageerror", (err) => problems.push(`uncaught: ${err.message}`));
    page.on("console", (msg) => {
      if (msg.type() !== "error") return;
      const where = msg.location()?.url;
      const text = `${msg.text()}${where ? ` (${where})` : ""}`;
      if (!BENIGN_CONSOLE.some((re) => re.test(text))) problems.push(`console: ${text}`);
    });
    // The browser's own dialogs are never used (the app has its own confirm
    // dialog): one opening is a failure, dismissed so the test doesn't hang.
    page.on("dialog", (dialog) => {
      problems.push(`native ${dialog.type()} dialog: ${dialog.message()}`);
      dialog.dismiss().catch(() => {});
    });
    // A server error behind the page is a failure even if the page copes.
    page.on("response", (res) => {
      if (res.status() >= 500) problems.push(`${res.status()} from ${res.request().method()} ${res.url()}`);
    });
    if (DEPLOYED) {
      // Against a live site the run is read-only: the page's own writes
      // (analytics beacons, error reports) are answered here and never sent.
      await page.addInitScript(() => {
        navigator.sendBeacon = () => true;
      });
      await page.route("**/*", (route) =>
        ["GET", "HEAD", "OPTIONS"].includes(route.request().method())
          ? route.continue()
          : route.fulfill({ status: 204, body: "" })
      );
    }
    await use(problems);
  },
});

// Open `path` and wait for it to settle: the network quiet (bounded: some
// pages poll) and no "Loading…" placeholder left.
export async function open(page, path) {
  const response = await page.goto(path, { waitUntil: "load" });
  await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
  await expect(page.locator(".view-loading, .auth-loading"), `${path} still loading`).toHaveCount(0, {
    timeout: 20_000,
  });
  return response;
}

// The page drew without crashing: no "Something went wrong" (the error
// boundary, or a page's own failure heading), its content area showing a
// heading, a chart if asked for, and nothing logged as an error.
export async function expectHealthy(page, problems, { label = page.url(), chart = false, root = "main" } = {}) {
  const crashed = async () => {
    const shown = page
      .locator(".error-boundary")
      .or(page.getByRole("heading", { name: "Something went wrong", exact: true }));
    if (await shown.count()) throw new Error(`${label}: "Something went wrong"\n${problems.join("\n")}`);
  };
  await crashed();
  const content = page.locator(root).first();
  await expect(content, `${label}: no ${root}`).toBeVisible();
  await expect(content.locator("h1, h2").first(), `${label}: no heading`).toBeVisible();
  if (chart) {
    await expect(content.locator(".js-plotly-plot .main-svg").first(), `${label}: no chart`).toBeVisible({
      timeout: 20_000,
    });
  }
  await crashed(); // a crash once the page's data arrived
  expect(problems, `${label}: errors in the page`).toEqual([]);
}

// POST to the API and return the JSON, failing the test on a refusal. The
// Maintenance API takes at most 600 changes a minute per workspace, and the
// whole suite shares one: a 429 waits for the next minute (up to 65 s) and
// tries again, rather than failing a test for what other tests did.
export async function postOk(request, path, data) {
  const until = Date.now() + 65_000;
  for (;;) {
    const res = await request.post(path, { data });
    if (res.status() === 429 && Date.now() < until) {
      await new Promise((r) => setTimeout(r, 2_000));
      continue;
    }
    expect(res.ok(), `${path}: ${res.status()} ${await res.text()}`).toBeTruthy();
    return res.json();
  }
}
