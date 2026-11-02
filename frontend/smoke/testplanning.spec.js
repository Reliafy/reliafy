// Strategy › Test planning: every tab computes a plan and draws it, and the
// old Demonstration test address lands on the Demonstration tab with its
// query string. (The pages themselves are opened by pages.spec.js.)
import { test, expect, open, expectHealthy, DEPLOYED } from "./health.js";

test("the old demonstration-test address opens the Demonstration tab, keeping its requirement", async ({ page, problems }) => {
  await open(page, "/strategy/demonstration-test?b=10&life=1000&conf=90&unit=hours");
  await expect(page).toHaveURL(/\/strategy\/test-planning\?b=10&life=1000&conf=90&unit=hours$/);
  await expect(page.getByRole("tab", { name: "Demonstration" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("B-life (% failed)")).toHaveValue("10");
  await expectHealthy(page, problems, { label: "redirected demonstration test" });
});

test("Demonstration: an MTBF test that stops at a failure", async ({ page, problems }) => {
  await open(page, "/strategy/test-planning");
  await page.getByRole("radio", { name: "MTBF (constant rate)" }).click();
  await page.getByRole("radio", { name: "At the last failure allowed" }).click();
  await page.getByLabel("Failures allowed").fill("2");
  await page.getByRole("button", { name: "Compute" }).click();
  await expect(page.getByText(/Run until failure/).first()).toBeVisible({ timeout: 20_000 });
  await expectHealthy(page, problems, { label: "failure-terminated test", chart: true });
});

const TABS = [
  ["Sequential test", "/strategy/test-planning/sequential", /on average/],
  ["Life test", "/strategy/test-planning/life", /within a factor of/],
  ["Accelerated test", "/strategy/test-planning/accelerated", /each for 1,000 hours/],
  ["Comparison", "/strategy/test-planning/comparison", /operation after it|after the change/],
];

for (const [tab, path, answer] of TABS) {
  test(`${tab}: computes a plan and draws it`, async ({ page, problems }) => {
    await open(page, "/strategy/test-planning");
    await page.getByRole("tab", { name: tab }).click();
    await expect(page).toHaveURL(new RegExp(`${path}$`));
    await page.getByRole("button", { name: "Compute" }).click();
    await expect(page.locator(".rs-sentence")).toContainText(answer, { timeout: 30_000 });
    await expectHealthy(page, problems, { label: `${tab} plan`, chart: true });
  });
}

test("Life test: the simulation check runs (billing is off locally)", async ({ page, problems }) => {
  await open(page, "/strategy/test-planning/life");
  await page.getByRole("button", { name: "Compute" }).click();
  await page.getByRole("button", { name: "Simulate this test (Pro)" }).click();
  await expect(page.locator(".tp-sim-out")).toContainText(/simulated tests/, { timeout: 60_000 });
  await expectHealthy(page, problems, { label: "life test simulation", chart: true });
});

// Percentage fields (the 18 Oct UX review): typed as a percentage, checked in
// percent before anything is computed, and a value of 1 or less questioned
// ("Did you mean 99%?") instead of taken as a tiny percentage. Plus the
// workspace's currency symbol on the Strategy tools' costs.
test("Test planning: 150% gets a message in percent and Compute waits", async ({ page, problems }) => {
  await open(page, "/strategy/test-planning");
  await page.getByLabel("Target reliability").fill("150");
  await expect(page.getByText("Enter a percentage between 0 and 100, e.g. 95.")).toBeVisible();
  await expect(page.getByText(/between 0 and 1\b/)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Compute" })).toBeDisabled();
  await page.getByLabel("Target reliability").fill("95");
  await expect(page.getByRole("button", { name: "Compute" })).toBeEnabled();
  await expectHealthy(page, problems, { label: "test planning percent check" });
});

test("Failure finding: 0.99 asks 'Did you mean 99%?' and computes only once answered", async ({ page, problems }) => {
  await open(page, "/strategy/failure-finding");
  const field = page.getByLabel("Target availability");
  await field.fill("0.99");
  await expect(page.getByText("Did you mean 99%?")).toBeVisible();
  await expect(page.getByRole("button", { name: "Compute" })).toBeDisabled();
  await page.getByRole("button", { name: "Use 99%" }).click();
  await expect(field).toHaveValue("99");
  await expect(page.getByRole("button", { name: "Compute" })).toBeEnabled({ timeout: 15_000 });
  await page.getByRole("button", { name: "Compute" }).click();
  await expect(page.locator(".rs-sentence")).toContainText("99%", { timeout: 20_000 });
  // Keeping the small value is a choice, said with the % sign.
  await field.fill("0.99");
  await page.getByRole("button", { name: "Keep 0.99%" }).click();
  await expect(field).toHaveValue("0.99%");
  await expect(page.getByRole("button", { name: "Compute" })).toBeEnabled();
  await expectHealthy(page, problems, { label: "failure finding percent check" });
});

test("Settings: the currency symbol labels replacement costs", async ({ page, problems }) => {
  test.skip(DEPLOYED, "writes a setting");
  await open(page, "/settings");
  // The Currency card's own form (Settings has other Save buttons).
  const form = page.locator("form").filter({ has: page.getByLabel("Currency symbol") });
  await form.getByLabel("Currency symbol").fill("€");
  await form.getByRole("button", { name: "Save" }).click();
  await expect(form.getByText("Saved.")).toBeVisible();
  await open(page, "/strategy/replacement");
  await expect(page.getByText("Planned replacement cost (€)")).toBeVisible();
  await open(page, "/settings");
  await form.getByLabel("Currency symbol").fill("$");
  await form.getByRole("button", { name: "Save" }).click();
  await expect(form.getByText("Saved.")).toBeVisible();
  await expectHealthy(page, problems, { label: "currency symbol" });
});
