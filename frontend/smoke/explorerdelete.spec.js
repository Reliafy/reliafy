// Delete… in the Explorer (Assets › Explorer, Summary tab): a position with
// everything inside it, counted by the server in the dialog (positions
// inside, the fitted item taken out and kept, its task, its open work order
// cancelled), one click, gone; the toast's Undo (and Ctrl/Cmd+Z) brings the
// whole branch back. Delete or Backspace on a focused row opens the dialog.
// At 400 px the dialog fits and nothing scrolls sideways. A location's row
// deletes the places inside it too. Each test plants its own small tree
// (named to sort last, so other specs' rows keep their places on screen) and
// deletes it again at the end.
//
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
  const top = await post(`${M}/positions`, { name: `Zdel craft ${tag}` });
  const prop = await post(`${M}/positions`, { name: `Zdel propulsion ${tag}`, parent_id: top.id });
  const motor = await post(`${M}/positions`, { name: `Zdel motor ${tag}`, parent_id: prop.id });
  const esc = await post(`${M}/positions`, { name: `Zdel esc ${tag}`, parent_id: prop.id });
  await post(`${M}/positions/${motor.id}/fit`, { new_item: { name: `Zdel unit ${tag}` } });
  await post(`${M}/positions/${motor.id}/tasks`, { name: `Zdel grease ${tag}`, interval: 3, unit: "months" });
  await post(`${M}/work-orders`, { position_id: esc.id, title: `Zdel check ${tag}` });
  return { top, prop, motor, esc };
}

const row = (page, name) => page.getByRole("treeitem", { name: new RegExp(`^${name}`) });
const rowMenu = (page, name) => page.getByRole("menu", { name: new RegExp(`^Actions for ${name}`) });

