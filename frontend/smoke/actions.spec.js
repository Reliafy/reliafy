// The main path through the app: fit a model to a sample dataset and save it.
// (Calculating an RBD is in rbd.spec.js.)
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { SMOKE_PRODUCT } from "./seed.js";
import { EXPLORER_PARTS_CLASSES_TABS } from "../src/explorerTabs.js";

test("fit and save a Weibull model from a sample dataset", async ({ page, problems }) => {
  await open(page, "/data/sample-ds-bearings");
  await page.getByRole("button", { name: "Fit a model" }).click();
  await expect(page).toHaveURL(/\/models\/new\?dataset=sample-ds-bearings/);
  // No column step: the dataset's reading in one line, then the model.
  await expect(page.locator('[data-wt="reading-summary"]')).toContainText("x = ");
  await page.getByRole("button", { name: "Fit Weibull" }).click();
  await expect(page.getByText("Shape β").first()).toBeVisible({ timeout: 30_000 });
  await expectHealthy(page, problems, { label: "fitted model", chart: true });

  await page.getByRole("button", { name: "Save this model", exact: true }).click();
  // Not named yet: Save asks for a name, starting from the default.
  await page.getByRole("dialog", { name: "Name this model" }).getByRole("button", { name: "Save model", exact: true }).click();
  await page.waitForURL(/\/models\/m\/[0-9a-f]{32}$/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: /Weibull/ })).toBeVisible();
  await expectHealthy(page, problems, { label: "saved model", chart: true });
});

// Start and stop rows with a failure flag (covariates that change over time):
// the dataset page offers the non-repairable fit, not a degradation one, and
// it opens with the columns mapped and fits to a covariate schedule.
test("data with covariates that change over time fits a non-repairable model", async ({ page, problems }) => {
  await open(page, "/data/sample-ds-pump-load");
  await expect(page.getByRole("button", { name: "Fit a degradation model" })).toHaveCount(0);
  await page.getByRole("button", { name: "Fit a non-repairable model with covariates that change over time" }).click();
  await expect(page).toHaveURL(/\/models\/new\?dataset=sample-ds-pump-load/);
  // The reading has the start and stop rows; a life model reads one life per item,
  // a regression on Z fits the covariates over time.
  const summary = page.locator('[data-wt="reading-summary"]');
  await expect(summary).toContainText("range = start_h to stop_h");
  await expect(summary).toContainText("a life model reads one life per item");
  await page.getByRole("radio", { name: /Regression on Z/ }).click();
  await expect(page.getByText(/Covariates change over time/)).toBeVisible();
  await page.getByRole("button", { name: "Fit Weibull PH" }).click();
  await expect(page.getByText(/Weibull PH, covariates changing over time/)).toBeVisible({ timeout: 30_000 });
  await page.getByRole("tab", { name: "Calculator" }).click();
  await expect(page.getByText("Covariate schedule").first()).toBeVisible();
  await expectHealthy(page, problems, { label: "time-varying fit", chart: true });

  // The shared picker offers it for a non-repairable fit (not greyed).
  await open(page, "/models/new");
  await page.getByRole("button", { name: /Fit to data/ }).click();
  await page.getByRole("searchbox", { name: "Search datasets" }).fill("changing load");
  await expect(page.getByRole("radio", { name: /Pump bearings under changing load/ })).toBeEnabled();
});

