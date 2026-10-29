// Rearranging the RCM tree by drag and drop, on the Explorer's RCM tab
// (Operate › Assets › Explorer › RCM). Each drag is one batch, all or
// nothing, with a toast that says what moved and offers Undo:
// - a function onto another position, and back with Undo;
// - a functional failure onto another function's standard, and before a
//   sibling (its place and that one's standard);
// - two failure modes picked with Ctrl-click, onto another functional
//   failure (a count on the dragged label), undone in one go;
// - a standard onto another function: it moves alone, its failure falls to
//   "No standard", and Undo puts the breach back;
// - a task, from its failure mode's Task cell, onto another failure mode;
// - a refusal the server knows (a same-named failure mode on the other
//   position) shows before the drop: the no-drop cursor and the reason, and
//   dropping writes nothing;
// - nothing on the page moves while dragging;
// - at 400 px there's no dragging: the row menu's Move to… does the move.
// Each test makes its own plant through the API and pins it (?pin=), so its
// rows are at the top of the tree.
//
// With SMOKE_SHOTS_DIR set, it saves screenshots at 1280 and 400 px.
import { test, expect, open, postOk } from "./health.js";
import { frameOf } from "./explorer.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";

// A plant with two pumps. Pump A: "Pump water" with two standards (No flow
// breaches the first, with two modes and a task; Low pressure the second,
// with one mode) and "Contain the water". Pump B: "Pump more water" with one
// standard and a failure with a mode named like one on Pump A.
async function plant(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const top = await post(`${M}/positions`, { name: `Drag plant ${tag}` });
  const a = await post(`${M}/positions`, { name: `Pump A ${tag}`, parent_id: top.id });
  const b = await post(`${M}/positions`, { name: `Pump B ${tag}`, parent_id: top.id });
  const water = await post(`${M}/positions/${a.id}/functions`, { text: `Pump water ${tag}` });
  const flow = await post(`${M}/functions/${water.id}/standards`, { text: `At least 50 L/s ${tag}` });
  const bar = await post(`${M}/functions/${water.id}/standards`, { text: `At 4 bar ${tag}` });
  const noFlow = await post(`${M}/functions/${water.id}/failures`, { text: `No flow ${tag}`, standard_id: flow.id });
  const lowP = await post(`${M}/functions/${water.id}/failures`, { text: `Low pressure ${tag}`, standard_id: bar.id });
  const bearing = await post(`${M}/positions/${a.id}/failure-modes`, { text: `Bearing seizes ${tag}`, functional_failure_id: noFlow.id });
  const seal = await post(`${M}/positions/${a.id}/failure-modes`, { text: `Seal leaks ${tag}`, functional_failure_id: noFlow.id });
  const impeller = await post(`${M}/positions/${a.id}/failure-modes`, { text: `Impeller worn ${tag}`, functional_failure_id: lowP.id });
  const task = await post(`${M}/failure-modes/${bearing.id}/tasks`, { name: `Grease bearings ${tag}`, interval: 3 });
  const contain = await post(`${M}/positions/${a.id}/functions`, { text: `Contain the water ${tag}` });
  const more = await post(`${M}/positions/${b.id}/functions`, { text: `Pump more water ${tag}` });
  const twenty = await post(`${M}/functions/${more.id}/standards`, { text: `At least 20 L/s ${tag}` });
  const noFlowB = await post(`${M}/functions/${more.id}/failures`, { text: `No flow at B ${tag}`, standard_id: twenty.id });
  await post(`${M}/positions/${b.id}/failure-modes`, { text: `Seal leaks ${tag}`, functional_failure_id: noFlowB.id });
  return { top, a, b, water, flow, bar, noFlow, lowP, bearing, seal, impeller, task, contain, more, twenty, noFlowB };
}

const table = (page) => page.getByRole("treegrid", { name: /and their RCM/ });
const trow = (page, name) => table(page).getByRole("row", { name: new RegExp(name) });
const toast = (page) => page.locator(".rcm-toast");
const ghost = (page) => page.locator(".rcm-ghost");
const settled = async (page) => {
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
  await page.waitForTimeout(250);
};
const rcmOf = async (request, id) => (await (await request.get(`${M}/positions/${id}/rcm?scope=this`)).json()).positions[0];

