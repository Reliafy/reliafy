// The Explorer's Signals tab (Operate › Assets › Explorer): a vibration channel
// with a few snapshots made through the API (a 50 Hz tone that grows), then the
// spectrum chart draws, a typed range becomes a watch band whose level shows
// over time, and Play steps through to the latest snapshot. At 400 px nothing
// scrolls the page sideways. The names start "Sig" so they sort after the other specs' plants.
// With SMOKE_SHOTS_DIR set, it also saves screenshots there (for the pull request).
import { test, expect, open, expectHealthy } from "./health.js";

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
  const p = await plant(request, "B");
  await page.setViewportSize({ width: 400, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=signals`);
  // On a phone the panel is its own screen: pick the row.
  await page.getByText("Sig pump B", { exact: true }).click();
  await expect(page.getByRole("region", { name: "Spectrum" })).toBeVisible();
  const sideways = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(sideways, "the page scrolls sideways at 400 px").toBe(false);
  await shot(page, "signals-phone");

  const bare = await request.post(`${M}/positions`, { data: { name: "Sig bare pump" } }).then((r) => r.json());
  await open(page, `/asset-register/explorer?arrange=positions&sel=${bare.id}&tab=signals`);
  await page.getByText("Sig bare pump", { exact: true }).click();
  await expect(page.getByText("No sensor channels here yet")).toBeVisible();
  await expect(page.getByRole("link", { name: "How signal channels work" })).toBeVisible();
  expect(problems, "errors on the page").toEqual([]);
});