test("Delete a branch: the server's counts, one click, gone; Undo brings it all back", async ({ page, request, problems }) => {
  const tag = `d${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.motor.id}`);
  await expect(row(page, `Zdel motor ${tag}`)).toBeVisible();

  await row(page, `Zdel propulsion ${tag}`).locator(".tp-nm").click({ button: "right" });
  await rowMenu(page, `Zdel propulsion ${tag}`).getByRole("menuitem", { name: "Delete…" }).click();
  const dialog = page.getByRole("dialog", { name: `Delete “Zdel propulsion ${tag}” and everything inside it?` });
  const counts = dialog.getByTestId("delete-counts");
  await expect(counts).toContainText("2 positions inside it");
  await expect(counts).toContainText("1 fitted item kept, unfitted: it stays in Items");
  await expect(counts).toContainText("1 scheduled task: no longer scheduled");
  await expect(counts).toContainText("1 open work order: cancelled");
  await expect(counts).toContainText("Its history stays in the log");
  await shot(page, "delete-1-dialog-1280");
  await dialog.getByRole("button", { name: "Delete 3 positions" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(row(page, `Zdel propulsion ${tag}`)).toHaveCount(0);
  await expect(row(page, `Zdel motor ${tag}`)).toHaveCount(0);
  await expect(row(page, `Zdel craft ${tag}`)).toHaveAttribute("aria-selected", "true");
  const toast = page.locator(".rcm-toast");
  await expect(toast).toContainText(`Deleted Zdel propulsion ${tag} and 2 positions inside it.`);
  await shot(page, "delete-2-toast-1280");

  await toast.getByRole("button", { name: "Undo" }).click();
  await expect(toast).toContainText(`Undone: Zdel propulsion ${tag} and everything inside it are back.`);
  await expect(row(page, `Zdel propulsion ${tag}`)).toBeVisible();
  // The item was kept (never deleted) and is back in its position.
  const back = await (await request.get(`${M}/positions/${p.motor.id}`)).json();
  expect(back.retired).toBe(false);
  expect(back.fitted?.item?.name).toBe(`Zdel unit ${tag}`);
  const esc = await (await request.get(`${M}/positions/${p.esc.id}`)).json();
  expect(esc.retired).toBe(false);
  await expectHealthy(page, problems, { label: "delete and undo", root: ".tx" });
  await request.post(`${M}/positions/${p.top.id}/retire`, { data: { cascade: true } });
});

test("Delete from the keyboard, Undo with Ctrl+Z; at 400 px the dialog fits", async ({ page, request, problems }) => {
  const tag = `k${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.esc.id}`);
  const esc = row(page, `Zdel esc ${tag}`);
  await esc.click();
  await expect(esc).toBeFocused();
  await esc.press("Delete");
  let dialog = page.getByRole("dialog", { name: `Delete “Zdel esc ${tag}”?` });
  await expect(dialog.getByTestId("delete-counts")).toContainText("1 open work order: cancelled");
  await dialog.getByRole("button", { name: "Delete the position" }).click();
  await expect(row(page, `Zdel esc ${tag}`)).toHaveCount(0);
  await expect(page.locator(".rcm-toast")).toContainText(`Deleted Zdel esc ${tag}.`);
  await page.keyboard.press("ControlOrMeta+z");
  await expect(page.locator(".rcm-toast")).toContainText("Undone");
  await expect(row(page, `Zdel esc ${tag}`)).toBeVisible();

  // A phone: the ⋯ button, Delete…, the dialog fits; Backspace opens it too.
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.top.id}`);
  await row(page, `Zdel propulsion ${tag}`).getByRole("button", { name: "Actions", exact: true }).click();
  await rowMenu(page, `Zdel propulsion ${tag}`).getByRole("menuitem", { name: "Delete…" }).click();
  dialog = page.getByRole("dialog", { name: `Delete “Zdel propulsion ${tag}” and everything inside it?` });
  await expect(dialog.getByRole("button", { name: "Delete 3 positions" })).toBeVisible();
  const box = await dialog.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(400);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await shot(page, "delete-3-dialog-phone-400");
  await dialog.getByRole("button", { name: "Delete 3 positions" }).click();
  await expect(dialog).toHaveCount(0);
  const toast = page.locator(".rcm-toast");
  await expect(toast).toContainText(`Deleted Zdel propulsion ${tag}`);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await shot(page, "delete-4-toast-phone-400");
  await toast.getByRole("button", { name: "Undo" }).click();
  await expect(toast).toContainText("Undone");
  await expectHealthy(page, problems, { label: "delete keyboard and phone", root: ".tx" });
  await request.post(`${M}/positions/${p.top.id}/retire`, { data: { cascade: true } });
});

test("A location's Delete… takes the places inside it", async ({ page, request, problems }) => {
  const tag = `l${Date.now()}`;
  const post = async (path, data) => (await request.post(path, { data })).json();
  const site = await post(`${M}/locations`, { name: `Zdel site ${tag}` });
  await post(`${M}/locations`, { name: `Zdel shed ${tag}`, parent_id: site.id });
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, `/asset-register/explorer?arrange=locations&sel=${site.id}`);
  await row(page, `Zdel site ${tag}`).locator(".tp-nm").click({ button: "right" });
  await rowMenu(page, `Zdel site ${tag}`).getByRole("menuitem", { name: "Delete…" }).click();
  const dialog = page.getByRole("dialog", { name: `Delete “Zdel site ${tag}” and everything inside it?` });
  await expect(dialog.getByTestId("delete-counts")).toContainText("1 location inside it");
  await dialog.getByRole("button", { name: "Delete 2 locations" }).click();
  await expect(row(page, `Zdel site ${tag}`)).toHaveCount(0);
  await expect(row(page, `Zdel shed ${tag}`)).toHaveCount(0);
  await page.locator(".rcm-toast").getByRole("button", { name: "Undo" }).click();
  await expect(row(page, `Zdel site ${tag}`)).toBeVisible();
  await expectHealthy(page, problems, { label: "delete a location", root: ".tx" });
  await request.post(`${M}/locations/${site.id}/retire`, { data: { cascade: true } });
});
