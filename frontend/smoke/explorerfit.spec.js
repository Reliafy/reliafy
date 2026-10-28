// The Explorer's RCM table on a laptop, and saying so when things go wrong
// (Operate › Assets › Explorer, the RCM tab): at 1280x720 the usual columns
// fit (none cut off, the interval in the Task cell), with the side panel open
// the four main columns still show, and a soft shadow says there's more to the
// side only when there is; a function's text is kept to 200 characters where
// it's typed (a longer one saved before stays as it is); a save that doesn't
// go through (offline) says so in plain words and keeps what was typed; and a
// crumb at the whole tree's one top row un-pins rather than pinning it.
// Each test makes its own small plant through the API. The names start
// "Yard" so they sort after the other specs' plants ("Rcm", "Tree", "Works"), which
// share the server and expect their rows near the top.
// With SMOKE_SHOTS_DIR set, it also saves screenshots there (for the pull request).
import { test, expect, open, expectHealthy } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};

async function plant(request, tag) {
  const send = async (method, path, data) => {
    const res = await request.fetch(path, { method, data });
    expect(res.ok(), `${path}: ${res.status()} ${await res.text()}`).toBeTruthy();
    return res.json();
  };
  const post = (path, data) => send("POST", path, data);
  const top = await post(`${M}/positions`, { name: `Yard pool ${tag}` });
  const circ = await post(`${M}/positions`, { name: `Yard circulation ${tag}`, parent_id: top.id });
  const pump = await post(`${M}/positions`, { name: `Yard pump ${tag}`, parent_id: circ.id });
  const fn = await post(`${M}/positions/${pump.id}/functions`, { text: `Circulate the water ${tag}` });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `No flow ${tag}` });
  const basket = await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Basket blocked ${tag}`, functional_failure_id: ff.id });
  await send("PUT", `${M}/failure-modes/${basket.id}/decision`, {
    consequence: "operational", decision: { outcome: "fixed_interval", task: "Empty the pump basket", interval: 12, interval_unit: "months" },
  });
  const motor = await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Motor fails ${tag}`, functional_failure_id: ff.id });
  await send("PATCH", `${M}/failure-modes/${motor.id}`, { effects: "No circulation: the water goes green within two or three days in summer" });
  return { top, circ, pump, fn, ff, basket, motor };
}

const table = (page) => page.getByRole("treegrid", { name: /and their RCM/ });
const trow = (page, name) => table(page).getByRole("row", { name: new RegExp(name) });
const fresh = async (page) => {
  // The usual columns (nothing chosen on this device yet).
  await page.addInitScript(() => {
    try {
      if (!sessionStorage.getItem("fit-cleared")) {
        localStorage.removeItem("reliafy.rcmWorksheet");
        sessionStorage.setItem("fit-cleared", "1");
      }
    } catch { /* fine */ }
  });
};
// Each column header: cut short (its text wider than it), or past the scroll area's visible edge.
const headers = (page) => page.evaluate(() => {
  const sc = document.querySelector(".tp-scroll");
  const right = sc.getBoundingClientRect().left + sc.clientWidth;
  return [...document.querySelectorAll(".tt-head [role=columnheader]")].map((h) => ({
    name: h.textContent.trim(),
    clipped: h.scrollWidth > h.clientWidth + 1 || h.getBoundingClientRect().right > right + 1,
  }));
});
const shade = (page) => page.evaluate(() => {
  const o = (s) => Number(document.querySelector(s)?.style.opacity || 0);
  const sc = document.querySelector(".tp-scroll");
  return { left: o(".tt-shade-l"), right: o(".tt-shade-r"), more: sc.scrollWidth - sc.clientWidth };
});
// The connection's own errors while offline are what the test is about.
const offlineNoise = (problems) => {
  for (let i = problems.length - 1; i >= 0; i -= 1) if (/ERR_INTERNET_DISCONNECTED|Failed to fetch/.test(problems[i])) problems.splice(i, 1);
};

