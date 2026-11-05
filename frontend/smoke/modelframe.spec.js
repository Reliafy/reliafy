// The model pages fit the screen (the model frame, components/model/): for
// every kind of model in MODEL_KINDS (smoke/modelKinds.js) and every tab its
// page shows, at 1440×900 the page doesn't scroll (charts size to the tab,
// long tables scroll inside their card), and at 400 px wide nothing scrolls
// sideways (a phone scrolls down as usual).
//
// To check a new kind of model page: add a row to MODEL_KINDS (and, if no
// sample has one, its fit to seedModelKinds()). Nothing here changes.
import { test, expect, open, expectHealthy } from "./health.js";
import { MODEL_KINDS, kindUrl } from "./modelKinds.js";

const SIZES = [
  { name: "desktop", viewport: { width: 1440, height: 900 }, vertical: true },
  { name: "phone", viewport: { width: 400, height: 860 }, vertical: false },
];

const overflow = (page) => page.evaluate(() => {
  const el = document.scrollingElement;
  return { down: el.scrollHeight - innerHeight, side: el.scrollWidth - innerWidth };
});

for (const kind of MODEL_KINDS) {
  for (const size of SIZES) {
    test(`model page fits: ${kind.slug} at ${size.name}`, async ({ page, request, problems }) => {
      await page.setViewportSize(size.viewport);
      const url = await kindUrl(request, kind);
      await open(page, url);
      const tabs = page.locator("main [role=tablist][aria-label='Model views'] [role=tab]");
      await expect(tabs).toHaveText(kind.tabs);
      const names = kind.tabs.length ? kind.tabs : [null];
      for (const [i, name] of names.entries()) {
        await test.step(name || "(one view)", async () => {
          if (name) {
            await tabs.nth(i).click();
            await expect(tabs.nth(i)).toHaveAttribute("aria-selected", "true");
            // The open tab is in the address (the first one has none).
            if (i > 0) await expect(page).toHaveURL(/[?&]tab=/);
          }
          await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
          await page.waitForTimeout(400);
          const { down, side } = await overflow(page);
          expect(side, `${kind.slug} · ${name}: scrolls sideways by ${side}px at ${size.name}`).toBeLessThanOrEqual(0);
          if (size.vertical) {
            expect(down, `${kind.slug} · ${name}: the page scrolls by ${down}px at 1440×900`).toBeLessThanOrEqual(0);
          }
        });
      }
      await expectHealthy(page, problems, { label: `${kind.slug} at ${size.name}` });
    });
  }
}

// Old tab ids in links open the tab that holds that content now, and the
// arrow keys move between the tabs (the ARIA tab pattern).
test("model tabs: old links and the keyboard", async ({ page, problems }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, "/models/m/sample-model-seal-weibull-ph?tab=check");
  const selected = page.locator("main [role=tab][aria-selected=true]");
  await expect(selected).toHaveText("Diagnostics");
  await open(page, "/models/m/sample-model-seal-weibull-ph?tab=coef");
  await expect(selected).toHaveText("Effects");
  await selected.focus();
  await page.keyboard.press("ArrowRight");
  await expect(selected).toHaveText("Calculator");
  await expect(selected).toBeFocused();
  await page.keyboard.press("End");
  await expect(selected).toHaveText("Data");
  await page.keyboard.press("Home");
  await expect(selected).toHaveText("Effects");
  await expect(page.getByRole("tabpanel")).toBeVisible();
  await expectHealthy(page, problems, { label: "model tabs", chart: true });
});
