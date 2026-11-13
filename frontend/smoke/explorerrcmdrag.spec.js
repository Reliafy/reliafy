// Rearranging the RCM tree by drag and drop, on the Explorer's RCM tab
// (Assets › Explorer › RCM). Each drag is one batch, all or
// nothing, with a toast that says what moved and offers Undo:
// - a function onto another position, and back with Undo;
// - a functional failure onto another function's standard, and before a
//   sibling (its place and that one's standard);
// - two failure modes picked with Ctrl-click, onto another functional
//   failure (a count on the dragged label), undone in one go;
// - a standard onto another function on another position: it carries its
//   functional failures, their failure modes and tasks (the label says
//   what moves), nothing on the page shifts while dragging, and one Undo
//   puts all of it back; a refusal under it shows before the drop; at 400 px
//   the standard's Move to… does the same;
// - a task, from its failure mode's Task cell, onto another failure mode;
// - a task's own row is dragged to copy, never to move ("Link here", a +
//   badge): onto a sibling failure mode, which then has it too (Serves 2 here);
//   onto a function it's refused quietly; the row menu's Link to another
//   failure mode… does the same from the keyboard;
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
import { frameOf, pickPlace } from "./explorer.js";

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
  // The tree and its RCM read first (a position's row says what it holds): "Open everything" opens
  // the rows there are, so chosen before they're in it would leave the plant's rows closed.
  await expect(trow(page, `^Pump A `).getByText(/to decide/)).toBeVisible();
  await page.getByRole("button", { name: "Tree options" }).click();
  await page.getByRole("menuitemradio", { name: "Open everything" }).click();
  await page.keyboard.press("Escape");
  await expect(table(page).getByRole("row", { name: /^Failure mode: Impeller worn / }).first()).toBeVisible();
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
  // Ctrl+Z undoes too, but only once this drop's own toast (with its Undo) is on screen: the
  // server has the new order a moment before the page has the answer, and a key pressed in
  // that gap has nothing to undo. Wait for the toast, not for the clock.
  await expect(toast(page)).toContainText(`Moved “Contain the water ${tag}”`);
  await expect(toast(page).getByRole("button", { name: "Undo" })).toBeEnabled();
  await page.keyboard.press("Control+z");
  await expect(toast(page)).toContainText("Undone");
  await expect.poll(async () => (await rcmOf(request, p.a.id)).functions.map((f) => f.text), { timeout: 30_000 }).toEqual([`Pump water ${tag}`, `Contain the water ${tag}`]);
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
  // Close the first move's toast, so the one read next is the second move's
  // (on a slow runner the first can still be showing when the second lands).
  await toast(page).getByRole("button", { name: "Dismiss" }).click();
  await expect(toast(page)).toBeHidden();
  await dragTo(page, trow(page, `^Functional failure: Low pressure ${tag}`), trow(page, `^Performance standard: At least 20 L/s ${tag}`));
  await expect.poll(async () => (await rcmOf(request, p.b.id)).functions[0].failures.map((f) => [f.text, f.standard?.text]), { timeout: 20_000 })
    .toContainEqual([`Low pressure ${tag}`, `At least 20 L/s ${tag}`]);
  await expect(toast(page)).toContainText(`under “Pump more water ${tag}”`);
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