// New model › Fit to data opens on the saved-data list: every saved dataset (yours, then the
// samples), a picked one previewed with how its columns read, then fitted like any other.
test("fit a new model from a saved dataset picked in the list", async ({ page, problems }) => {
  const made = await postOk(page.request, "/api/datasets/paste",
    { name: "Smoke saved lives", content: "hours,censored\n120,0\n340,0\n500,1\n610,0\n800,1\n" });
  try {
    await open(page, "/models/new");
    await page.getByRole("button", { name: /Fit to data/ }).click();
    await expect(page.getByRole("tab", { name: "Saved data" })).toHaveAttribute("aria-selected", "true");
    await page.getByRole("searchbox", { name: "Search datasets" }).fill("smoke saved");
    await page.getByRole("radio", { name: /Smoke saved lives/ }).click();
    await expect(page.locator('[data-wt="reading-summary"]')).toContainText("c = censored");
    await expect(page.getByText(/3\s+failures, 2 still running/)).toBeVisible();
    // A repairable sample is listed, greyed, with what to fit it with instead.
    await page.getByRole("searchbox", { name: "Search datasets" }).fill("compressor fleet");
    await expect(page.getByRole("radio", { name: /Compressor fleet/ })).toBeDisabled();
    await expect(page.getByText("Repeated failures of the same units: fit a repairable model instead.")).toBeVisible();
    await page.getByRole("searchbox", { name: "Search datasets" }).fill("smoke saved");
    await page.getByRole("button", { name: "Next" }).click();
    // Saved without a reading (as before readings): guessed, checked once with "Looks right".
    const summary = page.locator('[data-wt="reading-summary"]');
    await expect(summary).toContainText("guessed — check it");
    await expect(page.getByRole("button", { name: "Fit Weibull" })).toBeDisabled();
    await summary.getByRole("button", { name: "Looks right" }).click();
    await expect(summary).not.toContainText("guessed");
    const kept = await (await page.request.get(`/api/datasets/${made.id}`)).json();
    expect(kept.reading_source).toBe("saved");
    // Change opens the upload's selectors, kept for the dataset.
    await summary.getByRole("button", { name: "Change" }).click();
    await expect(page.locator(".reading-change")).toBeVisible();
    await page.locator(".reading-change").getByRole("button", { name: "Cancel" }).click();
    await page.getByRole("button", { name: "Fit Weibull" }).click();
    await expect(page.getByText("Shape β").first()).toBeVisible({ timeout: 30_000 });
    await expectHealthy(page, problems, { label: "fit from a saved dataset", chart: true });
  } finally {
    await page.request.delete(`/api/datasets/${made.id}`);
  }
});

