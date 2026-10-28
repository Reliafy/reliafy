// A function, functional failure or failure mode in its own dialog, on the
// Explorer's RCM tab (Operate › Assets › Explorer › RCM): a double-click on its
// row (not on a cell edited in place, nor the chevron), or Open… first in its
// row menu (right-click, ⋯, Shift+F10; on a phone the ⋯). Save keeps the
// words, checked as the panel checks them; Cancel, Esc or × drops them,
// asking first when something was typed; the focus goes back to the row; the
// Explorer's frame doesn't move. At 400 px it is a sheet and nothing scrolls
// sideways. Each test makes its own small plant through the API.
//
// With SMOKE_SHOTS_DIR set, it also saves screenshots of each dialog there,
// on the sample truck, at 1280 and 400 px (for the pull request).
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { frameOf, movedBetween } from "./explorer.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";

async function plant(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const top = await post(`${M}/positions`, { name: `Dlg plant ${tag}` });
  const pump = await post(`${M}/positions`, { name: `Dlg pump ${tag}`, parent_id: top.id });
  const fn = await post(`${M}/positions/${pump.id}/functions`, { text: `Pump water ${tag}`, standard: "10 L/s at 3 bar" });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `No flow ${tag}` });
  const mode = await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Bearing seizes ${tag}`, functional_failure_id: ff.id });
  await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Seal leaks ${tag}`, functional_failure_id: ff.id });
  return { top, pump, fn, ff, mode };
}

const table = (page) => page.getByRole("treegrid", { name: /and their RCM/ });
const trow = (page, name) => table(page).getByRole("row", { name: new RegExp(name) });
const dialog = (page, name) => page.getByRole("dialog", { name, exact: true });
const overflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
const settled = async (page) => {
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
  await page.waitForTimeout(250);
};