test("a standard dragged to a function on another position carries its failures, modes and tasks; one Undo puts it all back", async ({ page, request }) => {
  const tag = `s${Date.now()}`;
  const p = await plant(request, tag);
  // A task on the mode under "At 4 bar", so the task goes too.
  await postOk(request, `${M}/failure-modes/${p.impeller.id}/tasks`, { name: `Check impeller ${tag}`, interval: 6 });
  await openPlant(page, p);
  const before = await frameOf(page);
  await dragTo(page, trow(page, `^Performance standard: At 4 bar ${tag}`), trow(page, `^Function: Pump more water ${tag}`), { hold: true });
  await expect(ghost(page).locator(".rcm-ghost-what")).toHaveText(`The performance standard “At 4 bar ${tag}” and its functional failure`);
  await expect(ghost(page)).toContainText("with its failure modes and tasks");
  await expect(ghost(page)).toHaveClass(/is-ok/);
  // Nothing on the page moved while dragging.
  const during = await frameOf(page);
  expect(during.rows).toEqual(before.rows);
  expect(during.boxes).toEqual(before.boxes);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/standard-subtree-drag-1280.png` });
  await page.mouse.up();
  await expect(toast(page)).toContainText(`Moved the performance standard “At 4 bar ${tag}” and its functional failure to “Pump more water ${tag}”.`);
  await expect(toast(page)).not.toContainText("stays");
  await expect.poll(async () => {
    const fn = (await rcmOf(request, p.b.id)).functions[0];
    return [fn.standards.map((s) => s.text), fn.failures.map((f) => [f.text, f.standard?.text, f.modes.map((m) => [m.text, m.tasks.map((t) => t.name)])])];
  }).toEqual([[`At least 20 L/s ${tag}`, `At 4 bar ${tag}`], [
    [`No flow at B ${tag}`, `At least 20 L/s ${tag}`, [[`Seal leaks ${tag}`, []]]],
    [`Low pressure ${tag}`, `At 4 bar ${tag}`, [[`Impeller worn ${tag}`, [`Check impeller ${tag}`]]]],
  ]]);
  expect((await rcmOf(request, p.a.id)).functions[0].failures.map((f) => f.text)).toEqual([`No flow ${tag}`]);
  // On screen too: the standard's row on Pump B, with its failure under it.
  await settled(page);
  const stdB = trow(page, `^Performance standard: At 4 bar ${tag}`);
  await expect(stdB).toHaveCount(1);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/standard-subtree-toast-1280.png` });
  await toast(page).getByRole("button", { name: "Undo" }).click();
  await expect(toast(page)).toContainText("Undone");
  await expect.poll(async () => {
    const fn = (await rcmOf(request, p.a.id)).functions[0];
    return [fn.standards.map((s) => s.text), fn.failures.map((f) => [f.text, f.standard?.text, f.modes.map((m) => m.text)])];
  }).toEqual([[`At least 50 L/s ${tag}`, `At 4 bar ${tag}`], [
    [`No flow ${tag}`, `At least 50 L/s ${tag}`, [`Bearing seizes ${tag}`, `Seal leaks ${tag}`]],
    [`Low pressure ${tag}`, `At 4 bar ${tag}`, [`Impeller worn ${tag}`]],
  ]]);
  const b = (await rcmOf(request, p.b.id)).functions[0];
  expect([b.standards.map((s) => s.text), b.failures.map((f) => f.text)]).toEqual([[`At least 20 L/s ${tag}`], [`No flow at B ${tag}`]]);
});

test("under a standard's row every row still drags: its functional failure, a mode, the mode's task", async ({ page, request }) => {
  const tag = `u${Date.now()}`;
  const p = await plant(request, tag);
  await openPlant(page, p);
  await expect(trow(page, `^Performance standard: At least 50 L/s ${tag}`).locator(".tt-grip")).toHaveCount(1);
  for (const name of [`^Functional failure: No flow ${tag}`, `^Failure mode: Bearing seizes ${tag}`, `^Failure mode: Seal leaks ${tag}`]) {
    await expect(trow(page, name).first().locator(".tt-grip")).toHaveCount(1);
  }
  await expect(trow(page, `^Failure mode: Bearing seizes ${tag}`).locator(".tt-task-drag")).toHaveCount(1);
  // The failure under the standard, onto the other function: it moves (the standard stays).
  await dragTo(page, trow(page, `^Functional failure: No flow ${tag}`), trow(page, `^Function: Contain the water ${tag}`));
  await expect(toast(page)).toContainText(`Moved “No flow ${tag}” under “Contain the water ${tag}”.`);
  await expect.poll(async () => (await rcmOf(request, p.a.id)).functions[1].failures.map((f) => f.text)).toEqual([`No flow ${tag}`]);
  expect((await rcmOf(request, p.a.id)).functions[0].standards.map((s) => s.text)).toEqual([`At least 50 L/s ${tag}`, `At 4 bar ${tag}`]);
});

