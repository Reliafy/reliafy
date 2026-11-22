// The shared Select (components/Select.jsx) is a button that opens a list, so
// Playwright's selectOption() can't drive it. choose(trigger, want) opens it
// and clicks the row, the way selectOption() picks one:
//   a string     the row with that value, or else that label
//   { label }    the row with that label (a RegExp: the first row whose label matches)
//   { index }    the nth row (headings aren't rows)
// The trigger carries the chosen value as data-value: expect(trigger).toHaveAttribute("data-value", v).
import { expect } from "@playwright/test";

async function openList(trigger) {
  await trigger.click();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  const id = await trigger.getAttribute("aria-controls");
  return trigger.page().locator(`[id="${id}"]`);
}

export async function choose(trigger, want) {
  // A native <select> still works, so a spec reads the same before and after its screen moves over.
  if (await trigger.evaluate((el) => el.tagName === "SELECT")) {
    if (want?.label instanceof RegExp) {
      want = await trigger.locator("option", { hasText: want.label }).first().getAttribute("value");
    }
    await trigger.selectOption(want);
    return;
  }
  const list = await openList(trigger);
  let row;
  if (typeof want === "string") {
    const v = want.replace(/["\\]/g, "\\$&");
    row = list.locator(`[role="option"][data-value="${v}"]`)
      .or(list.locator('[role="option"]').filter({ has: trigger.page().locator(".sel-option-label").getByText(want, { exact: true }) }))
      .first();
  } else if (want.label instanceof RegExp) {
    row = list.locator('[role="option"]').filter({ has: trigger.page().locator(".sel-option-label", { hasText: want.label }) }).first();
  } else if (want.label != null) {
    row = list.locator('[role="option"]').filter({ has: trigger.page().locator(".sel-option-label").getByText(want.label, { exact: true }) }).first();
  } else {
    row = list.locator('[role="option"]').nth(want.index);
  }
  await row.click();
}

// The labels of a Select's rows, in order (opens and shuts it).
export async function optionLabels(trigger) {
  if (await trigger.evaluate((el) => el.tagName === "SELECT")) return trigger.locator("option").allTextContents();
  const list = await openList(trigger);
  const labels = await list.locator('[role="option"] .sel-option-label').allTextContents();
  await trigger.press("Escape");
  return labels;
}

// The chosen value, native or shared: toHaveValue on a <select>, data-value on the trigger.
export async function expectChosen(trigger, value) {
  if (await trigger.evaluate((el) => el.tagName === "SELECT" || el.tagName === "INPUT")) await expect(trigger).toHaveValue(value);
  else await expect(trigger).toHaveAttribute("data-value", value);
}
