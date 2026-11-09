// The data library under Models (Derryn, 9 Nov 2026: "a good way to use models from a library.
// Especially the NUREG life models"): three levels (the sources, a source's records, a record),
// each record usable as a model or a prior; the Explorer's "From the data library…" and the Fit
// dialog's "A library record" prior.
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

test("attach a library record to a position, then fit with a library prior", async ({ page, request, problems }) => {
  const tag = `lib${Date.now()}`;
  const ago = (d) => new Date(Date.now() - d * 864e5).toISOString().slice(0, 10);
  const valve = await postOk(request, `${M}/positions`, { name: `Library valve ${tag}` });
  await postOk(request, `${M}/positions/${valve.id}/fit`, { new_item: { name: `V1 ${tag}` }, on: ago(700) });
  await postOk(request, `${M}/positions/${valve.id}/remove`, { on: ago(350), reason: "failure" });
  await postOk(request, `${M}/positions/${valve.id}/fit`, { new_item: { name: `V2 ${tag}` }, on: ago(350) });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${valve.id}&tab=models`);

  // Life model › From the data library…: the record attached, cited in its row's Source.
  await headPick(page, "Life model", "From the data library…");
  const attach = page.getByRole("dialog", { name: "From the data library" });
  await attach.getByRole("searchbox", { name: "Search the data library" }).fill("Motor-operated valve spurious");
  await attach.getByRole("radio", { name: new RegExp(SOP) }).first().check();
  const saved = page.waitForResponse((r) => r.url().includes(`${M}/positions/${valve.id}/models`) && r.request().method() === "POST");
  await attach.getByRole("button", { name: "Attach" }).click();
  expect((await saved).status()).toBe(200);
  await expect(attach).toHaveCount(0);
  await expect(page.locator(".tp-row", { hasText: "Library: NRC/INL 2020, Motor-operated valve spurious operation" })).toHaveCount(1);

  // Fit a life model… with "A library record" as the prior: on an exponential, exact (conjugate).
  await headPick(page, "Life model", "Fit a life model…");
  const fit = page.getByRole("dialog", { name: "Fit a life model" });
  await fit.getByRole("radio", { name: "With a prior" }).click();
  await fit.getByRole("combobox", { name: "Prior", exact: true }).selectOption("library");
  await fit.getByRole("combobox", { name: "Distribution" }).selectOption("exponential");
  await fit.getByRole("searchbox", { name: "Search the data library" }).fill("Motor-operated valve spurious");
  await fit.getByRole("radio", { name: new RegExp(SOP) }).first().check();
  await expect(fit.getByRole("status")).toContainText("conjugate", { timeout: 30_000 });
  const fitted = page.waitForResponse((r) => r.url().includes(`${M}/positions/${valve.id}/models`) && r.request().method() === "POST",
    { timeout: 60_000 });
  await fit.getByRole("button", { name: "Save as this position's model" }).click();
  expect((await fitted).status()).toBe(200);
  await expect(fit).toHaveCount(0);
  await expectHealthy(page, problems, { label: "library models on a position" });
});
