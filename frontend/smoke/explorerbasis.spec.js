// The working behind a function's performance standard (Explorer › RCM tab),
// written in the function's "Notes and rationale" since Nov 2026: the hint on
// the box, Markdown shown formatted, a hostile text staying inert, a PDF added
// at the end of the section, a working written before (standard_basis) read
// inside the notes, and nothing scrolling sideways on a phone. Makes its own
// plant through the API. With SMOKE_SHOTS_DIR set, screenshots are saved there.
import { test, expect, open, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};

const WORKING = [
  "## Chlorine demand",
  "",
  "| Source | Demand |",
  "|---|---|",
  "| Sunlight (UV 11-13) | 3.1 ppm/day |",
  "| 20 swimmers at 0.1 ppm | 2.0 ppm/day |",
  "",
  "```",
  "150 g / 35,000 L = 4.3 ppm/day",
  "```",
  "",
  "<script>window.__pwned = 1</script>",
  "<img src=x onerror=\"window.__pwned = 2\">",
  "",
  "[click](javascript:window.__pwned=3) and [ok](https://reliafy.com)",
].join("\n");

async function plant(request, tag) {
  const top = await postOk(request, `${M}/positions`, { name: `Basis pool ${tag}`, operating_context: "About 35 kL, UV 11-13." });
  const sub = await postOk(request, `${M}/positions`, { name: `Basis circulation ${tag}`, parent_id: top.id });
  const fn = await postOk(request, `${M}/positions/${sub.id}/functions`, { text: `Keep the water safe ${tag}`, standard: "1-3 ppm free chlorine" });
  const ff = await postOk(request, `${M}/functions/${fn.id}/failures`, { text: `Too little chlorine ${tag}` });
  await postOk(request, `${M}/positions/${sub.id}/failure-modes`, { text: `Dosing pump fails ${tag}`, functional_failure_id: ff.id });
  return { top, sub, fn };
}

const table = (page) => page.getByRole("treegrid", { name: /and their RCM/ });
const trow = (page, name) => table(page).getByRole("row", { name: new RegExp(name) });
const panel = (page) => page.locator("aside.rw-panel");
const section = (page) => panel(page).getByRole("region", { name: "Notes and rationale" });
const overflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - innerWidth);

test("the working goes in a function's notes: the hint, Markdown shown, inert HTML, a PDF, one section", async ({ page, request, problems }) => {
  const tag = `b${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.sub.id}&tab=rcm`);
  await expect(table(page)).toBeVisible();
  const fnRow = trow(page, `^Function: Keep the water safe ${tag}`);
  await fnRow.locator(".tt-tree").click();
  await expect(panel(page)).toBeVisible();

  // One long-text section on a function: no separate working section, and the hint says the working goes here.
  await expect(panel(page).getByRole("region", { name: "Working behind the performance standard" })).toHaveCount(0);
  // Empty: only a quiet "+ Add notes" by the heading, the hint its tooltip; the hint shows in the box.
  await expect(section(page).getByRole("button", { name: "Add notes" })).toHaveAttribute("title", /Why these limits: the working, the data and the sources behind the performance standard/);
  await expect(section(page)).not.toContainText("Why these limits");
  await shot(page, "01-empty");

  // Write it: tables and code render; raw HTML and scripts are inert.
  await section(page).getByRole("button", { name: "Add notes" }).click();
  await expect(section(page)).toContainText("Why these limits: the working, the data and the sources behind the performance standard");
  await section(page).getByRole("textbox").fill(WORKING);
  await shot(page, "02-write");
  await section(page).getByRole("button", { name: "Save" }).click();
  await section(page).getByRole("button", { name: /Show all/ }).click();
  await expect(section(page).locator(".rw-md table")).toBeVisible();
  await expect(section(page).locator(".rw-md pre")).toContainText("150 g / 35,000 L");
  for (const bad of ["script", "img", "style", "iframe"]) await expect(section(page).locator(`.rw-md ${bad}`)).toHaveCount(0);
  await expect(section(page).locator(".rw-md a[href^='javascript']")).toHaveCount(0);
  await expect(section(page).locator(".rw-md a[href='https://reliafy.com']")).toHaveAttribute("rel", /noopener/);
  expect(await page.evaluate(() => window.__pwned)).toBeUndefined();
  await shot(page, "03-saved");

  // A PDF at the end of the section.
  await section(page).getByRole("button", { name: "Attach a PDF…" }).click();
  await page.getByTestId("basis-pdf").setInputFiles("smoke/fixtures/working.pdf");
  await section(page).getByRole("button", { name: "Upload", exact: true }).click();
  await expect(section(page).locator(".rw-pdf")).toContainText("working");
  await shot(page, "04-pdf-chip");
  await section(page).locator(".rw-pdf .ovm-trigger").click();
  await section(page).getByRole("button", { name: "Remove…" }).click();
  await section(page).getByRole("button", { name: "Remove", exact: true }).click();
  await expect(section(page).locator(".rw-pdf")).toHaveCount(0);

  // From the performance standard: a line that opens the function's notes.
  await trow(page, "^Performance standard: 1-3 ppm free chlorine").locator(".tt-tree").click();
  await panel(page).getByRole("button", { name: "open them" }).click();
  await expect(panel(page).getByRole("heading", { name: `Keep the water safe ${tag}` })).toBeVisible();
  await expect(section(page).locator(".rw-md h2")).toHaveText("Chlorine demand");
  expect(problems).toEqual([]);
});

test("a working written before reads in the notes, on a phone too, and nothing scrolls sideways", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const p = await plant(request, tag);
  // standard_basis is the old, deprecated name: it is written into the notes.
  await postOk(request, `${M}/positions/${p.sub.id}/functions`, { text: `Second ${tag}`, notes: "Why these limits", standard_basis: `${WORKING}\n\n${"| a | b | c | d | e | f | g |\n|---|---|---|---|---|---|---|\n| 1111111111 | 2222222222 | 3333333333 | 4444444444 | 5555555555 | 6666666666 | 7777777777 |\n"}` });
  await page.setViewportSize({ width: 400, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.sub.id}&tab=rcm`);
  const row = page.getByRole("row", { name: new RegExp(`^Function: Second ${tag}`) });
  await row.locator(".tt-l1").click();
  await expect(panel(page)).toBeVisible();
  await section(page).getByRole("button", { name: /Show all/ }).click();
  await expect(section(page)).toContainText("Working");
  await expect(section(page).locator(".rw-md table").first()).toBeVisible();
  expect(await overflow(page)).toBeLessThanOrEqual(0);
  await shot(page, "05-phone-expanded");
  await section(page).getByRole("button", { name: /Edit/ }).click();
  expect(await overflow(page)).toBeLessThanOrEqual(0);
  await shot(page, "06-phone-edit");
  expect(problems).toEqual([]);
});