test("at 1280x720 the RCM table fits: no column cut off, the interval in the Task cell; a shadow only when there's more to the side", async ({ page, request, problems }) => {
  const tag = `w${Date.now()}`;
  const p = await plant(request, tag);
  await fresh(page);
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  await expect(table(page)).toBeVisible();
  const basket = trow(page, `^Failure mode: Basket blocked ${tag}`);
  await expect(basket).toBeVisible();
  // The usual columns under 1400 px: no Interval, no Evidence check; every header whole.
  expect((await headers(page)).map((h) => h.name)).toEqual([
    "Position › function, standard, failure or mode", "Failure effects", "Consequence", "Decision", "Task",
  ]);
  expect((await headers(page)).filter((h) => h.clipped)).toEqual([]);
  await expect(basket.getByRole("gridcell").nth(3)).toHaveText("Empty the pump basket · every 12 months");
  // A cut-off cell's tooltip is its whole text; the edit hint isn't over it.
  const effects = trow(page, `^Failure mode: Motor fails ${tag}`).getByRole("gridcell").first();
  await expect(effects).toHaveAttribute("title", "No circulation: the water goes green within two or three days in summer");
  await expect(effects).toHaveAttribute("aria-description", "Double-click to edit");
  // Everything fits: no shadow.
  expect(await shade(page)).toEqual({ left: 0, right: 0, more: 0 });
  // At least 18 rows in view.
  const rows = await page.evaluate(() => {
    const sc = document.querySelector(".tp-scroll").getBoundingClientRect();
    const head = document.querySelector(".tt-head").getBoundingClientRect().height;
    return [...document.querySelectorAll(".tp-body .tp-row")].filter((r) => {
      const b = r.getBoundingClientRect();
      return b.top >= sc.top + head - 1 && b.bottom <= sc.bottom + 1;
    }).length;
  });
  expect(rows).toBeGreaterThanOrEqual(Math.min(18, await page.locator(".tp-body .tp-row").count()));
  await shot(page, "fit-1-1280-usual-columns");

  // The side panel open: the four main columns still show, whole.
  await basket.locator(".tt-tree").click();
  await expect(page.getByRole("complementary", { name: "Details" })).toBeVisible();
  const open4 = await headers(page);
  for (const name of ["Failure effects", "Consequence", "Decision", "Task"]) {
    expect(open4.find((h) => h.name === name), name).toEqual({ name, clipped: false });
  }
  await shot(page, "fit-2-1280-panel-open");
  await page.getByRole("button", { name: "Close the details" }).click();

  // More columns than fit: the table scrolls sideways, and a shadow shows on the side with more.
  await page.getByRole("button", { name: "Columns", exact: true }).click();
  const pop = page.getByRole("group", { name: "Columns to show" });
  for (const n of ["Interval", "Performance standard", "Mode notes", "Decision notes", "What the evidence shows"]) {
    await pop.getByRole("checkbox", { name: n }).check();
  }
  await page.keyboard.press("Escape");
  await expect(table(page).getByRole("columnheader", { name: "Interval" })).toBeVisible();
  await expect(basket.getByRole("gridcell", { name: "Empty the pump basket", exact: true })).toBeVisible(); // its own column now
  await expect.poll(async () => (await shade(page)).right).toBe(1);
  const start = await shade(page);
  expect(start.more).toBeGreaterThan(0);
  expect(start.left).toBe(0);
  await shot(page, "fit-3-shadow-right");
  await page.locator(".tp-scroll").evaluate((el) => { el.scrollLeft = 60; });
  await expect.poll(async () => (await shade(page)).left).toBe(1);
  expect((await shade(page)).right).toBe(1);
  await page.locator(".tp-scroll").evaluate((el) => { el.scrollLeft = el.scrollWidth; });
  await expect.poll(async () => (await shade(page)).right).toBe(0);
  expect((await shade(page)).left).toBe(1);
  await shot(page, "fit-4-shadow-left");
  // The choice is remembered; Show the usual columns puts them back (and the shadow goes).
  await page.waitForTimeout(400);
  await page.reload();
  await expect(table(page).getByRole("columnheader", { name: "Interval" })).toBeVisible();
  await page.getByRole("button", { name: "Columns", exact: true }).click();
  await expect(page.getByRole("button", { name: "Columns", exact: true })).toHaveAttribute("title", "Choose which columns to show");
  await page.getByRole("button", { name: "Show the usual columns" }).click();
  await page.keyboard.press("Escape");
  await expect(table(page).getByRole("columnheader", { name: "Interval" })).toHaveCount(0);
  await expect.poll(async () => shade(page)).toEqual({ left: 0, right: 0, more: 0 });
  // At 1920 the usual columns include the Interval.
  await page.setViewportSize({ width: 1920, height: 1080 });
  await expect(table(page).getByRole("columnheader", { name: "Interval" })).toBeVisible();
  expect((await headers(page)).filter((h) => h.clipped)).toEqual([]);
  await expectHealthy(page, problems, { label: "rcm table fits", root: ".tx" });
});