// Open the plant pinned on the RCM tab, every row open (the ⋯ menu's "Open everything").
async function openPlant(page, p, width = 1280) {
  await page.setViewportSize({ width, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.top.id}&pin=${p.top.id}&tab=rcm`);
  await expect(table(page)).toBeVisible();
  await page.getByRole("button", { name: "Tree options" }).click();
  await page.getByRole("menuitemradio", { name: "Open everything" }).click();
  await page.keyboard.press("Escape");
  await settled(page);
}

// Press on a row's name (or a locator inside the row), move past the start
// distance, go to the target row at `frac` of its height (0.5: into; 0.12:
// before; 0.88: after), rest there until the server has answered, and let go
// (unless `hold`).
async function dragTo(page, from, to, { frac = 0.5, hold = false, handle = null } = {}) {
  await settled(page); // the tree read again after the last move, its rows where they'll stay
  const grab = handle || from.locator(".tp-nm");
  const a = await grab.boundingBox();
  const b = await to.locator(".tp-nm").boundingBox();
  const row = await to.boundingBox();
  await page.mouse.move(a.x + Math.min(20, a.width / 2), a.y + a.height / 2);
  await page.mouse.down();
  await page.mouse.move(a.x + 30, a.y + a.height / 2 + 8, { steps: 3 });
  await page.mouse.move(b.x + 20, row.y + row.height * frac, { steps: 8 });
  await expect(ghost(page)).toBeVisible();
  await expect(ghost(page)).not.toHaveClass(/is-checking/, { timeout: 5_000 });
  if (!hold) await page.mouse.up();
}

test("a function dragged onto another position moves there with everything under it; Undo puts it back", async ({ page, request }) => {
  const tag = `f${Date.now()}`;
  const p = await plant(request, tag);
  await openPlant(page, p);
  await dragTo(page, trow(page, `^Function: Contain the water ${tag}`), trow(page, `^Pump B ${tag}`));
  await expect(toast(page)).toContainText(`Moved “Contain the water ${tag}” to “Pump B ${tag}”.`);
  await expect.poll(async () => (await rcmOf(request, p.b.id)).functions.map((f) => f.text)).toEqual([`Pump more water ${tag}`, `Contain the water ${tag}`]);
  await toast(page).getByRole("button", { name: "Undo" }).click();
  await expect(toast(page)).toContainText("Undone");
  await expect.poll(async () => (await rcmOf(request, p.a.id)).functions.map((f) => f.text)).toEqual([`Pump water ${tag}`, `Contain the water ${tag}`]);
  // Before a sibling: the order.
  await dragTo(page, trow(page, `^Function: Contain the water ${tag}`), trow(page, `^Function: Pump water ${tag}`), { frac: 0.1 });
  await expect.poll(async () => (await rcmOf(request, p.a.id)).functions.map((f) => f.text)).toEqual([`Contain the water ${tag}`, `Pump water ${tag}`]);
  // Ctrl+Z undoes too.
  await page.keyboard.press("Control+z");
  await expect.poll(async () => (await rcmOf(request, p.a.id)).functions.map((f) => f.text)).toEqual([`Pump water ${tag}`, `Contain the water ${tag}`]);
});

test("a functional failure onto another function's standard, and before a sibling (taking its standard)", async ({ page, request }) => {
  const tag = `x${Date.now()}`;
  const p = await plant(request, tag);
  await openPlant(page, p);
  if (SHOTS) {
    await dragTo(page, trow(page, `^Functional failure: Low pressure ${tag}`), trow(page, `^Functional failure: No flow ${tag}`), { frac: 0.12, hold: true });
    await page.screenshot({ path: `${SHOTS}/drag-before-sibling-1280.png` });
    await page.mouse.up();
  } else {
    await dragTo(page, trow(page, `^Functional failure: Low pressure ${tag}`), trow(page, `^Functional failure: No flow ${tag}`), { frac: 0.12 });
  }
  await expect.poll(async () => {
    const fn = (await rcmOf(request, p.a.id)).functions[0];
    return fn.failures.map((f) => [f.text, f.standard?.text]);
  }).toEqual([[`Low pressure ${tag}`, `At least 50 L/s ${tag}`], [`No flow ${tag}`, `At least 50 L/s ${tag}`]]);
  await dragTo(page, trow(page, `^Functional failure: Low pressure ${tag}`), trow(page, `^Standard: At least 20 L/s ${tag}`));
  await expect(toast(page)).toContainText(`under “Pump more water ${tag}”`);
  await expect.poll(async () => (await rcmOf(request, p.b.id)).functions[0].failures.map((f) => [f.text, f.standard?.text]))
    .toContainEqual([`Low pressure ${tag}`, `At least 20 L/s ${tag}`]);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/drag-toast-undo-1280.png` });
});

