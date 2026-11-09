// The data library under Models (Derryn, 9 Nov 2026: "a good way to use models from a library.
// Especially the NUREG life models"): three levels (the sources, a source's records, a record),
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
  await expect(page).toHaveURL(/\/models\/library$/);
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
  await expect(page.getByRole("searchbox", { name: "Search the data library" })).toBeVisible();

  // A source: its records, filtered and sorted.
  await page.getByRole("link", { name: NRC }).click();
  await expect(page).toHaveURL(/\/models\/library\/nrc-inl-2020$/);
  await page.getByRole("searchbox", { name: "Search this library" }).fill("Motor-operated valve");
  const table = page.locator(".lib-table");
  // A per-demand record can't be a model: its button is off, the reason in its title.
  const perDemand = table.locator("tr", { hasText: "Motor-operated valve: fails to open" }).first();
  await expect(perDemand.getByRole("button", { name: "Use as a model…" })).toBeDisabled();
  await page.getByRole("combobox", { name: "Kind" }).selectOption("rate");
  await expect(table.locator("tr", { hasText: "fails to open" })).toHaveCount(0);
  await page.getByRole("combobox", { name: "Sort" }).selectOption("mean");

  // A record: the distribution written out and plotted, its source, the two actions.
  await table.getByRole("link", { name: SOP, exact: true }).click();
  await expect(page).toHaveURL(/\/models\/library\/nrc-inl-2020\/mov-sop$/);
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
  const lib = page.getByRole("region", { name: "Library" });
  await expect(lib.getByRole("link", { name: NRC })).toBeVisible();
  await expect(lib.getByRole("link", { name: SOP }).first()).toBeVisible();
  await expectHealthy(page, problems, { label: "the data library" });
});