test("a standard whose failure can't go there is refused before the drop, with the reason; nothing is written", async ({ page, request }) => {
  const tag = `q${Date.now()}`;
  const p = await plant(request, tag);
  await openPlant(page, p);
  // Under "At least 50 L/s": a mode named like one on Pump B.
  await dragTo(page, trow(page, `^Performance standard: At least 50 L/s ${tag}`), trow(page, `^Function: Pump more water ${tag}`), { hold: true });
  await expect(ghost(page).locator(".rcm-ghost-what")).toHaveText(`The performance standard “At least 50 L/s ${tag}” and its functional failure`);
  await expect(ghost(page)).toHaveClass(/is-no/);
  await expect(ghost(page)).toContainText(`Can't go here: Pump B ${tag} already has the failure mode Seal leaks ${tag}`);
  await expect(table(page).locator(".tp-row.drop-no")).toHaveCount(1);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/standard-subtree-refused-1280.png` });
  await page.mouse.up();
  await expect(page.locator(".tt-msg.error")).toContainText("Not moved");
  const fn = (await rcmOf(request, p.a.id)).functions[0];
  expect(fn.standards.map((s) => s.text)).toEqual([`At least 50 L/s ${tag}`, `At 4 bar ${tag}`]);
  expect(fn.failures.map((f) => f.standard?.text)).toEqual([`At least 50 L/s ${tag}`, `At 4 bar ${tag}`]);
});

test("at 400 px a standard's Move to… carries its failures too, with Undo", async ({ page, request }) => {
  const tag = `v${Date.now()}`;
  const p = await plant(request, tag);
  await openPlant(page, p, 400);
  const row = trow(page, `^Performance standard: At 4 bar ${tag}`);
  await row.getByRole("button", { name: /^Actions for / }).click();
  await page.getByRole("menu").getByRole("menuitem", { name: "Move to…" }).click();
  const dlg = page.getByRole("dialog", { name: `Move the performance standard “At 4 bar ${tag}” and its functional failure` });
  await expect(dlg).toBeVisible();
  await pickPlace(dlg, p.more.id, `Pump more water ${tag}`);
  await expect(dlg.getByRole("status")).toContainText(`to “Pump more water ${tag}”, with its failure modes and tasks.`);
  await expect(dlg.getByRole("status")).not.toContainText("checking");
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/standard-subtree-move-to-400.png` });
  await dlg.getByRole("button", { name: "Move", exact: true }).click();
  await expect(dlg).toHaveCount(0);
  await expect(toast(page)).toContainText(`Moved the performance standard “At 4 bar ${tag}”`);
  await expect.poll(async () => (await rcmOf(request, p.b.id)).functions[0].failures.map((f) => [f.text, f.standard?.text]))
    .toEqual([[`No flow at B ${tag}`, `At least 20 L/s ${tag}`], [`Low pressure ${tag}`, `At 4 bar ${tag}`]]);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/standard-subtree-toast-400.png` });
  await toast(page).getByRole("button", { name: "Undo" }).click();
  await expect.poll(async () => (await rcmOf(request, p.a.id)).functions[0].failures.map((f) => [f.text, f.standard?.text]))
    .toEqual([[`No flow ${tag}`, `At least 50 L/s ${tag}`], [`Low pressure ${tag}`, `At 4 bar ${tag}`]]);
  // The other way too: the refused one says why before Move.
  await trow(page, `^Performance standard: At least 50 L/s ${tag}`).getByRole("button", { name: /^Actions for / }).click();
  await page.getByRole("menu").getByRole("menuitem", { name: "Move to…" }).click();
  const dlg2 = page.getByRole("dialog", { name: /Move the performance standard “At least 50 L\/s/ });
  await pickPlace(dlg2, p.more.id, `Pump more water ${tag}`);
  await expect(dlg2.getByRole("status")).toContainText("It can't go there:");
  await expect(dlg2.getByRole("button", { name: "Move", exact: true })).toBeDisabled();
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

test("a task's row drags to copy: linked to a sibling failure mode, kept on its own; refused on a function; the menu links it too", async ({ page, request }) => {
  const tag = `k${Date.now()}`;
  const p = await plant(request, tag);
  await openPlant(page, p);
  const taskRow = trow(page, `^Task: Grease bearings ${tag}`);
  await expect(taskRow).toBeVisible();
  // Onto a function: refused quietly (the drop cue says no; nothing is written, nothing said after).
  await dragTo(page, taskRow, trow(page, `^Function: Contain the water ${tag}`), { hold: true });
  await expect(ghost(page)).toHaveClass(/is-no/);
  await expect(table(page).locator(".tp-row.drop-no")).toHaveCount(1);
  await page.mouse.up();
  await expect(page.locator(".tt-msg.error")).toHaveCount(0);
  // Onto the sibling failure mode: "Link here" with a + badge, and it reads as a copy.
  await dragTo(page, taskRow, trow(page, `^Failure mode: Seal leaks ${tag}`).first(), { hold: true });
  await expect(ghost(page)).toHaveClass(/is-ok/);
  await expect(ghost(page).locator(".rcm-ghost-plus")).toHaveText("+");
  await expect(ghost(page)).toContainText(`Link here: the task “Grease bearings ${tag}” will also prevent “Seal leaks ${tag}”`);
  await expect(table(page).locator(".tp-row.drop-copy")).toHaveCount(1);
  await expect(taskRow).not.toHaveClass(/dragged/); // a copy: its row stays as it is
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/drag-task-link-1280.png` });
  await page.mouse.up();
  await expect(toast(page)).toContainText(`Linked the task “Grease bearings ${tag}” to “Seal leaks ${tag}” as well`);
  // Both failure modes show it, each "Serves 2 here"; it never left the bearing.
  await expect(trow(page, `^Task: Grease bearings ${tag}`)).toHaveCount(2);
  await expect(trow(page, `^Task: Grease bearings ${tag}`).first()).toContainText("Serves 2 here");
  await expect(trow(page, `^Task: Grease bearings ${tag}`).nth(1)).toContainText("Serves 2 here");
  await expect.poll(async () => {
    const modes = (await rcmOf(request, p.a.id)).functions[0].failures[0].modes;
    return modes.map((m) => [m.text, (m.tasks || []).map((t) => t.id)]);
  }).toEqual([[`Bearing seizes ${tag}`, [p.task.id]], [`Seal leaks ${tag}`, [p.task.id]]]);
  // The keyboard's way: its row menu's Link to another failure mode…, the picker, Link.
  await trow(page, `^Task: Grease bearings ${tag}`).first().locator(".tp-nm").click();
  await page.keyboard.press("Shift+F10");
  await page.getByRole("menu").getByRole("menuitem", { name: "Link to another failure mode…" }).click();
  const pick = page.getByRole("dialog", { name: `Link the task “Grease bearings ${tag}” to another failure mode` });
  await expect(pick).toBeVisible();
  // Only failure modes it can reach and doesn't prevent yet are offered (Pump A's seal has it now; Pump B is beside it).
  await pick.getByRole("searchbox", { name: "Find a place" }).fill(tag);
  await expect(pick.getByRole("treeitem", { name: new RegExp(`Seal leaks ${tag}`) })).toHaveCount(0);
  await expect(pick.getByRole("treeitem", { name: new RegExp(`Bearing seizes ${tag}`) })).toContainText("linked here");
  await pick.getByRole("treeitem", { name: new RegExp(`Impeller worn ${tag}`) }).click();
  await pick.getByRole("button", { name: "Link", exact: true }).click();
  await expect(pick).toHaveCount(0);
  await expect(trow(page, `^Task: Grease bearings ${tag}`)).toHaveCount(3);
  await expect(trow(page, `^Task: Grease bearings ${tag}`).first()).toContainText("Serves 3 here");
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
  await row.getByRole("button", { name: /^Actions for / }).click();
  const menu = page.getByRole("menu");
  await expect(menu.getByRole("menuitem", { name: "Move up" })).toBeVisible();
  await menu.getByRole("menuitem", { name: "Move to…" }).click();
  const dlg = page.getByRole("dialog", { name: `Move “Contain the water ${tag}”` });
  await expect(dlg).toBeVisible();
  await pickPlace(dlg, p.b.id, `Pump B ${tag}`);
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

