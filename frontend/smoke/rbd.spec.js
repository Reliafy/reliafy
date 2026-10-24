// RBDs: every tab of every sample diagram, a calculation, and the importers
// (BlockSim, Open-PSA, Galileo, Excel) through the RBDs page's Import button.
import { existsSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test, expect, open, expectHealthy } from "./health.js";

const fixture = (name) => fileURLToPath(new URL(`fixtures/${name}`, import.meta.url));

test("every tab of every sample RBD", async ({ page, request, problems }) => {
  const { rbds } = await (await request.get("/api/rbds")).json();
  const samples = rbds.filter((r) => r.is_sample);
  expect(samples.length).toBeGreaterThan(0);
  for (const rbd of samples) {
    await open(page, `/systems/b/${rbd.id}`);
    const tablist = page.getByRole("tablist", { name: "Diagram views" });
    const names = await tablist.getByRole("tab").allInnerTexts();
    expect(names.length, `${rbd.id}: no tabs`).toBeGreaterThan(1);
    for (const name of names) {
      await test.step(`${rbd.id} › ${name}`, async () => {
        const tab = tablist.getByRole("tab", { name, exact: true });
        await tab.click();
        await expect(tab).toHaveAttribute("aria-selected", "true");
        await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
        await expectHealthy(page, problems, { label: `${rbd.id} › ${name}` });
      });
    }
  }
});

test("calculate a sample RBD", async ({ page, problems }) => {
  await open(page, "/systems/b/sample-rbd-pump-station");
  await page.getByRole("tab", { name: "Calculator" }).click();
  await page.locator('[data-wt="rbd-calculate"]').click();
  const panel = page.locator(".rbd-calc-panel").first();
  await expect(panel.getByText("Minimal cut sets")).toBeVisible({ timeout: 30_000 });
  await expect(panel.getByText(/MTTF/).first()).toBeVisible();
  await expectHealthy(page, problems, { label: "calculated RBD", chart: true });
});

// The BlockSim examples are ReliaSoft's copyright, so they aren't in the
// repository: backend/scripts/fetch_rbd_import_fixtures.py downloads them.
const BLOCKSIM_DIR = fileURLToPath(new URL("../../backend/tests/fixtures/external/blocksim/", import.meta.url));
const blocksim = () => {
  const files = existsSync(BLOCKSIM_DIR) ? readdirSync(BLOCKSIM_DIR).filter((f) => /\.(rsgz|rsr)\d+$|\.rsrp$/.test(f)) : [];
  const file = files.includes("blocksim_example1_V20.rsgz20") ? "blocksim_example1_V20.rsgz20" : files[0];
  return file && BLOCKSIM_DIR + file;
};

const IMPORTS = [
  { format: "Galileo", file: () => fixture("pump-train.dft"), blocks: 4 },
  { format: "Open-PSA", file: () => fixture("cooling.xml"), blocks: 5 },
  { format: "Excel", file: null, blocks: 2 }, // the template the app offers
  { format: "BlockSim", file: blocksim, blocks: 2 },
];

for (const { format, file, blocks } of IMPORTS) {
  test(`import an RBD from ${format}`, async ({ page, request, problems }) => {
    let upload;
    if (file) {
      upload = file();
      test.skip(!upload, "No BlockSim example here: run backend/scripts/fetch_rbd_import_fixtures.py");
    } else {
      const res = await request.get("/api/rbds/import/template.xlsx");
      expect(res.ok()).toBeTruthy();
      upload = { name: "reliafy-rbd-template.xlsx", mimeType: "application/octet-stream", buffer: await res.body() };
    }
    await open(page, "/systems/rbds");
    await page.locator('input[type="file"]').setInputFiles(upload);
    await page.waitForURL(/\/systems\/b$/, { timeout: 30_000 });
    await expect(page.locator(".react-flow__node").nth(blocks - 1)).toBeVisible();
    await expectHealthy(page, problems, { label: `${format} import` });
  });
}

// Full screen: the toolbar and canvas cover the screen, and every dialog,
// list and menu opened there shows inside it (they render in a portal, which
// would otherwise be hidden behind the full-screen part).
const inFull = (page, selector) =>
  page.evaluate((sel) => {
    const full = document.querySelector(".rbd-builder.is-full");
    const el = document.querySelector(sel);
    return !!(full && el && full.contains(el));
  }, selector);
const nativeFull = (page) => page.evaluate(() => document.fullscreenElement?.classList.contains("rbd-builder") ?? false);
const noFullscreenApi = () => {
  for (const k of ["requestFullscreen", "webkitRequestFullscreen"]) {
    delete Element.prototype[k];
    delete HTMLElement.prototype[k];
  }
  for (const k of ["exitFullscreen", "webkitExitFullscreen"]) delete Document.prototype[k];
};
const addComponent = async (page) => {
  await page.getByRole("button", { name: "Add block" }).click();
  await page.locator(".ovm-item", { hasText: /^Component$/ }).click();
};