// Derryn, 9 Nov: a pipe record "explicitly says a gamma model with the two parameters": the model keeps
// the gamma on its failure rate, and its page shows the 5–95% range across plants.
test("a pipe's rate record as a model keeps its gamma across plants", async ({ page, problems }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, "/models/library/nrc-inl-2020/pipe-other-ell");
  await expect(page.getByRole("heading", { name: "Pipe: external leak, large (not service water)" })).toBeVisible();
  await expect(page.locator("body")).toContainText("keeps this gamma on the rate");
  await page.getByRole("button", { name: "Use as a model…" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Use as a model" });
  const save = dialog.getByRole("button", { name: "Save the model" });
  await expect(save).toBeDisabled(); // a rate per foot needs the pipe's length
  await dialog.getByLabel("Pipe length (feet)").fill("100");
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
  // first library with usable records (handbook base rates for parts counts can't be a model); the
  // records as a table. "Every library" says what it leaves out.
  await headPick(page, "Life model", "From the data library…");
  const attach = page.getByRole("dialog", { name: "From the data library" });
  const picker = page.getByRole("dialog", { name: "Pick a library record" });
  await expect(picker).toBeVisible();
  const search = picker.getByRole("combobox", { name: "Search the data library" });
  await expect(search).toBeFocused();
  await expect(picker.getByRole("combobox", { name: "Library", exact: true })).toHaveValue("nrc-inl-2020");
  await picker.getByRole("combobox", { name: "Library", exact: true }).selectOption("");
  await expect(picker.locator(".lib-pick-status")).toContainText("Base rates for parts counts are left out");
  const options = picker.getByRole("listbox").getByRole("option");
  await expect(options).not.toHaveCount(0);
  await expect(picker.getByRole("listbox").getByRole("option", { name: /MIL-HDBK/ })).toHaveCount(0);
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
  await expect(attach.getByRole("group", { name: "The library record" })).toContainText(
    new RegExp(`${SOP} · .* per hour \\(calendar\\) · NRC/INL 2020`));
  const saved = page.waitForResponse((r) => r.url().includes(`${M}/positions/${valve.id}/models`) && r.request().method() === "POST");
  await attach.getByRole("button", { name: "Attach" }).click();
  expect((await saved).status()).toBe(200);
  await expect(attach).toHaveCount(0);
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
  await expect(fit.getByRole("status")).toContainText("conjugate", { timeout: 30_000 });
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
  await expect(fit.getByRole("status")).toContainText("prior on the mean life", { timeout: 60_000 });
  await expect(numbers.locator("tr", { hasText: "Mean life" }).locator("td").nth(1)).toContainText(/\d/);
  await expect(numbers.locator("tr", { hasText: "Shape" }).locator("td").nth(1)).toContainText(/\d/);
  await expect(fit.getByRole("status")).not.toContainText("gave the belief its numbers.");
  await fit.getByRole("combobox", { name: "Distribution" }).selectOption("exponential");
  await expect(fit.getByRole("status")).toContainText("conjugate", { timeout: 30_000 });
  const fitted = page.waitForResponse((r) => r.url().includes(`${M}/positions/${valve.id}/models`) && r.request().method() === "POST",
    { timeout: 60_000 });
  await fit.getByRole("button", { name: "Save as this position's model" }).click();
  expect((await fitted).status()).toBe(200);
  await expect(fit).toHaveCount(0);
  await expectHealthy(page, problems, { label: "library models on a position" });
});

// A library of the user's own (Derryn, 9 Nov 2026: "allow a model to be added to one"): made on the
// Library page, a saved model added from its ⋯ menu, the record in the pickers and usable as a prior.
test("build a library: a model added to it, found in the picker, used as a prior", async ({ page, request, problems }) => {
  const tag = `ul${Date.now()}`;
  await page.setViewportSize({ width: 1440, height: 900 });
  // A saved parametric model to add.
  const model = await postOk(request, "/api/models/from-params", {
    name: `Gearbox ${tag}`, distribution: "weibull", params: [{ name: "alpha", value: 2400 }, { name: "beta", value: 2.1 }], unit: "hours",
  });

  // The Library page: "Yours" above "Published", with New library….
  await open(page, "/models/library");
  await expect(page.getByRole("heading", { name: "Yours" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Published" })).toBeVisible();
  await page.getByRole("button", { name: "New library…" }).first().click();
  const form = page.getByRole("dialog", { name: "New library" });
  await form.getByLabel("Name").fill(`Site gearboxes ${tag}`);
  await form.getByLabel("What it holds (one line)").fill("Fitted models for the mill's gearboxes");
  await form.getByLabel("Notes or licence text").fill("Internal use only.");
  await form.getByRole("button", { name: "Create the library" }).click();
  await expect(page).toHaveURL(/\/models\/library\/[0-9a-f]{32}$/);
  const libraryUrl = page.url();
  await expect(page.getByRole("heading", { name: `Site gearboxes ${tag}` })).toBeVisible();
  await expect(page.locator("body")).toContainText("No records yet");

  // The model's page: ⋯ › Add to a library…, into the library just made.
  await open(page, `/models/m/${model.id}`);
  await page.getByRole("button", { name: "More actions" }).first().click();
  await page.getByRole("button", { name: "Add to a library…" }).click();
  const add = page.getByRole("dialog", { name: "Add to a library" });
  await add.getByRole("combobox", { name: "Library", exact: true }).selectOption({ label: `Site gearboxes ${tag}` });
  await add.getByLabel("Failure mode").fill("Bearing wear");
  await add.getByRole("combobox", { name: "Equipment type" }).selectOption("rotating");
  await add.getByRole("button", { name: "Add to the library" }).click();
  await expect(add.getByRole("status")).toContainText("Added");
  await add.getByRole("link", { name: "Open the record" }).click();
  await expect(page).toHaveURL(/\/models\/library\/[0-9a-f]{32}\/[0-9a-f]{32}$/);
  await expect(page.getByRole("heading", { name: `Gearbox ${tag}: Bearing wear` })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Source and licence" })).toBeVisible();
  await expect(page.locator("body")).toContainText("Internal use only.");
  await expect(page.getByRole("link", { name: `Gearbox ${tag}` })).toBeVisible(); // From the model …
  await expect(page.getByRole("button", { name: "Remove from library" })).toBeVisible();

  // The library's table has the record as a life model; the Models landing lists the library under Yours.
  await open(page, libraryUrl.replace(/^https?:\/\/[^/]+/, ""));
  await expect(page.locator(".lib-table tr", { hasText: "Bearing wear" })).toHaveCount(1);
  await expect(page.locator(".lib-table")).toContainText("Life model");
  await open(page, "/models");
  const lib = page.getByRole("region", { name: "Library" });
  await expect(lib.getByRole("heading", { name: "Yours" })).toBeVisible();
  await expect(lib.getByRole("link", { name: `Site gearboxes ${tag}` })).toBeVisible();

  // In the Explorer's fit pane, the library is in the picker's dropdown (first) and the record is a prior.
  const ago = (d) => new Date(Date.now() - d * 864e5).toISOString().slice(0, 10);
  const box = await postOk(request, `${M}/positions`, { name: `Gearbox position ${tag}` });
  await postOk(request, `${M}/positions/${box.id}/fit`, { new_item: { name: `G1 ${tag}` }, on: ago(900) });
  await postOk(request, `${M}/positions/${box.id}/remove`, { on: ago(300), reason: "failure" });
  await postOk(request, `${M}/positions/${box.id}/fit`, { new_item: { name: `G2 ${tag}` }, on: ago(300) });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${box.id}&tab=models`);
  await headPick(page, "Life model", "Fit a life model…");
  const fit = page.getByRole("region", { name: "Fit a life model" });
  await fit.getByRole("radio", { name: "With a prior" }).click();
  await fit.getByRole("combobox", { name: "Prior", exact: true }).selectOption("library");
  const picker = page.getByRole("dialog", { name: "Pick a library record" });
  const dropdown = picker.getByRole("combobox", { name: "Library", exact: true });
  await expect(dropdown.locator("option").first()).toHaveText(`Site gearboxes ${tag} (yours)`);
  await dropdown.selectOption({ label: `Site gearboxes ${tag} (yours)` });
  await picker.getByRole("listbox").getByRole("option", { name: new RegExp(`Gearbox ${tag}: Bearing wear`) }).click();
  await expect(picker).toHaveCount(0);
  await expect(fit.getByRole("group", { name: "The library record" })).toContainText(`Gearbox ${tag}: Bearing wear · mean life`);
  await expect(fit.getByRole("status")).toContainText("The record's Weibull is the prior", { timeout: 60_000 });
  const fitted = page.waitForResponse((r) => r.url().includes(`${M}/positions/${box.id}/models`) && r.request().method() === "POST",
    { timeout: 60_000 });
  await fit.getByRole("button", { name: "Save as this position's model" }).click();
  expect((await fitted).status()).toBe(200);
  await expect(fit).toHaveCount(0);
  // Life model › Add to a library… is on now that the position has a life model.
  await headMenu(page);
  await page.getByRole("menuitem", { name: "Life model", exact: true }).click();
  await expect(page.getByRole("menu", { name: "Life model" }).getByRole("menuitem", { name: "Add to a library…" })).toBeEnabled();
  await page.keyboard.press("Escape");
  await expectHealthy(page, problems, { label: "a library of the user's own" });
});