test("double-click opens each kind's dialog; Save keeps it, Esc drops it, the focus goes back, nothing moves", async ({ page, request, problems }) => {
  const tag = `d${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  const fnRow = trow(page, `^Function: Pump water ${tag}`);
  const ffRow = trow(page, `^Functional failure: No flow ${tag}`);
  const modeRow = trow(page, `^Failure mode: Bearing seizes ${tag}`);
  await expect(modeRow).toBeVisible();
  await modeRow.locator(".tp-nm").click();
  await settled(page);
  const before = await frameOf(page);

  // A function: its words, its standard, its functional failures.
  await fnRow.locator(".tp-nm").dblclick();
  let dlg = dialog(page, "Function");
  await expect(dlg).toBeVisible();
  await expect(dlg.getByRole("textbox", { name: /^Description/ })).toHaveValue(`Pump water ${tag}`);
  await expect(dlg.getByRole("textbox", { name: "Performance standard" })).toHaveValue("10 L/s at 3 bar");
  await expect(dlg.getByText(`On Dlg pump ${tag}`)).toBeVisible();
  await expect(dlg.getByRole("region", { name: "Functional failures" }).getByRole("button", { name: `No flow ${tag}` })).toBeVisible();
  await expect(dlg.getByRole("button", { name: "Add a working…" })).toBeVisible(); // the working behind the standard
  // Nothing typed: Esc closes at once, and the focus is back on the row.
  await page.keyboard.press("Escape");
  await expect(dlg).toHaveCount(0);
  await expect(fnRow).toBeFocused();

  // A functional failure: its status in words, its links, its failure modes; one opens from the list.
  await ffRow.locator(".tp-nm").dblclick();
  dlg = dialog(page, "Functional failure");
  await expect(dlg).toBeVisible();
  await expect(dlg.getByText("2 of its 2 failure modes still need a decision.")).toBeVisible();
  await expect(dlg.getByRole("region", { name: "Caused by, on positions below" })).toBeVisible();
  await expect(dlg.getByRole("region", { name: "Causes, on positions above" })).toBeVisible();
  await dlg.getByRole("region", { name: "Failure modes" }).getByRole("button", { name: `Seal leaks ${tag}` }).click();
  dlg = dialog(page, "Failure mode");
  await expect(dlg.getByRole("textbox", { name: /^Description/ })).toHaveValue(`Seal leaks ${tag}`);
  // …and back up to its failure from the line saying where it sits.
  await dlg.getByRole("button", { name: `No flow ${tag}` }).click();
  await expect(dialog(page, "Functional failure")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(ffRow).toBeFocused();

  // A failure mode: edit and save; the table shows it, and so does the server.
  await modeRow.locator(".tp-nm").dblclick();
  dlg = dialog(page, "Failure mode");
  await expect(dlg).toBeVisible();
  await expect(dlg.getByRole("region", { name: "Decision" })).toContainText("No decision yet.");
  // Focus stays in the dialog: Tab goes round it.
  for (let i = 0; i < 14; i += 1) await page.keyboard.press("Tab");
  expect(await page.evaluate(() => !!document.activeElement?.closest(".rcm-item-modal"))).toBe(true);
  // Every failure mode needs a description: said under the field, nothing sent.
  const desc = dlg.getByRole("textbox", { name: /^Description/ });
  await desc.fill("   ");
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(dlg.getByRole("alert")).toHaveText("Every failure mode needs a description.");
  await expect(desc).toBeFocused();
  await desc.fill(`Bearing seizes early ${tag}`);
  await dlg.getByRole("textbox", { name: /^Failure effects/ }).fill("Pump stops; no flow to the tank");
  await dlg.getByRole("combobox", { name: "Consequence" }).selectOption("hidden");
  // Typed and not saved: Esc asks first; Keep editing keeps it all.
  await page.keyboard.press("Escape");
  const ask = page.getByRole("alertdialog", { name: "Discard your changes?" });
  await expect(ask).toBeVisible();
  await ask.getByRole("button", { name: "Keep editing" }).click();
  await expect(dlg.getByRole("textbox", { name: /^Failure effects/ })).toHaveValue("Pump stops; no flow to the tank");
  // Saved once, however fast it's double-clicked.
  let writes = 0;
  page.on("request", (r) => { if (r.method() !== "GET" && r.url().includes(`/failure-modes/${p.mode.id}`)) writes += 1; });
  await dlg.getByRole("button", { name: "Save" }).dblclick();
  await expect(dlg).toHaveCount(0);
  expect(writes).toBe(2); // its words, then its consequence
  const saved = trow(page, `^Failure mode: Bearing seizes early ${tag}`);
  await expect(saved).toBeVisible();
  await expect(saved).toContainText("Pump stops; no flow to the tank");
  await expect(saved).toBeFocused();
  const rcm = await (await request.get(`${M}/rcm`)).json();
  const m = rcm.positions.find((x) => x.id === p.pump.id).functions[0].failures[0].modes.find((x) => x.id === p.mode.id);
  expect([m.text, m.effects, m.consequence]).toEqual([`Bearing seizes early ${tag}`, "Pump stops; no flow to the tank", "hidden"]);

  // Decide… opens the decision dialog over it; Esc closes that one only.
  await saved.locator(".tp-nm").dblclick();
  dlg = dialog(page, "Failure mode");
  await dlg.getByRole("button", { name: "Decide…" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(2);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(1);
  await expect(dlg).toBeVisible();
  // Discard after typing: Esc, then Discard changes.
  await dlg.getByRole("textbox", { name: "Mode notes" }).fill("not this");
  await page.keyboard.press("Escape");
  await ask.getByRole("button", { name: "Discard changes" }).click();
  await expect(dlg).toHaveCount(0);
  await expect(saved).toBeFocused();

  // A cell edited in place still edits in place on a double-click.
  await saved.getByRole("gridcell").first().dblclick();
  await expect(table(page).getByRole("textbox", { name: /^Failure effects of/ })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // The chevron: a double-click opens or closes the row once, and opens no dialog.
  const was = await fnRow.getAttribute("aria-expanded");
  await fnRow.locator(".tp-chev").dblclick();
  await expect(fnRow).toHaveAttribute("aria-expanded", was === "true" ? "false" : "true");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await fnRow.locator(".tp-chev").click();
  await expect(fnRow).toHaveAttribute("aria-expanded", was);

  // The frame is where it was before any of it.
  await saved.locator(".tp-nm").click();
  await settled(page);
  const after = await frameOf(page);
  expect(movedBetween(before, after).filter((x) => !x.startsWith("row "))).toEqual([]);
  await expectHealthy(page, problems, { label: "rcm dialogs" });
});

test("Open… is first in the row menu; Enter still opens the Details", async ({ page, request, problems }) => {
  const tag = `o${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  const ffRow = trow(page, `^Functional failure: No flow ${tag}`);
  await ffRow.locator(".tp-nm").click();
  await page.keyboard.press("Shift+F10");
  const menu = page.getByRole("menu", { name: new RegExp(`^Actions for Functional failure: No flow ${tag}`) });
  await expect(menu.getByRole("menuitem").first()).toHaveText("Open…");
  await expect(menu.getByRole("menuitem", { name: "Open…" })).toBeFocused();
  await page.keyboard.press("Enter");
  const dlg = dialog(page, "Functional failure");
  await expect(dlg).toBeVisible();
  // Show in Details: the dialog goes, the panel shows the row.
  await dlg.getByRole("button", { name: "Show in Details" }).click();
  await expect(dlg).toHaveCount(0);
  await expect(page.getByRole("complementary", { name: "Details" })).toContainText(`No flow ${tag}`);
  // Enter on a row: the Details, as before.
  await ffRow.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("complementary", { name: "Details" })).toBeVisible();
  await expectHealthy(page, problems, { label: "rcm open from menu" });
});