// Move to…: one picker for every kind, from the row's ⋯ with the mouse too.
// Only the places that kind can go can be picked; the rest are greyed with a
// reason. Each move lands where it was put, and the moved row is picked there.
async function moveVia(page, rowName, { item = "Move to…", width = 1280 } = {}) {
  const row = typeof rowName === "string" ? trow(page, rowName) : rowName;
  if (width > 600) await row.hover();
  await row.getByRole("button", { name: /^Actions for / }).click();
  await page.getByRole("menu").getByRole("menuitem", { name: item }).click();
  const dlg = page.getByRole("dialog", { name: /^Move / });
  await expect(dlg).toBeVisible();
  return dlg;
}
const place = (dlg, key) => dlg.getByRole("tree", { name: "Where it goes" }).locator(`[role="treeitem"][data-key="${key}"]`);
async function moveAndCheck(page, dlg, key, name) {
  await pickPlace(dlg, key, name);
  await expect(dlg.getByRole("status")).not.toContainText("checking");
  await dlg.getByRole("button", { name: "Move", exact: true }).click();
  await expect(dlg).toHaveCount(0);
  await expect(toast(page).getByRole("button", { name: "Undo" })).toBeVisible();
}

test("Move to… moves every kind from its ⋯ menu, and the moved row is picked in its new place", async ({ page, request }) => {
  const tag = `m${Date.now()}`;
  const p = await plant(request, tag);
  await openPlant(page, p);

  // A performance standard → another function (its functional failure goes with it). Positions are greyed.
  let dlg = await moveVia(page, `^Performance standard: At 4 bar ${tag}`);
  await expect(place(dlg, p.b.id)).toHaveAttribute("aria-disabled", "true");
  await expect(place(dlg, p.b.id)).toHaveAttribute("title", "A performance standard goes under a function.");
  await expect(place(dlg, p.water.id)).toHaveAttribute("title", "It's here now.");
  await moveAndCheck(page, dlg, p.more.id, `Pump more water ${tag}`);
  await expect.poll(async () => (await rcmOf(request, p.b.id)).functions[0].failures.map((f) => [f.text, f.standard?.text]))
    .toEqual([[`No flow at B ${tag}`, `At least 20 L/s ${tag}`], [`Low pressure ${tag}`, `At 4 bar ${tag}`]]);
  await expect(trow(page, `^Performance standard: At 4 bar ${tag}`)).toHaveAttribute("aria-selected", "true");

  // A function → another position.
  dlg = await moveVia(page, `^Function: Contain the water ${tag}`);
  await moveAndCheck(page, dlg, p.b.id, `Pump B ${tag}`);
  await expect.poll(async () => (await rcmOf(request, p.b.id)).functions.map((f) => f.text)).toContain(`Contain the water ${tag}`);
  await expect(trow(page, `^Function: Contain the water ${tag}`)).toHaveAttribute("aria-selected", "true");

  // A failure mode → its position's "Not under a functional failure" (offered though there's none yet).
  const sealRow = table(page).locator(`[id="tp-${p.seal.id}"]`);
  dlg = await moveVia(page, sealRow);
  await expect(place(dlg, p.noFlow.id)).toHaveAttribute("title", "It's here now.");
  await expect(place(dlg, p.a.id)).toHaveAttribute("title", /^A failure mode goes under a functional failure/);
  await place(dlg, p.a.id).click({ force: true }); // a greyed place (aria-disabled): says why, picks nothing
  await expect(dlg.getByRole("status")).toContainText("It can't go there.");
  await expect(dlg.getByRole("button", { name: "Move", exact: true })).toBeDisabled();
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/move-to-failure-mode-1280.png` });
  await moveAndCheck(page, dlg, `U:${p.a.id}`, "Not under a functional failure");
  await expect.poll(async () => (await rcmOf(request, p.a.id)).unassigned.map((m) => m.text)).toEqual([`Seal leaks ${tag}`]);
  await expect(sealRow).toHaveAttribute("aria-selected", "true");

  // A task → another failure mode (Move a task…).
  dlg = await moveVia(page, `^Failure mode: Bearing seizes ${tag}`, { item: "Move a task…" });
  await moveAndCheck(page, dlg, p.seal.id, `Seal leaks ${tag}`);
  await expect.poll(async () => (await rcmOf(request, p.a.id)).unassigned[0].tasks.map((t) => t.name)).toEqual([`Grease bearings ${tag}`]);

  // A functional failure → its function's "No performance standard" (offered though there's none yet).
  dlg = await moveVia(page, `^Functional failure: No flow ${tag}`);
  await expect(place(dlg, p.flow.id)).toHaveAttribute("title", "It's here now.");
  await expect(place(dlg, p.water.id)).toHaveAttribute("aria-disabled", "true");
  await expect(place(dlg, p.a.id)).toHaveAttribute("aria-disabled", "true");
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/move-to-functional-failure-1280.png` });
  await moveAndCheck(page, dlg, `N:${p.water.id}`, "No performance standard");
  await expect.poll(async () => (await rcmOf(request, p.a.id)).functions[0].failures.find((f) => f.text === `No flow ${tag}`).standard).toBeNull();
  await expect(trow(page, `^Functional failure: No flow ${tag}`)).toHaveAttribute("aria-selected", "true");
  // Undo puts it back under its standard.
  await toast(page).getByRole("button", { name: "Undo" }).click();
  await expect(toast(page)).toContainText("Undone");
  await expect.poll(async () => (await rcmOf(request, p.a.id)).functions[0].failures.find((f) => f.text === `No flow ${tag}`).standard?.text, { timeout: 30_000 })
    .toBe(`At least 50 L/s ${tag}`);
});

