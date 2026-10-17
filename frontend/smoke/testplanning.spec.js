// Strategy › Test planning: every tab computes a plan and draws it, and the
// old Demonstration test address lands on the Demonstration tab with its
// query string. (The pages themselves are opened by pages.spec.js.)
import { test, expect, open, expectHealthy } from "./health.js";

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
