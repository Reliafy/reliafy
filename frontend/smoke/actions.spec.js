// The main path through the app: fit a model to a sample dataset and save it.
// (Calculating an RBD is in rbd.spec.js.)
import { test, expect, open, expectHealthy } from "./health.js";

test("fit and save a Weibull model from a sample dataset", async ({ page, problems }) => {
  await open(page, "/data/sample-ds-bearings");
  await page.getByRole("button", { name: "Fit a model" }).click();
  await expect(page).toHaveURL(/\/models\/new\?dataset=sample-ds-bearings/);
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Fit Weibull" }).click();
  await expect(page.getByText("Shape β").first()).toBeVisible({ timeout: 30_000 });
  await expectHealthy(page, problems, { label: "fitted model", chart: true });

  await page.getByRole("button", { name: "Save model" }).click();
  await page.waitForURL(/\/models\/m\/[0-9a-f]{32}$/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: /Weibull/ })).toBeVisible();
  await expectHealthy(page, problems, { label: "saved model", chart: true });
});

// #31: a class with a fitted model and a spare with a lead time shows how many to
// hold, and the chance a typed stock runs out (smoke/seed.js makes the class).
test("a class's spares stock levels and the what-if", async ({ page, problems }) => {
  await open(page, `/asset-register/classes/${encodeURIComponent("Smoke test pump")}`);
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

// Assets opens on the top-level places, each with what's inside it; the positions
// at no place are the last row, opening the Explorer filtered to them (smoke/seed.js
// puts one position in the depot and leaves the pumps at no place).
test("the assets are the top-level places, and the positions at none stay reachable", async ({ page, problems }) => {
  await open(page, "/asset-register");
  await expect(page.getByRole("heading", { name: "Assets", exact: true })).toBeVisible();
  const depot = page.getByRole("row").filter({ has: page.getByRole("link", { name: "Smoke test depot", exact: true }) });
  await expect(depot).toBeVisible();
  const rest = page.getByRole("row").filter({ has: page.getByRole("link", { name: "Not at a place yet" }) });
  await expect(rest).toBeVisible();
  await expectHealthy(page, problems, { label: "assets" });

  await rest.getByRole("link", { name: "Not at a place yet" }).click();
  await expect(page).toHaveURL(/\/asset-register\/explorer\?arrange=positions&place=none$/);
  await expect(page.locator(".tp-notice")).toContainText("Not at a location yet");
  await expect(page.getByRole("treeitem", { name: /^Smoke pump 1\b/ })).toBeVisible();
  await expect(page.getByRole("treeitem", { name: /^Delivery truck/ })).toHaveCount(0); // at the depot
  await page.getByRole("link", { name: "Show every position" }).click();
  await expect(page).toHaveURL(/\/asset-register\/explorer\?arrange=positions$/);
  await expect(page.getByRole("heading", { name: "Explorer", exact: true })).toBeVisible();
  await expect(page.locator(".tp-notice")).toHaveCount(0);
  await expectHealthy(page, problems, { label: "positions" });

  await open(page, "/asset-register");
  await depot.getByRole("link", { name: "Smoke test depot", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Smoke test depot" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Open work here" })).toBeVisible();
  await expect(page.getByText("Smoke test inspection")).toBeVisible();
  await expectHealthy(page, problems, { label: "an asset's page" });
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
  await open(page, "/models/new?mode=data");
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
  await page.waitForURL(/\/models\/m\/[0-9a-f]{32}$/, { timeout: 30_000 });
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

test("a fit left unsaved is offered for saving on the next visit to Models", async ({ page, problems }) => {
  await uploadAndFit(page);
  await open(page, "/models");
  await expect(page.getByText("You left a fit without saving it")).toBeVisible();
  await page.getByRole("button", { name: "Save it and its data" }).click();
  await expectSavedWithData(page);
  // Saved: no reminder now.
  await open(page, "/models");
  await expect(page.getByText("You left a fit without saving it")).toHaveCount(0);
  await expectHealthy(page, problems, { label: "models home" });
});

// Strategy › Replacement, shutdown calendar: shuts every 180 days at 100, 150
// between shuts, 400 at a failure, for a bearing (Weibull, scale 365 days,
// shape 2): replace at a shut a bearing older than about 138 days; the unit in
// service 200 days old is kept to the next shut.
test("replacement over a shutdown calendar: the rule, the next months and one unit now", async ({ page, problems }) => {
  await open(page, "/strategy/replacement");
  await page.getByRole("radio", { name: "Shutdown calendar" }).click();
  await expect(page).toHaveURL(/mode=calendar/);
  await page.getByRole("radio", { name: "Parameters" }).click();
  await page.getByLabel(/Scale α/).fill("365");
  await page.getByLabel(/Shape β/).fill("2");
  await page.getByRole("combobox", { name: "Model time unit" }).click();
  await page.getByRole("option", { name: "Days", exact: true }).click();
  const shut = page.getByRole("group", { name: "Shut 1" });
  await shut.getByLabel("Replacing at it costs").fill("100");
  await shut.getByLabel(/Every how many/).fill("180");
  await shut.getByRole("combobox", { name: "Every unit" }).click();
  await page.getByRole("option", { name: "days", exact: true }).click();
  // The first shut in 150 days (UC-12's outage), so none falls today.
  const first = new Date(Date.now() + 150 * 86_400_000);
  const iso = `${first.getFullYear()}-${String(first.getMonth() + 1).padStart(2, "0")}-${String(first.getDate()).padStart(2, "0")}`;
  await shut.getByLabel("Starting").fill(iso);
  await page.getByLabel("Failure (unplanned) cost").fill("400");
  await page.getByLabel("Replacing between shuts costs").fill("150");
  await page.getByRole("button", { name: "Compute" }).click();
  const rule = page.getByTestId("calendar-rule");
  await expect(rule).toContainText(/replace the part if it is older than 13\d days/, { timeout: 30_000 });
  await expect(page.getByTestId("calendar-schedule").getByRole("row")).toHaveCount(3); // a header and 2 shuts
  await expectHealthy(page, problems, { label: "calendar replacement", chart: true });

  const now = page.getByTestId("calendar-unit-now");
  await now.getByLabel(/Its age today/).fill("200");
  await now.getByRole("button", { name: "Check this unit" }).click();
  await expect(now).toContainText("Keep it: replace it at the Annual shutdown", { timeout: 30_000 });
  await expect(now).toContainText("Replacing now becomes the best choice from an age of");
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
  await open(page, `/asset-register/positions/${wo.position.id}`);
  await expect(page.getByRole("img", { name: "Smoke nameplate" })).toBeVisible();
  await expectHealthy(page, problems, { label: "position with the moved photo" });
});

// Deletes ask in the app's own dialog, never the browser's: it names the
// action, says what happens (a sample comes back from Settings), starts on
// Cancel, and Escape or Cancel leaves everything as it was.
test("removing a sample asks in the app's confirm dialog", async ({ page, problems }) => {
  await open(page, "/systems/rbds");
  const remove = page.getByRole("button", { name: "Remove from my view" }).first();
  const row = page.getByRole("row").filter({ has: remove }).first();
  await remove.click();
  const dialog = page.getByRole("alertdialog", { name: "Remove this sample?" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("Settings › Sample data");
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  await expect(dialog.getByRole("button", { name: "Remove sample" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await remove.click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(row).toBeVisible();
  expect(problems).toEqual([]);
});

// Renaming asks in the app's dialog too (never window.prompt): the box starts
// on the current name with it selected, Enter saves, and the delete dialog
// says what goes and that it can't be undone. The copy is kept (not deleted)
// so the detail-page sweep running alongside never opens a diagram that's gone.
test("rename a diagram, and the delete dialog, in the app's own dialogs", async ({ page, problems }) => {
  const sample = await (await page.request.get("/api/rbds/sample-rbd-pump-station")).json();
  const saved = await page.request.post("/api/rbds", {
    data: { name: "Smoke dialog diagram", graph: sample.graph, id: null, expected_updated_at: null },
  });
  expect(saved.ok(), await saved.text()).toBeTruthy();

  await open(page, "/systems/rbds");
  const row = page.getByRole("row").filter({ hasText: "Smoke dialog diagram" });
  await row.getByRole("button", { name: "Rename" }).click();
  const ask = page.getByRole("dialog", { name: "Rename this diagram" });
  const box = ask.getByRole("textbox", { name: "Diagram name" });
  await expect(box).toBeFocused();
  await expect(box).toHaveValue("Smoke dialog diagram");
  await page.keyboard.press("Escape");
  await expect(ask).toHaveCount(0);
  await expect(row).toBeVisible();

  await row.getByRole("button", { name: "Rename" }).click();
  await box.fill("  ");
  await expect(ask.getByRole("button", { name: "Rename diagram" })).toBeDisabled();
  await box.fill("Smoke dialog diagram, renamed");
  await page.keyboard.press("Enter");
  await expect(ask).toHaveCount(0);
  const renamed = page.getByRole("row").filter({ hasText: "Smoke dialog diagram, renamed" });
  await expect(renamed).toBeVisible();

  await renamed.getByRole("button", { name: "Delete", exact: true }).click();
  const del = page.getByRole("alertdialog", { name: "Delete this diagram?" });
  await expect(del).toContainText("“Smoke dialog diagram, renamed” will be deleted. This can't be undone.");
  await expect(del.getByRole("button", { name: "Cancel" })).toBeFocused();
  await expect(del.getByRole("button", { name: "Delete diagram" })).toBeVisible();
  await page.locator(".confirm-overlay").click({ position: { x: 5, y: 5 } });
  await expect(del).toHaveCount(0);
  await expect(renamed).toBeVisible();
  expect(problems).toEqual([]);
});

// A non-repairable model's panel stays short: the failure pattern and "Use this
// model" open in dialogs, and a B-life is the Calculator's "Time at
// reliability" (R = 90% is the B10 life), with its bound.
test("a model's failure pattern, Use this model and B-lives", async ({ page, problems }) => {
  await open(page, "/models/m/sample-model-bearings-weibull");
  const pattern = page.getByRole("button", { name: /^Failure pattern: Wear-out/ });
  await pattern.click();
  const reading = page.getByRole("dialog", { name: "Wear-out" });
  await expect(reading).toContainText("β is above 1 at 95% confidence");
  await expect(reading.getByRole("button", { name: /Find the best replacement interval/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(reading).toBeHidden();
  await expect(pattern).toBeFocused();

  await page.getByRole("button", { name: /^Use this model/ }).click();
  const use = page.getByRole("dialog", { name: "Use this model" });
  for (const step of ["Find the best replacement interval", "Forecast a fleet", "Plan a demonstration test", "Add to an RBD"]) {
    await expect(use.getByRole("button", { name: new RegExp(step) })).toBeVisible();
  }
  await use.getByRole("button", { name: /Plan a demonstration test/ }).click();
  await expect(page).toHaveURL(/\/strategy\/test-planning\?.*model=sample-model-bearings-weibull/);

  await open(page, "/models/m/sample-model-bearings-weibull");
  // The panel no longer carries the B-lives, nor a link to them.
  await expect(page.getByRole("button", { name: /B-lives and mean life/ })).toHaveCount(0);
  await page.getByRole("tab", { name: "Calculator" }).click();
  await page.getByRole("radio", { name: "Time at reliability" }).click();
  const answer = page.locator(".calc-answer");
  await expect(answer).toContainText("(the B10 life)");
  // The model's own quantile with its one-sided lower bound, in words.
  await expect(answer).toContainText(/we're 90% sure it's at least [\d,]+ hours/);
  await page.getByRole("group", { name: "B-lives" }).getByRole("button", { name: "B50" }).click();
  await expect(answer).toContainText("(the B50 life)");
  await expect(page.getByLabel("Reliability %")).toHaveValue("50");
  await expect(page.getByRole("region", { name: "B-lives and mean life" })).toHaveCount(0);
  await expectHealthy(page, problems, { label: "model calculator", chart: true });
});

// The Model characteristics tab: the mean life with its bound at the page's
// confidence (shared with the Calculator), a Kaplan-Meier estimate's mean to a
// time, and "none, and why" where the mean is infinite.
async function saveModel(page, body) {
  const res = await page.request.post("/api/models", { multipart: body });
  expect(res.ok()).toBeTruthy();
  return (await res.json()).id;
}
const chars = (page) => page.getByRole("region", { name: "Mean life" });

test("Model characteristics: the mean life and its bound", async ({ page, problems }) => {
  await open(page, "/models/m/sample-model-bearings-weibull");
  await page.getByRole("tab", { name: "Model characteristics" }).click();
  await expect(chars(page)).toContainText("Mean life (MTTF)");
  await expect(chars(page)).toContainText(/1,270 hours\s*≥ 1,150 hours at 90%/);
  await expect(chars(page)).toContainText("Here the median is 1,240 hours");
  // A level chosen here is the Calculator's too, and the link opens Time at reliability.
  await page.getByRole("combobox", { name: "Confidence of the lower bound" }).click();
  await page.getByRole("option", { name: "95% lower bound" }).click();
  await expect(chars(page)).toContainText(/at 95%/);
  // The B-lives sit beside it, with their bounds at the same confidence.
  await expect(page.getByRole("region", { name: "B-lives" })).toContainText(/B10\s*582 hours\s*≥ \d+/);
  await page.getByRole("button", { name: /Another reliability: use Time at reliability/ }).click();
  await expect(page.locator(".calc-answer")).toContainText("(the B10 life)");
  await expect(page.getByLabel("Confidence level %")).toHaveValue("95");

  // An exponential's mean, and Kaplan-Meier's counted to a time.
  const pumps = { dataset_id: "sample-ds-pumps", x: "months", c: "censored", c_invert: "0", unit: "months" };
  const expo = await saveModel(page, { ...pumps, name: "Smoke mean exponential", distribution: "exponential" });
  await open(page, `/models/m/${expo}`);
  await page.getByRole("tab", { name: "Model characteristics" }).click();
  await expect(chars(page)).toContainText(/Mean life \(MTTF\)\s*35\.1 months\s*≥ [\d.]+ months at 90%/);
  const km = await saveModel(page, { ...pumps, name: "Smoke mean Kaplan-Meier", distribution: "kaplan_meier" });
  await open(page, `/models/m/${km}`);
  await page.getByRole("tab", { name: "Model characteristics" }).click();
  await page.getByLabel(/Count up to/).fill("20");
  await expect(chars(page)).toContainText(/Mean to 20 months\s*[\d.]+ months\s*≥ [\d.]+ months at 90%/);
  await expect(chars(page)).toContainText("counting only up to that time");

  // An infinite mean: none, and why; never Infinity.
  const heavy = await page.request.post("/api/models/from-params", {
    data: { name: "Smoke heavy tail", distribution: "loglogistic", unit: "hours",
            params: [{ name: "alpha", value: 1000 }, { name: "beta", value: 0.8 }] },
  });
  await open(page, `/models/m/${(await heavy.json()).id}`);
  await page.getByRole("tab", { name: "Model characteristics" }).click();
  await expect(chars(page)).toContainText("None");
  await expect(chars(page)).toContainText("no finite mean life");
  await expect(chars(page)).not.toContainText(/Infinity|NaN/);
  // A regression model's figures are at the Calculator's covariates.
  await open(page, "/models/m/sample-model-seal-weibull-ph");
  await page.getByRole("tab", { name: "Model characteristics" }).click();
  await expect(page.getByRole("region", { name: "At these covariates" })).toContainText("temp_C");
  await expect(page.locator(".rl-card")).toContainText("B10");
  await expectHealthy(page, problems, { label: "model characteristics" });
});

// A shared page's viewer can't ask the model's life path (it needs sign-in):
// the saved 90% figures stand, and another level says why.
test("Model characteristics on a page that can't ask for another level", async ({ page, problems }) => {
  await page.route("**/life", (r) => r.fulfill({ status: 401, contentType: "application/json",
                                                 body: '{"detail":"Not authenticated"}' }));
  await open(page, "/models/m/sample-model-bearings-weibull");
  await page.getByRole("tab", { name: "Model characteristics" }).click();
  await expect(chars(page)).toContainText(/1,270 hours\s*≥ 1,150 hours at 90%/);
  await page.getByRole("combobox", { name: "Confidence of the lower bound" }).click();
  await page.getByRole("option", { name: "99% lower bound" }).click();
  await expect(chars(page)).toContainText("needs you signed in to a copy of this model");
  await expect(chars(page)).toContainText(/≥ 1,150 hours at 90%/);
  expect(problems.filter((p) => !/status of 401\b/.test(p))).toEqual([]);
});

// The calculator's axis limits open in a dialog, apply as you type, and the
// range shows beside the button.
test("the calculator's Axes dialog", async ({ page, problems }) => {
  await open(page, "/models/m/sample-model-bearings-weibull");
  await page.getByRole("tab", { name: "Calculator" }).click();
  const axes = page.getByRole("button", { name: "Axes" });
  await expect(page.locator(".calc-axis-now")).toHaveText("Auto");
  await axes.click();
  const dialog = page.getByRole("dialog", { name: "Axes" });
  await dialog.getByLabel("From").fill("0");
  await dialog.getByLabel("To").fill("4000");
  await expect(page.locator(".calc-axis-now")).toHaveText("0 to 4,000 hours");
  await dialog.getByRole("button", { name: "Done" }).click();
  await expect(dialog).toBeHidden();
  await expect(axes).toBeFocused();
  await axes.click();
  await page.getByRole("dialog", { name: "Axes" }).getByRole("button", { name: "Reset to auto" }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".calc-axis-now")).toHaveText("Auto");
  await expectHealthy(page, problems, { label: "calculator axes", chart: true });
});
