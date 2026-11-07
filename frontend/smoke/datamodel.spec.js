// The Data model page (/data-model): the plain-words answer without graph
// access (the smoke server has none), and, with the graph's answers stubbed
// from an invented fixture, the diagram, the table, the three views, search,
// the details panel and the downloads.
import { readFile } from "node:fs/promises";
import { test, expect, open, expectHealthy } from "./health.js";
import { stubGraph } from "./fixtures/datamodel.js";

test("without graph access: says so plainly, and asks the graph nothing", async ({ page, problems }) => {
  const asked = [];
  page.on("request", (r) => {
    if (/\/api\/maintenance\/graph\//.test(r.url())) asked.push(r.url());
  });
  await open(page, "/data-model");
  await expect(page.getByRole("heading", { name: "Data model", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Not available for your account" })).toBeVisible();
  await expect(page.getByText("doesn't have graph access")).toBeVisible();
  expect(asked).toEqual([]);
  // Not in the menu for this user.
  await expect(page.getByRole("link", { name: "Data model" })).toHaveCount(0);
  await expectHealthy(page, problems, { label: "/data-model" });
});

test("with graph access: the diagram, the table, the three views and the details", async ({ page, problems }) => {
  await stubGraph(page);
  await open(page, "/data-model");
  await expect(page.getByText("These are the kinds of things your maintenance graph holds")).toBeVisible();

  // The diagram draws (cytoscape loads on this page only).
  const canvas = page.locator(".dm-canvas");
  await expect(canvas).toHaveAttribute("data-state", "ready", { timeout: 20_000 });
  await expect(canvas.locator("canvas").first()).toBeVisible();
  await expect(canvas).toHaveAttribute("aria-label", /4 kinds of thing and 5 connections/);
  await page.getByRole("button", { name: "Fit to screen" }).click();
  await page.getByRole("button", { name: "Re-layout" }).click();

  // The PNG and the Arrows file.
  const [png] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download as image" }).click()]);
  expect(png.suggestedFilename()).toBe("data-model-built.png");
  const [arrows] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download for Arrows" }).click()]);
  const file = JSON.parse(await readFile(await arrows.path(), "utf8"));
  expect(file.nodes.map((n) => n.caption).sort()).toEqual(["Box", "Room", "Shelf", "Widget"]);
  expect(file.relationships).toHaveLength(5);
  expect(file.relationships.find((r) => r.type === "PART_OF").fromId)
    .toBe(file.nodes.find((n) => n.caption === "Widget").id);

  // The table, and a kind's details from it.
  await page.getByRole("button", { name: "Table", exact: true }).click();
  const table = page.locator(".dm-table");
  await expect(table.locator("tbody tr")).toHaveCount(5);
  await expect(table.getByRole("row", { name: /Widget PART_OF Widget 60/ })).toBeVisible();
  await table.getByRole("button", { name: "Box" }).first().click();
  const details = page.getByRole("complementary", { name: "Details" });
  await expect(details.getByRole("heading", { name: "Box" })).toBeVisible();
  await expect(details.getByText("58")).toBeVisible();
  await expect(details.getByRole("listitem").filter({ hasText: "ON" })).toContainText("Shelf");
  await table.getByRole("button", { name: "ON" }).click();
  await expect(details.getByText("From Box to Shelf")).toBeVisible();

  // Counts hidden.
  await page.getByLabel("Show counts").uncheck();
  await expect(table.getByRole("columnheader", { name: "How many" })).toHaveCount(0);
  await page.getByLabel("Show counts").check();

  // Search.
  await page.getByRole("searchbox").fill("shel");
  await expect(page.getByText("1 kind and 0 connections match")).toBeVisible();
  await page.getByRole("searchbox").press("Enter");
  await expect(details.getByRole("heading", { name: "Shelf" })).toBeVisible();
  await page.getByRole("searchbox").fill("");

  // What's designed: the design only, proposed ones marked.
  await page.getByRole("button", { name: "What's designed" }).click();
  await expect(table.getByRole("row", { name: /Box INSIDE Crate .*Proposed/ })).toBeVisible();
  await expect(table.getByRole("row", { name: /Shelf/ })).toHaveCount(0);
  await expect(page.getByText("Dashed: proposed, not yet decided.")).toBeVisible();

  // Both: what's not built yet and what's not in the design.
  await page.getByRole("button", { name: "Both" }).click();
  await expect(table.getByRole("row", { name: /Box INSIDE Crate .*Designed, not built yet/ })).toBeVisible();
  await expect(table.getByRole("row", { name: /Box ON Shelf .*Built, not in the design/ })).toBeVisible();
  await expect(table.getByRole("row", { name: /Widget INSIDE Box .*Built and designed/ })).toBeVisible();
  await expect(page.getByText("Amber: built, but not in the design.")).toBeVisible();
  await table.getByRole("button", { name: "Crate" }).first().click();
  await expect(details.getByText("A big box, for moving boxes together.")).toBeVisible();

  // And the diagram of Both draws too.
  await page.getByRole("button", { name: "Diagram", exact: true }).click();
  await expect(page.locator(".dm-canvas")).toHaveAttribute("data-state", "ready", { timeout: 20_000 });
  await expect(page.locator(".dm-canvas")).toHaveAttribute("aria-label", /5 kinds of thing and 7 connections/);
  await expectHealthy(page, problems, { label: "/data-model (stubbed)" });
});

test("the graph not connected: the design still shows, and the reason is plain", async ({ page }) => {
  await stubGraph(page, { schemaStatus: 503 });
  await open(page, "/data-model");
  await expect(page.getByRole("button", { name: "What's built" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "What's designed" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("isn't connected on this server")).toBeVisible();
  await expect(page.locator(".dm-canvas")).toHaveAttribute("data-state", "ready", { timeout: 20_000 });
});

test("on a phone it opens on the table, with nothing wider than the screen", async ({ page, problems }) => {
  await page.setViewportSize({ width: 400, height: 860 });
  await stubGraph(page);
  await open(page, "/data-model");
  await expect(page.getByRole("button", { name: "Table", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".dm-table tbody tr")).toHaveCount(5);
  const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(wide).toBeLessThanOrEqual(0);
  await expectHealthy(page, problems, { label: "/data-model (phone)" });
});
