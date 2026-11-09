// The Explorer's Signals tab (Assets › Explorer): a vibration channel
// with a few snapshots made through the API (a 50 Hz tone that grows), then the
// spectrum chart draws, a typed range becomes a watch band whose level shows
// over time, and Play steps through to the latest snapshot. At 400 px nothing
// scrolls the page sideways. The names start "Sig" so they sort after the other specs' plants.
// With SMOKE_SHOTS_DIR set, it also saves screenshots there (for the pull request).
import { test, expect, open, expectHealthy } from "./health.js";
import { EXPLORER_SIGNALS_TAB } from "../src/explorerTabs.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};

async function plant(request, tag) {
  const post = async (path, data) => {
    const res = await request.post(path, { data });
    expect(res.ok(), `${path}: ${res.status()} ${await res.text()}`).toBeTruthy();
    return res.json();
  };
  const pump = await post(`${M}/positions`, { name: `Sig pump ${tag}` });
  const channel = await post(`${M}/signals/channels`, {
    position_id: pump.id, name: `Sig bearing ${tag}`, unit: "g", sample_rate: 3200, axes: ["X", "Y"], rpm: 2980,
  });
  const n = 4096;
  const day = 24 * 3600 * 1000;
  const now = Date.now();
  // Five snapshots over 40 days, the 50 Hz tone growing; one gap longer than the rest.
  const gaps = [40, 39, 38, 20, 1];
  for (let i = 0; i < gaps.length; i += 1) {
    const amp = 0.1 + 0.12 * i;
    const wave = (hz, a) => Array.from({ length: n }, (_, k) => +(a * Math.sin((2 * Math.PI * hz * k) / 3200) + 0.01 * Math.sin(k * 1.7)).toFixed(5));
    await post(`${M}/signals/snapshots`, {
      channel_id: channel.id, time: new Date(now - gaps[i] * day).toISOString(), running: true,
      axes: { X: wave(50, amp), Y: wave(100, 0.05) },
    });
  }
  return { pump, channel };
}

test("the Signals tab: spectrum, a watch band, and play", async ({ page, request, problems }) => {
  test.skip(!EXPLORER_SIGNALS_TAB, "the Signals tab is hidden for now: the hidden-tab test covers it");
  const p = await plant(request, "A");
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=signals`);
  await expect(page.getByRole("tab", { name: "Signals" })).toHaveAttribute("aria-selected", "true");
  const spectrum = page.getByRole("region", { name: "Spectrum" });
  await expect(spectrum).toBeVisible();
  await expect(spectrum.locator(".js-plotly-plot")).toBeVisible();
  await expect(page.getByText("5 snapshots")).toBeVisible();

  // Type a range around the tone and watch it.
  await spectrum.getByLabel("From (Hz)").fill("45");
  await spectrum.getByLabel("To (Hz)").fill("55");
  await spectrum.getByRole("button", { name: "Watch this range" }).click();
  const bands = page.getByRole("region", { name: "Watch bands" });
  await expect(bands.getByText("45 to 55 Hz (X)")).toBeVisible();
  const level = page.getByRole("region", { name: "Level over time" });
  await expect(level.locator(".js-plotly-plot")).toBeVisible();

  // Play once: it ends on the latest snapshot.
  await level.getByRole("button", { name: "Play through the snapshots" }).click();
  await expect(level.getByRole("button", { name: "Play through the snapshots" })).toBeVisible({ timeout: 10_000 });
  await expect(level.getByRole("slider", { name: "Snapshot" })).toHaveValue("4");
  await shot(page, "signals-desktop");
  await expectHealthy(page, problems, { label: "signals tab" });
});

test("the Signals tab fits a phone and an item with no channel offers the guide", async ({ page, request, problems }) => {
  test.skip(!EXPLORER_SIGNALS_TAB, "the Signals tab is hidden for now: the hidden-tab test covers it");
  const p = await plant(request, "B");
  await page.setViewportSize({ width: 400, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=signals`);
  // On a phone the panel is its own screen: pick the row (the tabs' "For …" line names it too).
  await page.getByLabel("Positions").getByText("Sig pump B", { exact: true }).click();
  await expect(page.getByRole("region", { name: "Spectrum" })).toBeVisible();
  const sideways = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(sideways, "the page scrolls sideways at 400 px").toBe(false);
  await shot(page, "signals-phone");

  const bare = await request.post(`${M}/positions`, { data: { name: "Sig bare pump" } }).then((r) => r.json());
  await open(page, `/asset-register/explorer?arrange=positions&sel=${bare.id}&tab=signals`);
  await page.getByLabel("Positions").getByText("Sig bare pump", { exact: true }).click();
  await expect(page.getByText("No sensor channels here yet")).toBeVisible();
  await expect(page.getByRole("link", { name: "How signal channels work" })).toBeVisible();
  expect(problems, "errors on the page").toEqual([]);
});

