// The Explorer's RCM table scrolled sideways (Operate › Assets › Explorer, the
// RCM tab): the tree column stays put on the left and the other columns slide
// under it. Whatever state a row is in (hovered, picked, keyboard focus, a cell
// being edited, its menu open, the "Not under a functional failure" rows, a
// pinned branch, full screen), the tree cell stays on top and opaque: nothing
// scrolled under it shows through. Checked two ways for each state: the point
// at the row's name (and over the text scrolled under it) hits the tree cell,
// and the tree cell looks exactly the same with the cells under it hidden.
// Its names start "Zone" so they sort after the other specs' plants, which
// share the server and expect their rows near the top.
// With SMOKE_SHOTS_DIR set, it also saves screenshots there (for the pull request).
import { test, expect, open, expectHealthy } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
// The whole window, and a close-up of the row (a few rows either side).
const shot = async (page, name, row) => {
  if (!SHOTS) return;
  await page.screenshot({ path: `${SHOTS}/${name}.png` });
  if (!row) return;
  const b = await row.boundingBox();
  const x = Math.max(0, b.x - 10);
  await page.screenshot({ path: `${SHOTS}/${name}-close.png`, clip: { x, y: Math.max(0, b.y - 70), width: Math.min(760, page.viewportSize().width - x), height: b.height + 140 } });
};

async function plant(request, tag) {
  const send = async (method, path, data) => {
    const res = await request.fetch(path, { method, data });
    expect(res.ok(), `${path}: ${res.status()} ${await res.text()}`).toBeTruthy();
    return res.json();
  };
  const post = (path, data) => send("POST", path, data);
  const top = await post(`${M}/positions`, { name: `Zone pool ${tag}` });
  const pump = await post(`${M}/positions`, { name: `Zone circulation and treatment ${tag}`, parent_id: top.id });
  const fn = await post(`${M}/positions/${pump.id}/functions`, { text: `Keep the water clear and free of algae ${tag}` });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `Floor not visible at the deep end ${tag}` });
  const basket = await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Basket blocked ${tag}`, functional_failure_id: ff.id });
  await send("PATCH", `${M}/failure-modes/${basket.id}`, { effects: "Floor visible at the deep end goes cloudy within two days" });
  await send("PUT", `${M}/failure-modes/${basket.id}/decision`, {
    consequence: "operational", decision: { outcome: "fixed_interval", task: "Empty the pump basket", interval: 12, interval_unit: "months" },
  });
  // A mode under no functional failure: the "Not under a functional failure" heading over it.
  const loose = await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Seal weeps ${tag}` });
  await send("PATCH", `${M}/failure-modes/${loose.id}`, { effects: "Water drips under the pump and the floor stays wet" });
  return { top, pump, fn, ff, basket, loose };
}

const table = (page) => page.getByRole("treegrid", { name: /and their RCM/ });
const trow = (page, name) => table(page).getByRole("row", { name: new RegExp(name) });
const scroller = (page) => page.locator(".tp-scroll");

// Scroll the table so the row is in view (the other specs' plants come
// first) and sideways so its first cell with text starts under the middle of
// the tree column (or as far as it goes).
async function slideUnder(row) {
  await row.evaluate((el) => {
    const sc = el.closest(".tp-scroll");
    if (!el.closest(".tp-pins")) {
      const b = el.getBoundingClientRect();
      const v = sc.getBoundingClientRect();
      if (b.top < v.top + 80 || b.bottom > v.bottom - 80) sc.scrollTop += b.top - (v.top + v.height / 2);
    }
    const tree = el.querySelector(".tt-tree");
    const cell = [...el.querySelectorAll(".rw-c")].find((c) => c.textContent.trim());
    if (!cell) throw new Error("no cell with text in the row");
    sc.scrollLeft = Math.max(0, cell.offsetLeft - tree.offsetWidth / 2);
  });
}