// New model › Model step › With a prior: the prior asked as the Explorer asks it, fitted through the
// same prior path, the prior's curve under the fit, and saved as a Bayesian model keeping its prior.
test("fit a new model with a prior and save it with its prior", async ({ page, problems }) => {
  await open(page, "/models/new?dataset=sample-ds-bearings");
  await expect(page.locator('[data-wt="reading-summary"]')).toBeVisible();
  await page.getByRole("radio", { name: "With a prior" }).click();
  await page.getByLabel("Prior", { exact: true }).selectOption("params");
  await expect(page.getByRole("button", { name: "Fit with the prior" })).toBeDisabled();
  await page.getByLabel("Characteristic life (alpha)").fill("1000");
  await page.getByLabel("Shape (beta)").fill("2");
  await page.getByRole("button", { name: "Fit with the prior" }).click();
  await expect(page.getByText(/the best B10 is about/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("90% credible band")).toBeVisible();
  await expectHealthy(page, problems, { label: "fit with a prior", chart: true });
  await page.getByRole("textbox", { name: "Model name" }).fill("Smoke bearings with a prior");
  await page.getByRole("button", { name: "Save this model", exact: true }).click();
  await page.waitForURL(/\/models\/m\/[0-9a-f]{32}$/, { timeout: 30_000 });
  const id = page.url().split("/").pop();
  const model = await (await page.request.get(`/api/models/${id}`)).json();
  try {
    expect(model.results.method).toBe("bayesian_update");
    expect(model.results.bayes.baseline.source).toBe("params");
  } finally {
    await page.request.delete(`/api/models/${id}`);
  }
});

// Every new-model flow picks its data from the one shared list (DatasetPicker): the datasets
// that kind of model takes first, the rest greyed with what to fit them with instead.
test("repairable, accelerated, degradation and condition-and-life flows share the saved-data list", async ({ page, problems }) => {
  await open(page, "/models/recurrent/new");
  await page.getByRole("button", { name: /Fit to event data/ }).click();
  await page.getByRole("searchbox", { name: "Search datasets" }).fill("bearing fatigue");
  await expect(page.getByRole("radio", { name: /Bearing fatigue test/ }).first()).toBeDisabled();
  await expect(page.getByText(/fit a non-repairable model instead/).first()).toBeVisible();
  await page.getByRole("searchbox", { name: "Search datasets" }).fill("compressor fleet");
  await page.getByRole("radio", { name: /Compressor fleet/ }).click();
  await page.getByRole("button", { name: "Use this dataset" }).click();
  // No column step: the dataset's reading in one line, then the model.
  await expect(page.locator('[data-wt="reading-summary"]')).toBeVisible();
  await expect(page.getByText(/Choose how repairs work/)).toBeVisible();

  await open(page, "/models/alt/new");
  await page.getByRole("radio", { name: /Insulating fluid/ }).click();
  await page.getByRole("button", { name: "Use this dataset" }).click();
  // No column step: the dataset's reading in one line; the stresses are the Model step's.
  await expect(page.locator('[data-wt="reading-summary"]')).toBeVisible();
  await expect(page.getByText("Life-stress relationship", { exact: true })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Stress 1 column" })).toBeVisible();
  // The upload tab still takes a file.
  await open(page, "/models/alt/new");
  await page.getByRole("tab", { name: "Upload a file" }).click();
  await expect(page.locator('input[type="file"]')).toHaveCount(1);

  await open(page, "/models/degradation");
  await page.getByRole("button", { name: "New model" }).first().click();
  await page.getByRole("radio", { name: /Brake pad wear/ }).click();
  await page.getByRole("button", { name: "Use this dataset" }).click();
  // No column step: i, x and m from the dataset's reading; the threshold is the Model step's.
  await expect(page.locator('[data-wt="reading-summary"]')).toContainText("wear_mm");
  await expect(page.getByRole("spinbutton", { name: "Failure threshold" })).toBeVisible();
  await page.keyboard.press("Escape");

  await open(page, "/models/joint/new");
  await page.getByRole("searchbox", { name: "Search datasets" }).fill("feed pumps");
  await page.getByRole("radio", { name: /Feed pumps/ }).click();
  await expect(page.getByText(/Measurements · 314 readings/)).toBeVisible();
  await expectHealthy(page, problems, { label: "condition and life dataset picked" });
});

// #31: a class with a fitted model and a spare with a lead time shows how many to
// hold, and the chance a typed stock runs out (smoke/seed.js makes the class).
// The Classes tab is hidden for now (explorerTabs.js): a class's old address lands on the Explorer, and the
// stock levels have no screen to test until the tab comes back.
test("a class's old address lands on the Explorer, with no Classes tab", async ({ page, problems }) => {
  test.skip(EXPLORER_PARTS_CLASSES_TABS, "the Classes tab is shown: the stock levels test below covers it");
  await open(page, `/asset-register/classes/${encodeURIComponent("Smoke test pump")}`);
  await expect(page).toHaveURL(/\/asset-register\/explorer(\?|$)/);
  await expect(page).not.toHaveURL(/tab=classes/);
  await expect(page.getByRole("tab", { name: "Classes" })).toHaveCount(0);
  await expectHealthy(page, problems, { label: "class address, Classes tab hidden" });
});

test("a class's spares stock levels and the what-if", async ({ page, problems }) => {
  test.skip(!EXPLORER_PARTS_CLASSES_TABS, "the Classes tab is hidden for now");
  // A class's old address opens the Explorer's Classes tab on that class.
  await open(page, `/asset-register/classes/${encodeURIComponent("Smoke test pump")}`);
  await expect(page).toHaveURL(/\/asset-register\/explorer\?tab=classes&scope=all&class=Smoke(%20|\+)test(%20|\+)pump/);
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
  // The seeded conveyor is at the depot.
  await expect(page.getByRole("treeitem", { name: /^Depot conveyor \(smoke test\)/ })).toHaveCount(0);
  await page.getByRole("link", { name: "Show every position" }).click();
  await expect(page).toHaveURL(/\/asset-register\/explorer\?arrange=positions$/);
  await expect(page.getByRole("heading", { name: "Explorer", exact: true })).toBeVisible();
  await expect(page.locator(".tp-notice")).toHaveCount(0);
  await expectHealthy(page, problems, { label: "positions" });

  await open(page, "/asset-register");
  await depot.getByRole("link", { name: "Smoke test depot", exact: true }).click();
  // An asset opens in the Explorer, arranged by locations, with the asset picked.
  await expect(page).toHaveURL(/\/asset-register\/explorer\?arrange=locations&sel=/);
  await expect(page.getByRole("heading", { name: "Explorer", exact: true })).toBeVisible();
  await expect(page.getByRole("treeitem", { name: /^Smoke test depot\b/ })).toBeVisible();
  await expect(page.locator(".td-title")).toContainText("Smoke test depot");
  await expectHealthy(page, problems, { label: "an asset in the Explorer" });
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
  // A new file is saved as a dataset first, through New dataset's reading screen.
  const dialog = page.getByRole("dialog", { name: "Save the data as a dataset" });
  await expect(dialog.getByText("Your first row looks like data, so we've treated it as data.")).toBeVisible();
  // One selector per input, labelled x, c, n…: col 1 is read as x.
  await expect(dialog.getByRole("combobox", { name: "x", exact: true })).toContainText("col 1");

  // The column of decimals is offered as n (a count) only with the reason, and can't be picked.
  const count = page.getByRole("option", { name: /^col 2/ });
  // Open the list once the dialog has read the file (CI can be slower than the click).
  await expect(async () => {
    await dialog.getByRole("combobox", { name: "n", exact: true }).click();
    await expect(count).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 20_000 });
  await expect(count).toBeDisabled();
  await expect(count).toContainText("has decimals");
  // Close the list by clicking the dialog's own text (Escape would close the dialog too).
  await dialog.getByText("How the columns are read for modelling").click();
  await expect(count).toBeHidden();

  // c is required: a status column, or "every row failed" said on purpose.
  await expect(dialog.getByRole("button", { name: "Create dataset" })).toBeDisabled();
  await expect(dialog.getByText(/beside c/)).toBeVisible();
  await dialog.getByLabel("No status column: every row failed").check();
  // No unit can be guessed from "col 1": the unit box is empty, but nothing is blocked.
  await expect(dialog.getByRole("combobox", { name: "Unit of the values" })).toHaveValue("");
  await dialog.getByRole("button", { name: "Create dataset" }).click();
  await expect(page.locator('[data-wt="reading-summary"]')).toContainText("c = every row failed");
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

test("a headerless CSV is detected, saved as a dataset with its reading, fitted and saved", async ({ page, problems }) => {
  await uploadAndFit(page);
  await expectHealthy(page, problems, { label: "fitted headerless CSV", chart: true });
  await page.getByRole("button", { name: "Save this model", exact: true }).click();
  await page.getByRole("dialog", { name: "Name this model" }).getByRole("button", { name: "Save model", exact: true }).click();
  await expectSavedWithData(page);
  await expectHealthy(page, problems, { label: "saved model", chart: true });
});

test("a fit left unsaved is offered for saving on the next visit to Models", async ({ page, problems }) => {
  await uploadAndFit(page);
  await open(page, "/models");
  await expect(page.getByText("You left a fit without saving it")).toBeVisible();
  await page.getByRole("button", { name: "Save it", exact: true }).click();
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
  // The thumbnail is a button: reach it with the keyboard and open it with Enter.
  const thumb = page.getByRole("button", { name: /^Open photo \d+ of \d+: Smoke nameplate$/ });
  await thumb.focus();
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: "Link or move…" }).click();
  const picker = page.locator(".modal").filter({ hasText: "Link or move this photo" });
  await picker.getByLabel(/Move it there/).check();
  await picker.getByLabel("Kind").selectOption("Position");
  await picker.getByLabel("Which position").selectOption(wo.position.id);
  await picker.getByRole("button", { name: "Move", exact: true }).click();
  await expect(page.getByRole("button", { name: /Smoke nameplate/ })).toHaveCount(0);
  await expectHealthy(page, problems, { label: "work order after moving a photo" });

  const position = await (await page.request.get(`/api/maintenance/positions/${wo.position.id}`)).json();
  expect(position.photos.map((p) => p.id)).toContain(photoId);
  await open(page, `/asset-register/positions/${wo.position.id}`);
  await expect(page.getByRole("button", { name: /^Open photo \d+ of \d+: Smoke nameplate$/ })).toBeVisible();
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
  await expect(reading).toContainText("β is above 1 at 90% confidence"); // one level everywhere (#818)
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
  // The field is labelled "Reliability"; the % is a visible suffix beside the box.
  await expect(page.getByLabel("Reliability", { exact: true })).toHaveValue("50");
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
  await expect(page.getByLabel("Confidence level", { exact: true })).toHaveValue("95");

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

// No ready-made product: the Explorer's tree menu has the import and export, nothing to
// open. A product's RCM tab (the seeded pump skid's): its evidence check (a run-to-failure
// decision its bearing model contradicts) and the RCM's Show only filters.
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
test("the Explorer's menu offers no ready-made product; a product's RCM tab checks its evidence", async ({ page, request, problems }) => {
  // Wide enough for the usual columns to include the Evidence check.
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, "/asset-register/explorer?arrange=positions&tab=rcm");
  await page.getByRole("button", { name: /^Tree options/ }).click();
  const options = page.getByRole("menu", { name: "Tree options" });
  await expect(options.getByRole("menuitem", { name: "Import from Excel…" })).toBeVisible();
  await expect(options.getByRole("menuitem", { name: /Survey quadcopter|sample truck/ })).toHaveCount(0);
  await page.keyboard.press("Escape");

  const { products } = await (await request.get("/api/maintenance/products")).json();
  const product = products.find((p) => p.name === SMOKE_PRODUCT);
  expect(product, "the seeded smoke test pump skid").toBeTruthy();
  await open(page, `/products/${product.id}?view=rcm&sel=${product.id}`);
  await expect(page.getByRole("tab", { name: "RCM" })).toHaveAttribute("aria-selected", "true");
  const grid = page.getByRole("treegrid", { name: /and their RCM/ });
  await expect(grid.getByRole("columnheader", { name: "Evidence check" })).toBeVisible();
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/1440-product-rcm.png` });
  const showOnly = async (name) => {
    await page.getByRole("button", { name: /^Tree options/ }).click();
    await options.getByRole("menuitemcheckbox", { name }).click();
    await expect(options.getByRole("menuitemcheckbox", { name })).toHaveAttribute("aria-checked", "true");
    await options.getByRole("menuitem", { name: "Done" }).click();
  };
  const done = async (name) => {
    await page.getByRole("button", { name: /^Tree options/ }).click();
    await options.getByRole("menuitemcheckbox", { name }).click();
    await options.getByRole("menuitem", { name: "Done" }).click();
  };
  // Evidence to look at: the bearing's run-to-failure, contradicted by its model.
  await showOnly("Evidence to look at");
  const bearing = grid.getByRole("row", { name: /^Failure mode: Bearing seizure/ }).first();
  await expect(bearing).toBeVisible();
  await expect(bearing).toContainText("Contradicted");
  await expect(grid.getByRole("row", { name: /^Failure mode: Winding insulation breaks down/ })).toHaveCount(0);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/1440-product-rcm-evidence.png` });
  await done("Evidence to look at");
  // Needs a decision: the winding's, left undecided on purpose.
  await showOnly("Needs a decision");
  await expect(grid.getByRole("row", { name: /^Failure mode: Winding insulation breaks down/ }).first()).toBeVisible();
  await expect(grid.getByRole("row", { name: /^Failure mode: Bearing seizure/ })).toHaveCount(0);
  await done("Needs a decision");
  await expectHealthy(page, problems, { label: "a product's RCM tab" });
});

// The empty tree: what to do first (a position, or the hierarchy from Excel) and the guides.
// No sample to open.
test("the empty tree offers New position, Import from Excel and the guides, no sample", async ({ page, problems }) => {
  // The tree read as empty (the suite's own isn't).
  await page.route("**/api/maintenance/tree", async (route) => {
    const res = await route.fetch();
    await route.fulfill({ response: res, json: { ...(await res.json()), positions: [], locations: [] } });
  });
  for (const [width, height] of [[1440, 900], [400, 860]]) {
    await page.setViewportSize({ width, height });
    await open(page, "/asset-register/explorer?arrange=positions");
    const empty = page.locator(".section-empty").first();
    await expect(empty).toContainText("No positions yet");
    await expect(empty).toContainText("Add the first position, or bring your hierarchy in from Excel.");
    await expect(empty.getByRole("button", { name: "New position" })).toBeVisible();
    await expect(empty.getByRole("button", { name: "Import from Excel" })).toBeVisible();
    await expect(empty.getByRole("button", { name: "How to build your asset tree" })).toBeVisible();
    await expect(empty).not.toContainText(/quadcopter|sample/i);
    await expect(page.locator(".ae-sample")).toHaveCount(0);
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/${width}-explorer-empty.png` });
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth))
      .toBeLessThanOrEqual(0);
  }
  // Import from Excel opens the tree's import.
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, "/asset-register/explorer?arrange=positions");
  await page.locator(".section-empty").first().getByRole("button", { name: "Import from Excel" }).click();
  await expect(page.locator("#ts-import")).toBeVisible();
  await expectHealthy(page, problems, { label: "the empty tree" });
});

// Maintenance on a phone: a task named with one unbreakable code (as imported
// ones often are) widens Orders' Due soon table, which then
// scrolls inside its card; the page itself never scrolls sideways.
test("Maintenance at 400 px: a wide due table scrolls in its card, not the page", async ({ page, request, problems }) => {
  const tag = `${Date.now() % 1000000}`;
  const p = await postOk(request, "/api/maintenance/positions", { name: `GBX_${tag}` });
  await postOk(request, `/api/maintenance/positions/${p.id}/tasks`,
               { name: `PM_WEEKLY_LUBRICATION_CHECK_GEARBOX_BEARINGS_${tag}`, interval: 1, unit: "days", outcome: "on_condition" });
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, "/maintenance/work-orders?tab=due");
  const row = page.getByRole("row", { name: new RegExp(`PM_WEEKLY_LUBRICATION_CHECK_GEARBOX_BEARINGS_${tag}`) });
  await expect(row).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  // The table is wider than the card, and it is the card's scroller that holds it.
  const box = await row.locator("xpath=ancestor::div[contains(@class, 'maint-scroll')]").evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(box).toBeGreaterThan(0);
  await expectHealthy(page, problems, { label: "maintenance on a phone" });
  await postOk(request, `/api/maintenance/positions/${p.id}/retire`, { reason: "smoke test" });
});