test("two failure modes picked with Ctrl-click drag together onto another functional failure; one Undo puts both back", async ({ page, request }) => {
  const tag = `m${Date.now()}`;
  const p = await plant(request, tag);
  await openPlant(page, p);
  const bearing = trow(page, `^Failure mode: Bearing seizes ${tag}`);
  const seal = trow(page, `^Failure mode: Seal leaks ${tag}`).first();
  await bearing.locator(".tp-nm").click();
  await seal.locator(".tp-nm").click({ modifiers: ["ControlOrMeta"] });
  await expect(table(page).locator(".tp-row.picked")).toHaveCount(2);
  await dragTo(page, seal, trow(page, `^Functional failure: Low pressure ${tag}`), { hold: true });
  await expect(ghost(page).locator(".rcm-ghost-n")).toHaveText("2");
  await expect(ghost(page)).toContainText("2 failure modes");
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/drag-two-modes-1280.png` });
  await page.mouse.up();
  await expect(toast(page)).toContainText(`Moved 2 failure modes under “Low pressure ${tag}”.`);
  await expect.poll(async () => (await rcmOf(request, p.a.id)).functions[0].failures.map((f) => f.modes.length)).toEqual([0, 3]);
  await toast(page).getByRole("button", { name: "Undo" }).click();
  await expect.poll(async () => (await rcmOf(request, p.a.id)).functions[0].failures.map((f) => f.modes.map((m) => m.text)))
    .toEqual([[`Bearing seizes ${tag}`, `Seal leaks ${tag}`], [`Impeller worn ${tag}`]]);
});

test("a standard dragged to another function moves alone; its failure falls to No standard; Undo puts the breach back", async ({ page, request }) => {
  const tag = `s${Date.now()}`;
  const p = await plant(request, tag);
  await openPlant(page, p);
  await dragTo(page, trow(page, `^Standard: At 4 bar ${tag}`), trow(page, `^Function: Pump more water ${tag}`), { hold: true });
  await expect(ghost(page)).toContainText("Its functional failure stays here, under No standard.");
  await page.mouse.up();
  await expect(toast(page)).toContainText(`Moved “At 4 bar ${tag}” to “Pump more water ${tag}”.`);
  await expect(table(page).locator(".tp-row.tt-nostd")).toHaveCount(1); // its failure, under No standard
  await expect.poll(async () => (await rcmOf(request, p.b.id)).functions[0].standards.map((s) => s.text)).toEqual([`At least 20 L/s ${tag}`, `At 4 bar ${tag}`]);
  await expect.poll(async () => (await rcmOf(request, p.a.id)).functions[0].failures[1].standard).toBeNull();
  await toast(page).getByRole("button", { name: "Undo" }).click();
  await expect.poll(async () => (await rcmOf(request, p.a.id)).functions[0].failures[1].standard?.text).toBe(`At 4 bar ${tag}`);
  await expect.poll(async () => (await rcmOf(request, p.a.id)).functions[0].standards.map((s) => s.text)).toEqual([`At least 50 L/s ${tag}`, `At 4 bar ${tag}`]);
});

test("a task dragged from its failure mode's Task cell moves to another failure mode", async ({ page, request }) => {
  const tag = `t${Date.now()}`;
  const p = await plant(request, tag);
  await openPlant(page, p);
  const bearing = trow(page, `^Failure mode: Bearing seizes ${tag}`);
  const cell = bearing.locator(".tt-task-drag");
  await expect(cell).toContainText(`Grease bearings ${tag}`);
  await dragTo(page, bearing, trow(page, `^Failure mode: Impeller worn ${tag}`), { handle: cell });
  await expect(toast(page)).toContainText(`Moved the task “Grease bearings ${tag}” to “Impeller worn ${tag}”.`);
  await expect.poll(async () => {
    const ffs = (await rcmOf(request, p.a.id)).functions[0].failures;
    return [ffs[0].modes[0].tasks.length, ffs[1].modes[0].tasks.map((t) => t.name)];
  }).toEqual([0, [`Grease bearings ${tag}`]]);
});

test("a refusal shows before the drop (no-drop cursor and the reason); dropping writes nothing; nothing moves while dragging", async ({ page, request }) => {
  const tag = `r${Date.now()}`;
  const p = await plant(request, tag);
  await openPlant(page, p);
  const before = await frameOf(page);
  const seal = trow(page, `^Failure mode: Seal leaks ${tag}`).first();
  await dragTo(page, seal, trow(page, `^Functional failure: No flow at B ${tag}`), { hold: true });
  await expect(ghost(page)).toHaveClass(/is-no/);
  await expect(ghost(page)).toContainText(`Can't go here: Pump B ${tag} already has the failure mode Seal leaks ${tag}`);
  expect(await page.evaluate(() => document.documentElement.classList.contains("rcm-nodrop"))).toBe(true);
  expect(await page.evaluate(() => getComputedStyle(document.querySelector(".tp-body .tp-row")).cursor)).toBe("no-drop");
  await expect(table(page).locator(".tp-row.drop-no")).toHaveCount(1);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/drag-refused-1280.png` });
  // Nothing on the page moved: every row on screen, the boxes, the scroll.
  const during = await frameOf(page);
  expect(during.rows).toEqual(before.rows);
  expect(during.boxes).toEqual(before.boxes);
  expect(during.scrollTop).toBe(before.scrollTop);
  await page.mouse.up();
  await expect(page.locator(".tt-msg.error")).toContainText("Not moved");
  expect((await rcmOf(request, p.a.id)).functions[0].failures[0].modes.map((m) => m.text)).toEqual([`Bearing seizes ${tag}`, `Seal leaks ${tag}`]);
  // What the tree knows is said at once (no server call): a mode onto a function.
  await dragTo(page, seal, trow(page, `^Function: Contain the water ${tag}`), { hold: true });
  await expect(ghost(page)).toContainText("under a functional failure");
  await page.keyboard.press("Escape");
  await expect(ghost(page)).toHaveCount(0);
});

test("at 400 px there's no dragging: the row menu's Move to… moves it, with Undo", async ({ page, request }) => {
  const tag = `p${Date.now()}`;
  const p = await plant(request, tag);
  await openPlant(page, p, 400);
  await expect(table(page).locator(".tt-grip")).toHaveCount(0);
  const row = trow(page, `^Function: Contain the water ${tag}`);
  await row.getByRole("button", { name: "Actions", exact: true }).click();
  const menu = page.getByRole("menu");
  await expect(menu.getByRole("menuitem", { name: "Move up" })).toBeVisible();
  await menu.getByRole("menuitem", { name: "Move to another position…" }).click();
  const dlg = page.getByRole("dialog", { name: `Move “Contain the water ${tag}”` });
  await expect(dlg).toBeVisible();
  await dlg.getByRole("listbox", { name: "Where it goes" }).selectOption(p.b.id);
  await expect(dlg.getByRole("status")).toContainText(`to “Pump B ${tag}”`);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/move-to-400.png` });
  await dlg.getByRole("button", { name: "Move", exact: true }).click();
  await expect(dlg).toHaveCount(0);
  await expect(toast(page)).toContainText("Moved");
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/move-toast-400.png` });
  await expect.poll(async () => (await rcmOf(request, p.b.id)).functions.map((f) => f.text)).toContain(`Contain the water ${tag}`);
  await toast(page).getByRole("button", { name: "Undo" }).click();
  await expect.poll(async () => (await rcmOf(request, p.a.id)).functions.map((f) => f.text)).toEqual([`Pump water ${tag}`, `Contain the water ${tag}`]);
});
