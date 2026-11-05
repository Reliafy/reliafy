// The working behind a function's performance standard (Explorer › RCM tab):
// the section in the function's details (empty, write, preview, save, read
// more), the (i) in the table, a hostile text staying inert, a .md file and a
// PDF added, and nothing scrolling sideways on a phone. Makes its own plant
// through the API. With SMOKE_SHOTS_DIR set, screenshots are saved there.
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
const section = (page) => panel(page).getByRole("region", { name: "Working behind the performance standard" });
const overflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - innerWidth);

test("the working behind a standard: write, preview, save, read, the (i), a .md file and a PDF", async ({ page, request, problems }) => {
  const tag = `b${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.sub.id}&tab=rcm`);
  await expect(table(page)).toBeVisible();
  await trow(page, `^Function: Keep the water safe ${tag}`).locator(".tt-tree").click();
  await expect(panel(page)).toBeVisible();

  // Empty: a quiet prompt and two links; no (i) on the function or its performance standard.
  await expect(section(page).getByText(/Optional\. Say how the performance standard was worked out/)).toBeVisible();
  const fnRow = trow(page, `^Function: Keep the water safe ${tag}`);
  const stdRow = trow(page, "^Performance standard: 1-3 ppm free chlorine");
  await expect(stdRow).toBeVisible();
  await expect(table(page).locator(".rw-info")).toHaveCount(0);
  await shot(page, "01-empty");

  // Write, then Preview: tables and code render; raw HTML and scripts are inert.
  await section(page).getByRole("button", { name: "Add a working…" }).click();
  const box = section(page).getByRole("textbox", { name: /Markdown/ });
  await box.fill(WORKING);
  await shot(page, "02-write");
  await section(page).getByRole("radio", { name: "Preview" }).click();
  await expect(section(page).locator(".rw-md table")).toBeVisible();
  await expect(section(page).locator(".rw-md pre")).toContainText("150 g / 35,000 L");
  for (const bad of ["script", "img", "style", "iframe"]) await expect(section(page).locator(`.rw-md ${bad}`)).toHaveCount(0);
  await expect(section(page).locator(".rw-md a[href^='javascript']")).toHaveCount(0);
  await expect(section(page).locator(".rw-md a[href='https://reliafy.com']")).toHaveAttribute("rel", /noopener/);
  await shot(page, "03-preview");

  // Save: collapsed to a preview line with Read more, the (i) on the performance standard's row (not the function's).
  await section(page).getByRole("radio", { name: "Write" }).click();
  await section(page).getByRole("button", { name: "Save" }).click();
  await expect(section(page).getByRole("button", { name: /Read more/ })).toBeVisible();
  await expect(section(page).locator(".rw-basis-preview")).toContainText("Chlorine demand");
  const info = stdRow.locator(".tt-tree .rw-info");
  await expect(info).toHaveCount(1);
  await expect(fnRow.locator(".rw-info")).toHaveCount(0);
  await expect(info).toHaveAttribute("title", /How this performance standard was worked out: Chlorine demand/);
  await shot(page, "04-collapsed-with-info");

  await section(page).getByRole("button", { name: /Read more/ }).click();
  await expect(section(page).locator(".rw-md h2")).toHaveText("Chlorine demand");
  expect(await page.evaluate(() => window.__pwned)).toBeUndefined();
  await shot(page, "05-expanded");
  await expect(section(page).getByRole("link", { name: /operating context of Basis pool/ })).toBeVisible();

  // No Performance standard column to move it into: the Columns menu doesn't offer one.
  await page.getByRole("button", { name: "Columns" }).click();
  await expect(page.getByRole("checkbox", { name: /Performance standard/ })).toHaveCount(0);
  await page.keyboard.press("Escape");

  // The (i) opens the function's working in full, from another row.
  await trow(page, `^Failure mode: Dosing pump fails ${tag}`).locator(".tt-tree").click();
  await expect(section(page)).toHaveCount(0);
  await info.click();
  await expect(panel(page).getByRole("heading", { name: `Keep the water safe ${tag}` })).toBeVisible();
  await expect(section(page).locator(".rw-md h2")).toBeVisible();

  // A .md file: replace the text. Then a PDF.
  await section(page).getByRole("button", { name: /Edit/ }).click();
  await section(page).getByRole("button", { name: "Upload .md" }).waitFor();
  await page.getByTestId("basis-md").setInputFiles({ name: "chlorine.md", mimeType: "text/markdown", buffer: Buffer.from("# From a file\r\n\r\nline  \r\n") });
  await expect(section(page).getByText(/There is text here already/)).toBeVisible();
  await shot(page, "06-upload-md-question");
  await section(page).getByRole("button", { name: "Replace it" }).click();
  await expect(section(page).getByRole("textbox", { name: /Markdown/ })).toHaveValue("# From a file\n\nline"); // line endings and trailing spaces tidied
  await page.getByTestId("basis-md").setInputFiles({ name: "bad.md", mimeType: "text/markdown", buffer: Buffer.from([0x66, 0x00, 0x6f]) });
  await expect(section(page).getByRole("alert")).toContainText("isn't a text file");
  await section(page).getByRole("button", { name: "Save" }).click();
  await expect(section(page).locator(".rw-md h1")).toHaveText("From a file"); // still open, as the (i) opened it

  await section(page).getByRole("button", { name: "Attach a PDF…" }).click();
  await page.getByTestId("basis-pdf").setInputFiles("smoke/fixtures/working.pdf");
  await section(page).getByRole("button", { name: "Upload", exact: true }).click();
  await expect(section(page).locator(".rw-pdf")).toContainText("working");
  await shot(page, "07-pdf-chip");
  await section(page).locator(".rw-pdf .ovm-trigger").click();
  await section(page).getByRole("button", { name: "Remove…" }).click();
  await section(page).getByRole("button", { name: "Remove", exact: true }).click();
  await expect(section(page).locator(".rw-pdf")).toHaveCount(0);

  // The link to the operating context opens the Summary tab on the position that has it.
  await section(page).getByRole("link", { name: /operating context of Basis pool/ }).click();
  await expect(page.getByRole("tab", { name: "Summary", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#operating-context")).toBeVisible();
  await expect(page.locator("#operating-context")).toContainText("About 35 kL");
  expect(problems).toEqual([]);
});

test("the working on a phone: a sheet that doesn't scroll the page sideways", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const p = await plant(request, tag);
  await postOk(request, `${M}/positions/${p.sub.id}/functions`, { text: `Second ${tag}`, standard_basis: `${WORKING}\n\n${"| a | b | c | d | e | f | g |\n|---|---|---|---|---|---|---|\n| 1111111111 | 2222222222 | 3333333333 | 4444444444 | 5555555555 | 6666666666 | 7777777777 |\n"}` });
  await page.setViewportSize({ width: 400, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.sub.id}&tab=rcm`);
  const row = page.getByRole("row", { name: new RegExp(`^Function: Second ${tag}`) });
  await expect(row).toContainText("has a working");
  await row.locator(".tt-l1").click();
  await expect(panel(page)).toBeVisible();
  await section(page).getByRole("button", { name: /Read more/ }).click();
  await expect(section(page).locator(".rw-md table").first()).toBeVisible();
  expect(await overflow(page)).toBeLessThanOrEqual(0);
  await shot(page, "08-phone-expanded");
  await section(page).getByRole("button", { name: /Edit/ }).click();
  expect(await overflow(page)).toBeLessThanOrEqual(0);
  await shot(page, "09-phone-edit");
  expect(problems).toEqual([]);
});
