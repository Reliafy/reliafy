// The main path through the app: fit a model to a sample dataset and save it.
// (Calculating an RBD is in rbd.spec.js.)
import { test, expect, open, expectHealthy } from "./health.js";

test("fit and save a Weibull model from a sample dataset", async ({ page, problems }) => {
  await open(page, "/datasets/d/sample-ds-bearings");
  await page.getByRole("button", { name: "Fit a model" }).click();
  await expect(page).toHaveURL(/\/modelling\/new\?dataset=sample-ds-bearings/);
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Fit Weibull" }).click();
  await expect(page.getByText("Shape β").first()).toBeVisible({ timeout: 30_000 });
  await expectHealthy(page, problems, { label: "fitted model", chart: true });

  await page.getByRole("button", { name: "Save model" }).click();
  await page.waitForURL(/\/modelling\/m\/[0-9a-f]{32}$/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: /Weibull/ })).toBeVisible();
  await expectHealthy(page, problems, { label: "saved model", chart: true });
});

// #31: a class with a fitted model and a spare with a lead time shows how many to
// hold, and the chance a typed stock runs out (smoke/seed.js makes the class).
test("a class's spares stock levels and the what-if", async ({ page, problems }) => {
  await open(page, `/maintenance/classes/${encodeURIComponent("Smoke test pump")}`);
  const stocking = page.getByTestId("spares-stocking");
  await expect(stocking.getByRole("heading", { name: "Stock to hold" })).toBeVisible({ timeout: 30_000 });
  const row = stocking.getByRole("row", { name: /SMOKE-PUMP/ });
  await expect(row).toContainText("60 days lead time at 95%");
  await expect(page.getByTestId("spares-summary")).toContainText(/^Hold \d+: a 95% chance of no stock-out/);
  await page.getByLabel("If we hold").fill("0");
  await expect(page.getByTestId("spares-whatif")).toContainText("chance of running out over the lead time");
  await stocking.getByLabel("Service level").selectOption("0.99");
  await expect(row).toContainText("at 99%");
  await expectHealthy(page, problems, { label: "class stock levels", chart: true });
});

// #434, the first run: a CSV saved without a header row. Its first row is
// all numbers, so it's read as data (col 1, col 2) and said so; the column of
// decimals can't be made the count; the fit is saved, with its data, in one
// click.
const HEADERLESS = [
  "300,544966.3125", "410,612000.5", "520,701234.25", "655,802000.75",
  "720,810000.5", "845,905000.25", "990,1010000.5", "1100,1200000.75",
].join("\n") + "\n";

async function uploadAndFit(page) {
  await open(page, "/modelling/new?mode=data");
  await page.locator('input[type="file"]').setInputFiles({
    name: "raw.csv", mimeType: "text/csv", buffer: Buffer.from(HEADERLESS),
  });
  await expect(page.getByText("Your first row looks like data, so we've treated it as data.")).toBeVisible();
  await expect(page.getByText(/raw\.csv · 8 rows · 2 columns/)).toBeVisible();
  await expect(page.getByText(/col 1 \(time to failure\)/)).toBeVisible();

  // The column of decimals is offered as a count only with the reason, and can't be picked.
  await page.getByRole("combobox", { name: "What “col 2” is" }).click();
  const count = page.getByRole("option", { name: /^Count/ });
  await expect(count).toBeDisabled();
  await expect(count).toContainText("has decimals");
  await expect(page.getByRole("option", { name: "Ignore this column" })).toBeVisible();
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Fit Weibull" }).click();
  await expect(page.getByText("Shape β").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("This fit isn't saved yet.")).toBeVisible();
}

async function expectSavedWithData(page) {
  await page.waitForURL(/\/modelling\/m\/[0-9a-f]{32}$/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: /Weibull/ })).toBeVisible();
  const id = page.url().split("/").pop();
  const model = await (await page.request.get(`/api/models/${id}`)).json();
  const dataset = await (await page.request.get(`/api/datasets/${model.dataset_id}`)).json();
  expect(dataset.n_rows).toBe(8); // the first row is kept
  expect(dataset.columns.map((c) => c.name)).toEqual(["col 1", "col 2"]);
}

test("a headerless CSV is detected, fitted and saved with its data in one click", async ({ page, problems }) => {
  await uploadAndFit(page);
  await expectHealthy(page, problems, { label: "fitted headerless CSV", chart: true });
  await page.getByRole("button", { name: "Save this model and its data" }).click();
  await expectSavedWithData(page);
  await expectHealthy(page, problems, { label: "saved model", chart: true });
});

test("a fit left unsaved is offered for saving on the next visit to Modelling", async ({ page, problems }) => {
  await uploadAndFit(page);
  await open(page, "/modelling");
  await expect(page.getByText("You left a fit without saving it")).toBeVisible();
  await page.getByRole("button", { name: "Save it and its data" }).click();
  await expectSavedWithData(page);
  // Saved: no reminder now.
  await open(page, "/modelling");
  await expect(page.getByText("You left a fit without saving it")).toHaveCount(0);
  await expectHealthy(page, problems, { label: "modelling home" });
});

