// Model addresses: another kind's id opens that model's own page, and an id no
// list knows says so with links back, instead of the error page.
import { test, expect, open, expectHealthy } from "./health.js";

test("a condition and life model's id on the non-repairable address opens its own page", async ({ page, request, problems }) => {
  const id = (await (await request.get("/api/joint/models")).json()).models?.[0]?.id;
  test.skip(!id, "no condition and life model to try");
  await open(page, `/models/m/${id}`);
  await expect(page).toHaveURL(new RegExp(`/models/joint/${id}$`));
  await expectHealthy(page, problems, { label: "non-repairable address with a joint id" });
});

test("a non-repairable model's id on the repairable address opens its own page", async ({ page, request }) => {
  const id = (await (await request.get("/api/models")).json()).models?.find((m) => m.kind !== "joint")?.id;
  test.skip(!id, "no non-repairable model to try");
  await open(page, `/models/recurrent/${id}`);
  await expect(page).toHaveURL(new RegExp(`/models/m/${id}$`));
  await expect(page.locator(".mf-answer").first()).toBeVisible();
  await expect(page.getByText("We couldn't find this model.")).toHaveCount(0);
});

test("an unknown model id says so and links back", async ({ page }) => {
  await open(page, "/models/alt/no-such-model");
  await expect(page.getByText("We couldn't find this model.")).toBeVisible();
  await expect(page.getByRole("link", { name: "See your accelerated life models" })).toBeVisible();
  await expect(page.getByRole("link", { name: "All models" })).toBeVisible();
  await expect(page.locator(".error-boundary")).toHaveCount(0);
});

test("a detail page that can't load links back to its list", async ({ page }) => {
  await open(page, "/forecasts/no-such-forecast");
  await expect(page.getByRole("link", { name: "See all forecasts" })).toBeVisible();
});