// Is the tree cell of `row` on top of everything scrolled under it?
// - `under`: the text scrolled under the tree cell (there must be some);
// - `hits`: for the middle of the name and each spot where that text lies,
//   whether the point lands in the tree cell;
// - `same`: the tree cell's pixels are the same with the cells under it hidden.
async function onTop(page, row) {
  const geo = await row.evaluate((el) => {
    const tree = el.querySelector(".tt-tree");
    const t = tree.getBoundingClientRect();
    const nm = tree.querySelector(".tp-nm, .rw-edit");
    const n = nm.getBoundingClientRect();
    const y = n.top + n.height / 2;
    const under = [];
    const points = [{ x: n.left + Math.min(n.width / 2, 40), y, what: "name" }];
    for (const c of el.querySelectorAll(".rw-c")) {
      const b = c.getBoundingClientRect();
      const text = c.textContent.trim();
      const from = Math.max(b.left, t.left) + 4;
      const to = Math.min(b.right - 4, t.right - 10); // the column's resize handle sits over its last few px
      if (!text || to - from < 16) continue; // not under the tree column (or only its edge)
      under.push(text);
      points.push({ x: from, y, what: text }, { x: (from + to) / 2, y, what: text }, { x: to, y, what: text });
    }
    const hits = points.map((p) => {
      const at = document.elementFromPoint(p.x, p.y);
      // The row's own menu, open, is meant to be over everything.
      return { what: p.what, x: Math.round(p.x), inTree: Boolean(at && (tree.contains(at) || at.closest("[role=menu]"))), at: at ? `${at.tagName.toLowerCase()}.${at.className?.baseVal ?? at.className}` : null };
    });
    return { clip: { x: t.left, y: t.top, width: t.width, height: t.height }, under, hits };
  });
  const look = () => page.screenshot({ clip: geo.clip, animations: "disabled", caret: "hide" });
  const shown = await look();
  await page.addStyleTag({ content: ".tp-scroll .rw-c { opacity: 0 !important; } /* sticky-check (not hidden: a field being edited would lose the focus) */" });
  const hidden = await look();
  await page.evaluate(() => {
    for (const s of document.querySelectorAll("style")) if (s.textContent.includes("sticky-check")) s.remove();
  });
  return { under: geo.under, hits: geo.hits.filter((h) => !h.inTree), same: shown.equals(hidden) };
}

async function expectOnTop(page, row, state) {
  const r = await onTop(page, row);
  expect(r.under.length, `${state}: some text is scrolled under the tree column`).toBeGreaterThan(0);
  expect(r.hits, `${state}: points over the tree column hit it`).toEqual([]);
  expect(r.same, `${state}: nothing scrolled under the tree column shows through (${r.under.join(" | ")})`).toBe(true);
}