test("at 400 px Move to… for a failure mode and a functional failure fits, searches and moves", async ({ page, request }) => {
  const tag = `q${Date.now()}`;
  const p = await plant(request, tag);
  await openPlant(page, p, 400);
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  // A failure mode: search narrows the tree to the matches and the way to them.
  let dlg = await moveVia(page, `^Failure mode: Impeller worn ${tag}`, { width: 400 });
  await dlg.getByRole("searchbox", { name: "Find a place" }).fill(`No flow at B ${tag}`);
  await expect(dlg.getByRole("tree", { name: "Where it goes" }).getByRole("treeitem")).toHaveText([
    `Drag plant ${tag}`, `Pump B ${tag}`, `Pump more water ${tag}`, `At least 20 L/s ${tag}`, `No flow at B ${tag}`]);
  await dlg.getByRole("searchbox", { name: "Find a place" }).fill("");
  expect(await overflow()).toBeLessThanOrEqual(0);
  const box = await dlg.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(400.5);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/move-to-failure-mode-400.png` });
  // Picked from the keyboard too: Enter on a place picks it.
  await dlg.getByRole("searchbox", { name: "Find a place" }).fill(`No flow at B ${tag}`);
  await place(dlg, p.noFlowB.id).focus();
  await page.keyboard.press("Enter");
  await expect(place(dlg, p.noFlowB.id)).toHaveAttribute("aria-selected", "true");
  await moveAndCheck(page, dlg, p.noFlowB.id, `No flow at B ${tag}`);
  await expect.poll(async () => (await rcmOf(request, p.b.id)).functions[0].failures[0].modes.map((m) => m.text)).toContain(`Impeller worn ${tag}`);
  // A functional failure: a performance standard on another position.
  dlg = await moveVia(page, `^Functional failure: Low pressure ${tag}`, { width: 400 });
  expect(await overflow()).toBeLessThanOrEqual(0);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/move-to-functional-failure-400.png` });
  await moveAndCheck(page, dlg, p.twenty.id, `At least 20 L/s ${tag}`);
  await expect.poll(async () => (await rcmOf(request, p.b.id)).functions[0].failures.map((f) => f.text)).toContain(`Low pressure ${tag}`);
  expect(await overflow()).toBeLessThanOrEqual(0);
});