test("full screen: edit, open dialogs and save without leaving it", async ({ page, problems }) => {
  await open(page, "/systems/b");
  const nodes = page.locator(".react-flow__node");
  const before = await nodes.count();
  await addComponent(page); // made before entering: still there after
  await expect(nodes).toHaveCount(before + 1);

  const toggle = page.locator(".rbd-full-panel .full-screen-btn");
  await expect(toggle).toHaveAttribute("title", "Full screen (F)");
  await toggle.click();
  await expect.poll(() => nativeFull(page)).toBe(true);
  await expect(page.getByRole("button", { name: "Exit full screen" })).toBeVisible();
  await expect(page.locator(".rbd-full-status")).toContainText("Not saved yet");
  const box = await page.locator(".rbd-builder").boundingBox();
  expect(box.width).toBe(1280);
  expect(box.height).toBe(900);

  // Add a block and open its dialog, with a dropdown in it, inside full screen.
  await addComponent(page);
  await expect(nodes).toHaveCount(before + 2);
  await nodes.filter({ hasText: "Component 2" }).dblclick();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(await inFull(page, ".overlay")).toBe(true);
  await page.getByRole("dialog").getByRole("combobox").first().click();
  await expect(page.getByRole("listbox")).toBeVisible();
  expect(await inFull(page, ".sel-menu")).toBe(true);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // The diagram's mode dropdown in the toolbar.
  await page.locator(".rbd-mode-select").click();
  await expect(page.getByRole("listbox")).toBeVisible();
  expect(await inFull(page, ".sel-menu")).toBe(true);
  await page.getByRole("option", { name: "Non-repairable" }).click();

  // Save: the name dialog shows, and the first save keeps full screen and the canvas.
  await page.getByRole("button", { name: /^Save/ }).first().click();
  await page.locator(".ovm-item", { hasText: /^Save…$/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  expect(await inFull(page, ".overlay")).toBe(true);
  await dialog.locator("input").first().fill("Full screen smoke");
  await dialog.locator("input").first().press("Enter");
  await page.waitForURL(/\/systems\/b\/[\w-]+$/);
  await expect(page.locator(".rbd-full-status")).toContainText("Saved");
  await expect.poll(() => nativeFull(page)).toBe(true);
  await expect(nodes).toHaveCount(before + 2);
  await page.locator(".react-flow__pane").click({ position: { x: 40, y: 40 } });
  await addComponent(page);
  await expect(page.locator(".rbd-full-status")).toContainText("Unsaved changes");

  // Out again: the browser's full screen ends, focus is back on the button,
  // and every block is still there.
  await page.getByRole("button", { name: "Exit full screen" }).click();
  await expect.poll(() => nativeFull(page)).toBe(false);
  await expect(page.locator(".rbd-builder.is-full")).toHaveCount(0);
  await expect(toggle).toBeFocused();
  await expect(nodes).toHaveCount(before + 3);
  await expect(page.locator(".portal-host")).toHaveCount(1);
  expect(await page.evaluate(() => document.querySelector(".portal-host").parentElement === document.body)).toBe(true);
  // F goes in and out too (the browser's own exit is picked up the same way).
  await page.locator(".react-flow__pane").click({ position: { x: 40, y: 40 } });
  await page.keyboard.press("f");
  await expect.poll(() => nativeFull(page)).toBe(true);
  await page.evaluate(() => document.exitFullscreen());
  await expect(page.locator(".rbd-builder.is-full")).toHaveCount(0);
  await expectHealthy(page, problems, { label: "full screen" });
});

test("full screen without the browser's Fullscreen API (iPhone): covers the page", async ({ page, problems }) => {
  await page.addInitScript(noFullscreenApi);
  await open(page, "/systems/b/sample-rbd-pump-station");
  const nodes = page.locator(".react-flow__node");
  await expect(nodes.first()).toBeVisible();
  const count = await nodes.count();
  await page.locator(".react-flow__pane").click({ position: { x: 40, y: 40 } });
  await page.keyboard.press("F");
  const builder = page.locator(".rbd-builder.is-full");
  await expect(builder).toBeVisible();
  expect(await nativeFull(page)).toBe(false);
  await expect(page.locator("html.full-screen-lock")).toHaveCount(1);
  const box = await builder.boundingBox();
  expect([box.x, box.y, box.width, box.height]).toEqual([0, 0, 1280, 900]);
  await expect(page.locator(".rbd-full-status")).toContainText("Read only");

  // Escape closes the dialog first, then leaves full screen.
  await addComponent(page);
  await expect(nodes).toHaveCount(count + 1);
  await nodes.filter({ hasText: "Component" }).last().dblclick();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(await inFull(page, ".overlay")).toBe(true);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(builder).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".rbd-builder.is-full")).toHaveCount(0);
  await expect(page.locator("html.full-screen-lock")).toHaveCount(0);
  await expect(nodes).toHaveCount(count + 1);
  // ...and the button.
  await page.getByRole("button", { name: "Full screen", exact: true }).click();
  await expect(builder).toBeVisible();
  await page.getByRole("button", { name: "Exit full screen" }).click();
  await expect(page.locator(".rbd-builder.is-full")).toHaveCount(0);
  await expectHealthy(page, problems, { label: "full screen fallback" });
});

test("full screen on a phone (400 px): no sideways scroll, big enough to tap", async ({ page, problems }) => {
  await page.setViewportSize({ width: 400, height: 860 });
  await page.addInitScript(noFullscreenApi);
  await open(page, "/systems/b/sample-rbd-pump-station");
  await expect(page.locator(".react-flow__node").first()).toBeVisible();
  const enter = page.getByRole("button", { name: "Full screen", exact: true });
  expect((await enter.boundingBox()).height).toBeGreaterThanOrEqual(40);
  await enter.click();
  await expect(page.locator(".rbd-builder.is-full")).toBeVisible();
  const exit = page.getByRole("button", { name: "Exit full screen" });
  await expect(exit).toBeVisible();
  const size = await exit.boundingBox();
  expect(size.height).toBeGreaterThanOrEqual(40);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await addComponent(page);
  await page.locator(".react-flow__node").filter({ hasText: "Component" }).last().dblclick();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
  await exit.click();
  await expect(page.locator(".rbd-builder.is-full")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Full screen", exact: true })).toBeFocused();
  await expectHealthy(page, problems, { label: "full screen at 400 px" });
});