// A photo added to a work order (a nameplate, say) moved to the work order's
// position from the photo's "Link or move" picker: it leaves the work order and
// shows on the position (smoke/seed.js makes the work order).
const NAMEPLATE_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAGAAAABACAIAAABqVuVZAAAC7UlEQVR42u3aW0hTcRwH8N8u6uatoWFGYoF3i7C0KWYuVJKoB8UgM5vRTY2UQDFyYQ+tG4mWipIWCaVZWfkUTjAvMTRJty6ixtBA8VKuy2Jl7nJ6GK2B03yqjn6/b/8L5+HD7///c87/cILTagmZP1wQAAhAAAIQgAAEIAAh9sJfeLi7Mmk5KEQdb0IFYYn9kyW2mCJkbxazgaCCAAQgAAEIQAACEIAQAAEIQAACEC3Rzx1zE7rOMy91M5/PNZmYwmrlpFavrk1/qfmQIVdYJvTU7BMfvWud7+bsWCgVJ0T4bjlSb+lJkQQkS/xdhPzi+l7l63GBI/9C5taVK4QuQn5Zo7pDNcbuCjqfGS2rVmbIFQ2tQwVpEUQ0azDxuFxxiLfd+VX58f0jWoZhLE0Pd0FSrJ/0XHNeeWehVExE+3cEvxmelsqbs660Fh2MZP0S83QXOjrwiOhp72hdy6Cls+KhOmdPmN35J8va7ygGrE2Rq1Ndy6CZYSa0epGrExE9aHt7WzFARP4+IqOJYT1Q6b2+uqKd8mPR4UFevUNTls7u/gkiigy1U0TTn7/bNofHvzQ/f0dEieK1bapRItLpZw1G8+XsbZV5cWdvdrEe6HGnZldBU9/Q+9MHxCdSfldNeeO8RTQ3vqvcDu/eUNLQZ+05VfUsv6IzOdaP3UAe7oJNgV46/eyjDs2hiy2p8YHWoZ6BSZOZiVq/+o8PcRbwS3IkshrlR90MEZ3JiOTxOETUrhqThPmwG4hhmNJcibeni2U3GdfqbUfLG9W2NWU3HA5dyoq59aT/lWb61zHnkBDuS0RhAV4jEzp2H/Ofvv4outF1LXf7jMFoNjOy60rb0ReDUwajybKFz5fkWP+YjWtEroK9cUHfZgxZxa1X76suZcekJ4YYjGZZtfI/AeIs/I+i9WJkaV/74GYVrxoAAhCAAAQgACEAAhCAAAQgAAGIcC9Gy/KXe1QQgOjvfnJFUEEAAhCAAAQgAAFoueYnG4bvXTtLdPoAAAAASUVORK5CYII=",
  "base64",
);

test("move a photo from a work order to its position", async ({ page, problems }) => {
  const { work_orders: wos } = await (await page.request.get("/api/maintenance/work-orders")).json();
  const wo = wos.find((w) => w.title === "Smoke test inspection");
  expect(wo?.position, "the seeded work order and its position").toBeTruthy();
  const added = await page.request.post(
    `/api/maintenance/photos?target_id=${wo.id}&caption=${encodeURIComponent("Smoke nameplate")}`,
    { data: NAMEPLATE_PNG, headers: { "Content-Type": "image/png" } },
  );
  expect(added.ok(), await added.text()).toBeTruthy();
  const photoId = (await added.json()).photo.id;

  await open(page, `/maintenance/work-orders/${wo.id}`);
  await page.getByRole("img", { name: "Smoke nameplate" }).click();
  await page.getByRole("button", { name: "Link or move…" }).click();
  const picker = page.locator(".modal").filter({ hasText: "Link or move this photo" });
  await picker.getByLabel(/Move it there/).check();
  await picker.getByLabel("Kind").selectOption("Position");
  await picker.getByLabel("Which position").selectOption(wo.position.id);
  await picker.getByRole("button", { name: "Move", exact: true }).click();
  await expect(page.getByRole("img", { name: "Smoke nameplate" })).toHaveCount(0);
  await expectHealthy(page, problems, { label: "work order after moving a photo" });

  const position = await (await page.request.get(`/api/maintenance/positions/${wo.position.id}`)).json();
  expect(position.photos.map((p) => p.id)).toContain(photoId);
  await open(page, `/maintenance/positions/${wo.position.id}`);
  await expect(page.getByRole("img", { name: "Smoke nameplate" })).toBeVisible();
  await expectHealthy(page, problems, { label: "position with the moved photo" });
});