test("view controls: orders, log scale, editable bands with levels, the storage line, adding a file", async ({ page, request, problems }) => {
  test.skip(!EXPLORER_SIGNALS_TAB, "the Signals tab is hidden for now: the hidden-tab test covers it");
  const p = await plant(request, "C");
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=signals`);
  const spectrum = page.getByRole("region", { name: "Spectrum" });
  await expect(spectrum.locator(".js-plotly-plot")).toBeVisible();
  await expect(page.getByText(/Snapshots in this workspace/)).toBeVisible();

  // Orders and log: toggles that keep the chart drawn.
  await spectrum.getByRole("button", { name: "Orders" }).click();
  await expect(spectrum.getByRole("button", { name: "Orders" })).toHaveAttribute("aria-pressed", "true");
  await expect(spectrum.getByText("Order (multiples of running speed)")).toBeVisible();
  await spectrum.getByRole("button", { name: "Log" }).click();
  await expect(spectrum.getByText(/log scale/)).toBeVisible();
  await spectrum.getByRole("button", { name: "Hz" }).click();
  await spectrum.getByRole("button", { name: "Linear" }).click();

  // A band, then edit it: a warning and an alarm level and a new range.
  await spectrum.getByLabel("From (Hz)").fill("45");
  await spectrum.getByLabel("To (Hz)").fill("55");
  await spectrum.getByRole("button", { name: "Watch this range" }).click();
  const bands = page.getByRole("region", { name: "Watch bands" });
  await expect(bands.getByText("45 to 55 Hz (X)")).toBeVisible();
  await bands.getByRole("button", { name: "Edit" }).click();
  const editor = bands.getByRole("form", { name: /Edit/ });
  await editor.getByLabel(/^Warn above/).fill("0.2");
  await editor.getByLabel(/^Alarm above/).fill("0.4");
  await editor.getByLabel(/^To/).fill("60");
  await expect(editor.getByText(/starts from the next snapshot/)).toBeVisible();
  await editor.getByRole("button", { name: "Save changes" }).click();
  await expect(bands.getByText("45 to 60 Hz (X)")).toBeVisible();
  await expect(bands.getByText(/Warn above 0.2/)).toBeVisible();
  await expect(bands.getByText(/range changed 1 time/)).toBeVisible();

  // Add a snapshot from a CSV file.
  await page.getByRole("button", { name: "Add a snapshot from a file" }).click();
  const rows = Array.from({ length: 512 }, (_, k) => (0.3 * Math.sin((2 * Math.PI * 50 * k) / 3200)).toFixed(5)).join("\n");
  await page.locator('input[type="file"]').setInputFiles({ name: "burst.csv", mimeType: "text/csv", buffer: Buffer.from(rows) });
  const form = page.getByRole("form", { name: "Add a snapshot" });
  await expect(form.getByText(/512 samples each/)).toBeVisible();
  await form.getByLabel(/^Axis names/).fill("X");
  await form.getByLabel(/^Time taken/).fill("2026-10-30T10:00");
  await form.getByRole("button", { name: "Add the snapshot", exact: true }).click();
  await expect(form.getByText("burst.csv: added.")).toBeVisible();
  await expect(page.getByText("6 snapshots")).toBeVisible();
  await shot(page, "signals-view-desktop");
  await expectHealthy(page, problems, { label: "signals view controls" });
});

test("a file with too many numbers is refused in plain words, and the controls fit a phone", async ({ page, request, problems }) => {
  test.skip(!EXPLORER_SIGNALS_TAB, "the Signals tab is hidden for now: the hidden-tab test covers it");
  const p = await plant(request, "D");
  await page.setViewportSize({ width: 400, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=signals`);
  await page.getByLabel("Positions").getByText("Sig pump D", { exact: true }).click();
  const spectrum = page.getByRole("region", { name: "Spectrum" });
  await expect(spectrum).toBeVisible();
  await expect(spectrum.getByRole("button", { name: "Orders" })).toBeVisible();
  await page.getByRole("button", { name: "Add a snapshot from a file" }).click();
  const big = Array.from({ length: 260000 }, () => "0.1,0.2").join("\n");
  await page.locator('input[type="file"]').setInputFiles({ name: "big.csv", mimeType: "text/csv", buffer: Buffer.from(big) });
  await expect(page.getByRole("alert").filter({ hasText: "520,000 numbers" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Use the first 250,000/ })).toBeVisible();
  await page.getByRole("button", { name: /Use the first 250,000/ }).click();
  await expect(page.getByRole("alert").filter({ hasText: "520,000 numbers" })).toHaveCount(0);
  const sideways = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(sideways, "the page scrolls sideways at 400 px").toBe(false);
  await shot(page, "signals-view-phone");
  expect(problems, "errors on the page").toEqual([]);
});

test("the Signals tab is hidden for now: no tab, an old address shows Summary, a channel's link opens the position", async ({ page, request, problems }) => {
  test.skip(EXPLORER_SIGNALS_TAB, "the Signals tab is shown: the tests above cover it");
  const p = await plant(request, "H");
  // Phone width first, desktop last: the health check at the end looks for the
  // panel's heading in the main pane, which the phone layout keeps off screen.
  for (const width of [400, 1280]) {
    await page.setViewportSize({ width, height: 800 });
    await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=signals`);
    if (width < 800) await page.getByLabel("Positions").getByText("Sig pump H", { exact: true }).click();
    await expect(page.getByRole("tab", { name: "Signals" })).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("region", { name: "Spectrum" })).toHaveCount(0);
  }
  // The data and API stay: the channel is still there.
  const channels = await request.get(`${M}/signals/channels`).then((r) => r.json());
  expect(channels.channels.some((c) => c.name === "Sig bearing H")).toBe(true);
  await expectHealthy(page, problems, { label: "signals tab hidden" });
});