test("a function's text is kept to 200 characters where it's typed; one saved longer before stays as it is", async ({ page, request, problems }) => {
  const tag = `c${Date.now()}`;
  const p = await plant(request, tag);
  const long = `Keep the pool water moving ${tag} `.repeat(12).trim(); // longer than 200, saved before the limit
  const res = await request.post(`${M}/positions/${p.pump.id}/functions`, { data: { text: long } });
  expect(res.ok()).toBeTruthy();
  const longFn = await res.json();
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  await expect(table(page)).toBeVisible();

  // Add function: a live counter, the nudge, amber near the limit, and the box stops at 200.
  await page.locator(".tt-headslot").getByRole("button", { name: "Add function" }).click();
  const dialog = page.getByRole("dialog", { name: "Add a function" });
  const box = dialog.getByRole("textbox", { name: "What must this position do?" });
  await expect(dialog).toContainText("Keep it short. Put the standard of performance in its own field.");
  await box.fill("a".repeat(190));
  await expect(dialog.locator(".char-count")).toHaveText("190 / 200");
  await expect(dialog.locator(".char-count")).toHaveClass(/near/);
  await shot(page, "cap-1-add-function-190");
  await box.press("End");
  await page.keyboard.type("b".repeat(30));
  await expect(box).toHaveValue("a".repeat(190) + "b".repeat(10));
  await expect(dialog.locator(".char-count")).toHaveText("200 / 200");
  await shot(page, "cap-2-add-function-200");
  await dialog.getByRole("button", { name: "Cancel" }).click();

  // The longer one saved before: still all there; Edit description shows it red and won't save a change until it's short enough.
  const longRow = trow(page, `^Function: Keep the pool water moving ${tag}`);
  await expect(longRow.locator(".tp-nm")).toHaveAttribute("title", long);
  await longRow.locator(".tt-tree").click({ button: "right" });
  await page.getByRole("menu").getByRole("menuitem", { name: "Edit description" }).click();
  const edit = page.getByRole("dialog", { name: "Edit the function" });
  const editBox = edit.getByRole("textbox");
  await expect(editBox).toHaveValue(long);
  await expect(edit.locator(".char-count")).toHaveClass(/over/);
  await expect(edit.getByRole("button", { name: "Save" })).toBeEnabled(); // untouched: nothing to stop
  await editBox.press("End");
  await page.keyboard.press("Backspace");
  await expect(edit.getByRole("button", { name: "Save" })).toBeDisabled();
  await expect(edit).toContainText("Shorten it to 200 characters or fewer to save the change");
  await editBox.fill(`Keep the pool water moving ${tag}`);
  await expect(edit.getByRole("button", { name: "Save" })).toBeEnabled();
  await edit.getByRole("button", { name: "Cancel" }).click();
  // The panel's Description field: the same counter, red, and the stored text unchanged.
  await longRow.locator(".tt-tree").click();
  const panel = page.locator("aside.rw-panel");
  await expect(panel).toBeVisible();
  await expect(panel.locator(".rw-flabel .char-count")).toHaveClass(/over/);
  await expect(panel).toContainText("Keep it short. Put the standard of performance in its own field.");
  // The heading: two lines at most, the whole text in its tooltip.
  const title = panel.locator(".rw-panel-title");
  await expect(title).toHaveAttribute("title", long);
  expect(await title.evaluate((h) => h.getBoundingClientRect().height)).toBeLessThan(50);
  const after = await (await request.get(`${M}/rcm`)).json();
  const stored = after.positions.find((x) => x.id === p.pump.id).functions.find((f) => f.id === longFn.id);
  expect(stored.text).toBe(long);
  await expectHealthy(page, problems, { label: "function text cap", root: ".tx" });
});