test("at 400 px Open… in the ⋯ menu opens a sheet that fits, and Save works", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  const fnRow = trow(page, `^Function: Pump water ${tag}`);
  await fnRow.getByRole("button", { name: "Actions", exact: true }).click();
  await page.getByRole("menu", { name: new RegExp(`^Actions for Function: Pump water ${tag}`) }).getByRole("menuitem", { name: "Open…" }).click();
  const dlg = dialog(page, "Function");
  await expect(dlg).toBeVisible();
  const box = await dlg.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(400.5);
  expect(Math.round(box.y + box.height)).toBe(860); // a sheet from the foot of the screen
  expect(await overflow(page)).toBe(0);
  await dlg.getByRole("textbox", { name: "Performance standard" }).fill("12 L/s at 3 bar");
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(dlg).toHaveCount(0);
  const rcm = await (await request.get(`${M}/rcm`)).json();
  expect(rcm.positions.find((x) => x.id === p.pump.id).functions[0].standard).toBe("12 L/s at 3 bar");
  expect(await overflow(page)).toBe(0);
  await expectHealthy(page, problems, { label: "rcm dialog phone" });
});

test("screenshots of each dialog on the sample truck (SMOKE_SHOTS_DIR)", async ({ page, request }) => {
  test.skip(!SHOTS, "only when saving screenshots");
  const truck = (await postOk(request, `${M}/sample-truck`, { again: true })).position;
  const rcm = await (await request.get(`${M}/rcm`)).json();
  const pos = rcm.positions.find((x) => x.id === truck.id);
  const fn = pos.functions[0];
  const ff = fn.failures[0];
  const mode = ff.modes.find((x) => x.decision) || ff.modes[0];
  for (const [w, h] of [[1280, 800], [400, 860]]) {
    await page.setViewportSize({ width: w, height: h });
    await open(page, `/asset-register/explorer?arrange=positions&sel=${truck.id}&tab=rcm`);
    for (const [kind, label, text] of [["fn", "Function", fn.text], ["fail", "Functional failure", ff.text], ["mode", "Failure mode", mode.text]]) {
      const row = trow(page, `^${label}: ${text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`).first();
      if (w > 600) await row.locator(".tp-nm").dblclick();
      else {
        await row.getByRole("button", { name: "Actions", exact: true }).click();
        await page.getByRole("menuitem", { name: "Open…" }).click();
      }
      await expect(dialog(page, label)).toBeVisible();
      await page.waitForTimeout(300);
      await page.screenshot({ path: `${SHOTS}/rcm-modal-${kind}-${w}.png` });
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog")).toHaveCount(0);
    }
  }
});
