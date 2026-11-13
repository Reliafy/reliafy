// The built-in handbooks under Libraries (Derryn, 9 Nov 2026: "a good way to use models from a library.
// Especially the NUREG life models"; moved from Models to Libraries 13 Nov 2026): three levels (the sources, a source's records, a record),
// each record usable as a model or a prior; the Explorer's "From the data library…" and the Fit
// dialog's "A library record" prior, both through "Pick a library record" (a modal search).
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { headMenu } from "./explorer.js";

const M = "/api/maintenance";
const NRC = "NRC / INL industry-average parameter estimates (2020 update)";
const SOP = "Motor-operated valve: spurious operation";

async function headPick(page, group, item) {
  await headMenu(page);
  await page.getByRole("menuitem", { name: group, exact: true }).click();
  await page.getByRole("menu", { name: group }).getByRole("menuitem", { name: item }).click();
}

test("the library's three levels, then a record used as a model", async ({ page, problems }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  // The old address lands on the new one.
  await open(page, "/data/library");
  await expect(page).toHaveURL(/\/libraries$/);
  await expect(page.getByRole("heading", { name: "All libraries", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Public", exact: true })).toBeVisible();

  // A source: its records, filtered and sorted.
  await page.getByRole("link", { name: /^NRC\/INL 2020/ }).click();
  await expect(page).toHaveURL(/\/libraries\/nrc-inl-2020$/);
  await page.getByRole("searchbox", { name: "Search this library" }).fill("Motor-operated valve");
  const table = page.locator(".lib-table");
  // A per-demand record is a model too, with its demands a year (a covariate of the record).
  const perDemand = table.locator("tr", { hasText: "Motor-operated valve: fails to open" }).first();
  await expect(perDemand.getByRole("button", { name: "Use as a model…" })).toBeEnabled();
  await page.getByRole("combobox", { name: "Kind" }).selectOption("rate");
  await expect(table.locator("tr", { hasText: "fails to open" })).toHaveCount(0);
  await page.getByRole("combobox", { name: "Sort" }).selectOption("mean");

  // A record: the distribution written out and plotted, its source, the two actions.
  await table.getByRole("link", { name: SOP, exact: true }).click();
  await expect(page).toHaveURL(/\/libraries\/nrc-inl-2020\/mov-sop$/);
  await expect(page.getByRole("heading", { name: SOP })).toBeVisible();
  await expect(page.getByRole("heading", { name: "The distribution" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Source and licence" })).toBeVisible();
  await page.getByRole("button", { name: "Use as a model…" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Use as a model" });
  await dialog.getByRole("button", { name: "Save the model" }).click();
  await expect(page).toHaveURL(/\/models\/m\//);
  await expect(page.locator("body")).toContainText("Source's 5–95%");

  // The Models landing lists the library's sources and the record just used.
  await open(page, "/models");
  const lib = page.getByRole("region", { name: "Libraries" });
  await expect(lib.getByRole("link", { name: NRC })).toBeVisible();
  await expect(lib.getByRole("link", { name: SOP }).first()).toBeVisible();
  await expectHealthy(page, problems, { label: "the data library" });
});

// Derryn, 9 Nov: a pipe record "explicitly says a gamma model with the two parameters": the model keeps
// the gamma on its failure rate, and its page shows the 5–95% range across plants.
test("a pipe's rate record as a model keeps its gamma across plants", async ({ page, problems }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, "/libraries/nrc-inl-2020/pipe-other-ell");
  await expect(page.getByRole("heading", { name: "Pipe: external leak, large (not service water)" })).toBeVisible();
  await expect(page.locator("body")).toContainText("keeps this gamma on the rate");
  await page.getByRole("button", { name: "Use as a model…" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Use as a model" });
  const save = dialog.getByRole("button", { name: "Save the model" });
  await expect(save).toBeDisabled(); // a rate per foot needs the pipe's length (a covariate with no default)
  await dialog.getByLabel("Pipe length (L)").fill("100");
  await save.click();
  await expect(page).toHaveURL(/\/models\/m\//);
  await page.getByRole("tab", { name: "Model characteristics" }).click();
  const words = page.locator(".model-chars-spread");
  await expect(words).toContainText("for 100 feet of pipe");
  await expect(words).toContainText("give it as a gamma across plants (shape 0.3");
  await expect(words).toContainText("90% of plants lie between");
  await expect(page.locator("body")).toContainText("5–95% across plants (from the source)");
  await page.getByRole("tab", { name: "Calculator" }).click();
  await expect(page.locator(".calc-answer-ci")).toContainText("5–95% across plants (from the source)");
  await expectHealthy(page, problems, { label: "a library model's page" });
});

test("attach a library record to a position, then fit with a library prior", async ({ page, request, problems }) => {
  const tag = `lib${Date.now()}`;
  const ago = (d) => new Date(Date.now() - d * 864e5).toISOString().slice(0, 10);
  const valve = await postOk(request, `${M}/positions`, { name: `Library valve ${tag}` });
  await postOk(request, `${M}/positions/${valve.id}/fit`, { new_item: { name: `V1 ${tag}` }, on: ago(700) });
  await postOk(request, `${M}/positions/${valve.id}/remove`, { on: ago(350), reason: "failure" });
  await postOk(request, `${M}/positions/${valve.id}/fit`, { new_item: { name: `V2 ${tag}` }, on: ago(350) });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${valve.id}&tab=models`);

  // Life model › From the data library…: "Pick a library record" opens over the dialog at once, on the
  // first library with usable records; the records as a table.
  await headPick(page, "Life model", "From the data library…");
  const attach = page.getByRole("dialog", { name: "From the data library" });
  const picker = page.getByRole("dialog", { name: "Pick a library record" });
  await expect(picker).toBeVisible();
  const search = picker.getByRole("combobox", { name: "Search the data library" });
  await expect(search).toBeFocused();
  await expect(picker.getByRole("combobox", { name: "Library", exact: true })).toHaveValue("nrc-inl-2020");
  await picker.getByRole("combobox", { name: "Library", exact: true }).selectOption("");
  const options = picker.getByRole("listbox").getByRole("option");
  await expect(options).not.toHaveCount(0);
  // Filter: words, then a failure mode (its choices come with counts); nothing matching offers to clear.
  await search.fill("Motor-operated valve");
  await picker.getByRole("combobox", { name: "Failure mode" }).selectOption("Spurious operation");
  const row = picker.getByRole("listbox").getByRole("option", { name: new RegExp(SOP) }).first();
  await expect(row).toBeVisible();
  await expect(row).toContainText("NRC/INL 2020");
  await expect(row).not.toContainText("INL/EXT-21-65055");
  await search.fill("xyzzy");
  await expect(picker).toContainText("No records match.");
  await picker.getByRole("button", { name: "Clear the filters" }).click();
  await expect(picker.getByRole("combobox", { name: "Failure mode" })).toHaveValue("");
  // Pick with the keyboard: the highlight moves with the arrows, Enter picks and closes the picker.
  await search.fill("Motor-operated valve");
  await picker.getByRole("combobox", { name: "Failure mode" }).selectOption("Spurious operation");
  await expect(options.first()).toContainText(SOP);
  await search.focus();
  await page.keyboard.press("ArrowDown");
  await expect(options.nth(1)).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowUp");
  await expect(options.first()).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Enter");
  await expect(picker).toHaveCount(0);
  // A published record goes on to Fix covariates: its clock (the record's own, calendar) left to the RBD.
  await expect(attach).toHaveCount(0);
  const pane = page.getByRole("region", { name: "Fix covariates" });
  await expect(pane).toBeVisible();
  await expect(pane.getByRole("checkbox", { name: "Fix Clock at this position" })).not.toBeChecked();
  const saved = page.waitForResponse((r) => r.url().includes(`${M}/positions/${valve.id}/models`) && r.request().method() === "POST");
  await pane.getByRole("button", { name: "Save at this position" }).click();
  expect((await saved).status()).toBe(200);
  await expect(pane).toHaveCount(0);
  await expect(page.locator(".tp-row", { hasText: "Library: NRC/INL 2020, Motor-operated valve spurious operation" })).toHaveCount(1);

  // Fit a life model… with "A library record" as the prior: the fit is in the table area (not a dialog);
  // choosing it opens the picker, a dialog over the pane; Escape closes only the picker, focus goes back
  // to the pane's one Pick a library record… button.
  await headPick(page, "Life model", "Fit a life model…");
  const fit = page.getByRole("region", { name: "Fit a life model" });
  await fit.getByRole("radio", { name: "With a prior" }).click();
  await expect(page.getByRole("dialog", { name: "Fit a life model" })).toHaveCount(0);
  await fit.getByRole("combobox", { name: "Prior", exact: true }).selectOption("library");
  await expect(picker).toBeVisible();
  await expect(fit).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(picker).toHaveCount(0);
  await expect(fit).toBeVisible();
  await expect(fit.getByRole("button", { name: "Pick a library record…" })).toBeFocused();
  await fit.getByRole("button", { name: "Pick a library record…" }).click();
  await expect(picker).toBeVisible();
  await search.fill("Motor-operated valve spurious");
  await expect(picker.getByRole("listbox").getByRole("option").first()).toContainText(SOP);
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("Enter");
  await expect(picker).toHaveCount(0);
  const picked = fit.getByRole("group", { name: "The library record" });
  await expect(picked).toContainText(SOP);
  await expect(fit.getByRole("button", { name: "Change the library record" })).toBeFocused();
  await expect(fit.getByRole("listbox")).toHaveCount(0); // no list inside the dialog any more
  await fit.getByRole("combobox", { name: "Distribution" }).selectOption("exponential");
  await expect(fit.locator("p.ml-lead[role=status]")).toContainText("conjugate", { timeout: 30_000 });
  // Change… opens the picker again on the record picked; Escape leaves the pick as it was.
  await fit.getByRole("button", { name: "Change the library record" }).click();
  await expect(picker.getByRole("listbox").getByRole("option", { selected: true })).toContainText("(chosen)");
  await page.keyboard.press("Escape");
  await expect(picker).toHaveCount(0);
  await expect(fit).toBeVisible();
  await expect(fit.getByRole("button", { name: "Change the library record" })).toBeFocused();
  await expect(picked).toContainText(SOP);
  // The prior shows beside the fit: its mean life and B10 as numbers, not "—".
  const numbers = fit.locator(".fit2-numbers");
  await expect(numbers.locator("tr", { hasText: "Mean life" }).locator("td").nth(1)).toContainText(/\d/);
  await expect(numbers.locator("tr", { hasText: "B10 life" }).locator("td").nth(1)).toContainText(/\d/);
  // On a Weibull the record is a prior on the mean life with the shape between bounds: the prior still shows.
  await fit.getByRole("combobox", { name: "Distribution" }).selectOption("weibull");
  await expect(fit.locator("p.ml-lead[role=status]")).toContainText("prior on the mean life", { timeout: 60_000 });
  await expect(numbers.locator("tr", { hasText: "Mean life" }).locator("td").nth(1)).toContainText(/\d/);
  await expect(numbers.locator("tr", { hasText: "Shape" }).locator("td").nth(1)).toContainText(/\d/);
  await expect(fit.locator("p.ml-lead[role=status]")).not.toContainText("gave the belief its numbers.");
  await fit.getByRole("combobox", { name: "Distribution" }).selectOption("exponential");
  await expect(fit.locator("p.ml-lead[role=status]")).toContainText("conjugate", { timeout: 30_000 });
  const fitted = page.waitForResponse((r) => r.url().includes(`${M}/positions/${valve.id}/models`) && r.request().method() === "POST",
    { timeout: 60_000 });
  await fit.getByRole("button", { name: "Save as this position's model" }).click();
  expect((await fitted).status()).toBe(200);
  await expect(fit).toHaveCount(0);
  await expectHealthy(page, problems, { label: "library models on a position" });
});

// A library of the user's own (Derryn, 13 Nov 2026): made on All libraries, a dataset and a model
// fitted on it added from their ⋯ menus, the model's entry "fitted on ↑" the dataset, used (a copy
// that says where it came from), shared with a workspace and published.
test("build a library: data and a model added, used, shared and published", async ({ page, request, problems }) => {
  const tag = `ul${Date.now()}`;
  await page.setViewportSize({ width: 1440, height: 900 });
  // A model from parameters (no data behind it): a first-class entry.
  const model = await postOk(request, "/api/models/from-params", {
    name: `Gearbox ${tag}`, distribution: "weibull", params: [{ name: "alpha", value: 2400 }, { name: "beta", value: 2.1 }], unit: "hours",
  });

  await open(page, "/libraries");
  await expect(page.getByRole("heading", { name: "All libraries", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "New library…" }).first().click();
  const form = page.getByRole("dialog", { name: "New library" });
  await form.getByLabel("Name").fill(`Site gearboxes ${tag}`);
  await form.getByLabel("What it holds (one line)").fill("Models for the mill's gearboxes");
  await form.getByRole("button", { name: "Create the library" }).click();
  await expect(page).toHaveURL(/\/libraries\/[0-9a-f]+$/);
  const libraryPath = new URL(page.url()).pathname;
  await expect(page.getByRole("heading", { name: `Site gearboxes ${tag}` })).toBeVisible();
  await expect(page.locator("body")).toContainText("Nothing in this library yet");

  // The model's page: ⋯ › Add to library…, into the library just made.
  await open(page, `/models/m/${model.id}`);
  await page.getByRole("button", { name: "More actions" }).first().click();
  await page.getByRole("button", { name: "Add to library…" }).click();
  const add = page.getByRole("dialog", { name: "Add to library" });
  await expect(add).toContainText("keeps a copy as it is now");
  await add.getByRole("combobox", { name: "Library", exact: true }).selectOption({ label: `Site gearboxes ${tag}` });
  await add.getByRole("button", { name: "Add to the library" }).click();
  await expect(add.getByRole("status")).toContainText("Added");
  await add.getByRole("link", { name: "Open the entry" }).click();
  await expect(page).toHaveURL(new RegExp(`${libraryPath}#entry-`));
  const entry = page.locator(".lib-entry", { hasText: `Gearbox ${tag}` });
  await expect(entry).toContainText("From parameters");
  await expect(entry.getByRole("button", { name: "Update from the original" })).toBeVisible();

  // Use this model: a copy, which says where it came from.
  await entry.getByRole("button", { name: "Use this model" }).click();
  await expect(entry.getByRole("status")).toContainText("Copied to your workspace");
  await entry.getByRole("status").getByRole("link").first().click();
  await expect(page).toHaveURL(/\/models\/m\//);
  await expect(page.locator(".from-library")).toContainText(`Site gearboxes ${tag}`);

  // Sharing…: public needs a licence, a citation and the right to publish.
  await open(page, libraryPath);
  await page.getByRole("button", { name: "Sharing…" }).click();
  const panel = page.getByRole("region", { name: "Sharing" });
  await panel.getByRole("radio", { name: /^Public/ }).check();
  await panel.getByRole("button", { name: "Save" }).click();
  await expect(panel.getByRole("alert")).toContainText("Choose a licence");
  await panel.getByLabel("Licence").selectOption({ index: 1 });
  await panel.getByLabel("Citation").fill(`Mill gearbox records ${tag}`);
  await panel.getByRole("checkbox", { name: "I have the right to publish this" }).check();
  await panel.getByRole("button", { name: "Save" }).click();
  await expect(panel).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Preview as public" })).toBeVisible();
  await page.getByRole("link", { name: "Preview as public" }).click();
  await expect(page.locator(".share-bar")).toBeVisible();
  await expect(page.getByRole("link", { name: "Sign in to use" }).first()).toBeVisible();
  await page.setViewportSize({ width: 400, height: 860 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  await expectHealthy(page, problems, { label: "a library of the user's own" });
});

// Bulk import into a library (Derryn, 13 Nov 2026): New dataset's "Also add to library", split by a
// column, puts every dataset it makes into the library; and a library's own Add… › Upload data….
test("an upload split into datasets goes into a library, from Data and from the library", async ({ page, request, problems }) => {
  const tag = `${Date.now()}`;
  const sheet = ["Unit,Site,Hours,Failed", ...["North", "South", "East"].flatMap((site, k) => [1, 2, 3].map((i) =>
    `${site[0]}-${i},${site},${100 * (k + 1) + 37 * i + Number(tag.slice(-3))},${i % 2}`))].join("\n") + "\n";
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, "/data");
  await page.getByRole("button", { name: "New dataset" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.locator('input[type="file"]').setInputFiles({ name: `sites ${tag}.csv`, mimeType: "text/csv", buffer: Buffer.from(sheet) });
  await dialog.getByRole("combobox", { name: "Split into datasets by" }).click();
  await page.getByRole("option", { name: "Site", exact: true }).click();
  const choose = dialog.getByRole("combobox", { name: "Also add to library" });
  await choose.selectOption("new");
  await dialog.getByRole("textbox", { name: "New library's name" }).fill(`Sites ${tag}`);
  await dialog.getByRole("button", { name: "Save 3 datasets" }).click();
  const saved = dialog.getByRole("region", { name: "Saved datasets" });
  await expect(saved.getByText("Saved 3 datasets:")).toBeVisible({ timeout: 30_000 });
  await expect(saved.getByRole("status").filter({ hasText: "Added all 3 to" })).toBeVisible();
  await saved.getByRole("link", { name: `Sites ${tag}` }).click();
  await expect(page).toHaveURL(/\/libraries\/[0-9a-f]{32}$/);
  await expect(page.getByText("3 datasets · 0 models").first()).toBeVisible();
  await expectHealthy(page, problems, { label: "a library filled by a split upload" });

  // From the library: Add… (the owner's primary) › Upload data…, this library chosen; back on the page
  // with the new entry. The menu closes like every other menu (useMenuDismiss).
  const addButton = page.getByRole("button", { name: "Add…" });
  await expect(addButton).not.toHaveClass(/secondary/);
  await expect(page.getByRole("button", { name: "Sharing…" })).toHaveClass(/secondary/);
  await addButton.click();
  await expect(page.getByRole("menuitem", { name: "Upload data…" })).toBeVisible();
  await page.getByRole("menuitem", { name: "Upload data…" }).click();
  const up = page.getByRole("dialog");
  await expect(up.getByRole("heading", { name: `Upload data to Sites ${tag}` })).toBeVisible();
  await up.locator('input[type="file"]').setInputFiles({
    name: `west ${tag}.csv`, mimeType: "text/csv",
    buffer: Buffer.from(`Hours,Failed\n${410 + Number(tag.slice(-3))},1\n620,0\n900,1\n1050,0\n`),
  });
  await expect(up.getByRole("combobox", { name: "Also add to library" })).toHaveValue(/[0-9a-f]{32}/);
  await up.getByRole("button", { name: "Create dataset" }).click();
  await expect(up).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByRole("status").filter({ hasText: "Added it to" })).toBeVisible();
  await expect(page.getByText("4 datasets · 0 models").first()).toBeVisible();
  await expect(page.getByText(`west ${tag}`)).toBeVisible();
  // The "Added it to …" line goes with the next thing done on the page.
  await page.getByRole("button", { name: "Sharing…" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Added it to" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Sharing" }).getByRole("radio", { name: /^Private/ })).toBeChecked();
  await page.getByRole("region", { name: "Sharing" }).getByRole("button", { name: "Close" }).click();
  // On a phone: opened at 400 px, nothing scrolls sideways.
  const here = new URL(page.url()).pathname;
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, here);
  await expect(page.getByText("4 datasets · 0 models").first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  await expectHealthy(page, problems, { label: "a library after Upload data…" });
});