test("offline, a save says so in plain words and keeps what was typed: the dialog, and an edit in a cell", async ({ page, context, request, problems }) => {
  const tag = `o${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  const basket = trow(page, `^Failure mode: Basket blocked ${tag}`);
  await expect(basket).toBeVisible();

  await context.setOffline(true);
  // Add function: the dialog stays open with the text, and says what to do.
  await page.locator(".tt-headslot").getByRole("button", { name: "Add function" }).click();
  const dialog = page.getByRole("dialog", { name: "Add a function" });
  await dialog.getByRole("textbox").fill(`Hold the water ${tag}`);
  await dialog.getByRole("button", { name: "Add function" }).click();
  await expect(dialog.getByRole("alert")).toHaveText("Couldn't save. Check your connection and try again.");
  await expect(dialog.getByRole("textbox")).toHaveValue(`Hold the water ${tag}`);
  await expect(page.getByText("Failed to fetch")).toHaveCount(0);
  await shot(page, "offline-1-add-function");
  await dialog.getByRole("button", { name: "Cancel" }).click();

  // A cell edited in place: it doesn't revert; the text stays, with the reason in the heading.
  const effects = basket.getByRole("gridcell").first();
  await effects.dblclick();
  const editor = basket.getByRole("textbox");
  await editor.fill(`Pump runs dry ${tag}`);
  await editor.press("Enter");
  await expect(page.locator(".tt-msg.error")).toHaveText("Couldn't save. Check your connection and try again.");
  await expect(editor).toHaveValue(`Pump runs dry ${tag}`);
  await expect(editor).toBeFocused();
  await shot(page, "offline-2-cell-edit");
  // Back online: Enter saves it.
  await context.setOffline(false);
  await editor.press("Enter");
  await expect(page.locator(".tt-msg")).toHaveText("Saved.");
  await expect(editor).toHaveCount(0);
  await expect(effects).toHaveText(`Pump runs dry ${tag}`);
  offlineNoise(problems);
  await expectHealthy(page, problems, { label: "offline saves", root: ".tx" });
});

test("pinned: the crumb for the whole tree's one top row shows everything instead of pinning it", async ({ page, request, problems }) => {
  const tag = `r${Date.now()}`;
  const p = await plant(request, tag);
  // A workspace whose tree has one top row (this plant): the other specs' plants left out.
  await page.route(`**${M}/tree`, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    const mine = new Set([p.top.id]);
    for (let grew = true; grew;) {
      grew = false;
      for (const x of body.positions) if (x.parent_id && mine.has(x.parent_id) && !mine.has(x.id)) { mine.add(x.id); grew = true; }
    }
    body.positions = body.positions.filter((x) => mine.has(x.id)).map((x) => ({ ...x, location_id: null }));
    body.locations = [];
    for (const k of ["spares", "unhomed", "items"]) if (Array.isArray(body[k])) body[k] = [];
    await route.fulfill({ response: res, json: body });
  });
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&pin=${p.pump.id}`);
  const bar = page.locator(".tt-head").getByRole("group", { name: "Pinned branch" });
  await expect(bar).toContainText(`Pinned: Yard pump ${tag}`);
  const crumbs = page.locator(".tt-headslot").getByRole("navigation", { name: "Breadcrumb" });
  // A crumb above the pin that isn't the top: the pin moves up to it, as before.
  await crumbs.getByRole("button", { name: `Yard circulation ${tag}` }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("pin")).toBe(p.circ.id);
  // The ⋯ badge counts the pin.
  const changed = async () => Number((await page.getByRole("button", { name: /^Tree options/ }).getAttribute("aria-label")).match(/(\d+) changed/)?.[1] || 0);
  const pinned = await changed();
  expect(pinned).toBeGreaterThanOrEqual(1);
  // The whole tree's one top row: everything shows, nothing pinned, the pin no longer counted.
  await crumbs.getByRole("button", { name: `Yard pool ${tag}` }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("pin")).toBe(null);
  await expect(bar).toHaveCount(0);
  await expect.poll(changed).toBe(pinned - 1);
  await expect(page.getByRole("treeitem", { name: new RegExp(`^Yard pool ${tag}`) })).toHaveAttribute("aria-selected", "true");
  await expectHealthy(page, problems, { label: "pin crumb at the top", root: ".tx" });
});