test("the RCM table scrolled sideways: the tree column stays on top and opaque, whatever state the row is in", async ({ page, request, problems }) => {
  const tag = `s${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  await expect(table(page)).toBeVisible();
  // More columns than fit, so the table scrolls sideways.
  await page.getByRole("button", { name: "Columns", exact: true }).click();
  const pop = page.getByRole("group", { name: "Columns to show" });
  for (const n of ["Interval", "Evidence", "Mode notes", "Decision notes", "What the evidence shows"]) await pop.getByRole("checkbox", { name: n, exact: true }).check();
  await page.keyboard.press("Escape");
  await expect(table(page).getByRole("columnheader", { name: "Interval" })).toBeVisible();
  // A wider tree column (as dragged out to read long names).
  await page.getByRole("separator", { name: "Resize the tree column" }).focus();
  for (let i = 0; i < 8; i += 1) await page.keyboard.press("ArrowRight");
  expect(await scroller(page).evaluate((el) => el.scrollWidth - el.clientWidth)).toBeGreaterThan(300);

  const basket = trow(page, `^Failure mode: Basket blocked ${tag}`);
  const loose = trow(page, `^Failure mode: Seal weeps ${tag}`);
  const heading = trow(page, "^Not under a functional failure");
  const fn = trow(page, `^Function: Keep the water clear and free of algae ${tag}`);
  await expect(basket).toBeVisible();
  await expect(heading.first()).toBeVisible();

  // At rest.
  await page.mouse.move(5, 700);
  await slideUnder(basket);
  await expectOnTop(page, basket, "at rest");

  // Hovered (the case first seen: the row's cells showed through its name).
  await basket.locator(".tt-tree .tp-nm").hover();
  await shot(page, "sticky-1-hovered", basket);
  await expectOnTop(page, basket, "hovered");
  await slideUnder(loose);
  await loose.locator(".tt-tree .tp-nm").hover();
  await expectOnTop(page, loose, "hovered, under Not under a functional failure");
  await fn.locator(".tt-tree .tp-nm").hover();
  const fnCheck = await onTop(page, fn);
  expect(fnCheck.hits, "function row hovered").toEqual([]);
  expect(fnCheck.same, "function row hovered").toBe(true);

  // Picked (the ⋯ on show), then hovered as well.
  await basket.locator(".tt-tree .tp-nm").click();
  await expect(basket).toHaveAttribute("aria-selected", "true");
  const closeDetails = page.getByRole("button", { name: "Close the details" });
  if (await closeDetails.isVisible()) await closeDetails.click();
  await slideUnder(basket);
  await expectOnTop(page, basket, "picked and hovered");
  await page.mouse.move(5, 700);
  await expectOnTop(page, basket, "picked");

  // Keyboard focus: down to the next row and back.
  await basket.focus();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowUp");
  await expect(basket).toBeFocused();
  await slideUnder(basket);
  await expectOnTop(page, basket, "keyboard focus");
  await shot(page, "sticky-2-keyboard-focus", basket);

  // Its menu open (from the ⋯ button).
  await slideUnder(basket);
  await basket.locator(".tt-tree .tp-nm").hover();
  await basket.locator(".tt-more").click();
  await expect(page.getByRole("menu", { name: new RegExp(`^Actions for Failure mode: Basket blocked ${tag}`) })).toBeVisible();
  await expect(basket).toHaveClass(/menu-open/);
  await expectOnTop(page, basket, "menu open");
  await shot(page, "sticky-3-menu-open", basket);
  await page.keyboard.press("Escape");

  // A cell being edited, scrolled partly under the tree column.
  const effects = basket.getByRole("gridcell").filter({ hasText: "Floor visible at the deep end" });
  if (await closeDetails.isVisible()) await closeDetails.click();
  await scroller(page).evaluate((el) => { el.scrollLeft = 0; });
  await effects.dblclick();
  const editor = basket.getByRole("textbox");
  await expect(editor).toBeFocused();
  await slideUnder(basket);
  const editing = await onTop(page, basket);
  expect(editing.hits, "editing").toEqual([]);
  expect(editing.same, "editing").toBe(true);
  await shot(page, "sticky-4-editing", basket);
  await editor.press("Escape");
  await expect(editor).toHaveCount(0);

  // Full screen.
  await page.mouse.move(5, 700);
  await basket.focus();
  await page.keyboard.press("f");
  await expect(page.locator(".tx.is-full")).toBeVisible();
  await slideUnder(basket);
  await basket.locator(".tt-tree .tp-nm").hover();
  await expectOnTop(page, basket, "full screen, hovered");
  await page.getByRole("button", { name: "Exit full screen" }).click();
  await expect(page.locator(".tx.is-full")).toHaveCount(0);
  await expectHealthy(page, problems, { label: "RCM table scrolled sideways", root: ".tx" });

  // A pinned branch.
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&pin=${p.pump.id}&tab=rcm`);
  await expect(basket).toBeVisible();
  expect(await scroller(page).evaluate((el) => el.scrollWidth - el.clientWidth)).toBeGreaterThan(300); // the columns and width are remembered
  await slideUnder(basket);
  await basket.locator(".tt-tree .tp-nm").hover();
  await expectOnTop(page, basket, "pinned branch, hovered");
  await shot(page, "sticky-5-pinned-hovered", basket);
  await expectHealthy(page, problems, { label: "RCM table scrolled sideways, pinned", root: ".tx" });
});
