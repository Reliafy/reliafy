// Why a new-model form's main button is still unavailable: the first thing
// missing, in words, shown beside the button (never only a tooltip, which a
// phone can't show). null when nothing is missing.
import { UNIT_MISSING, unitSettled } from "./lifeData.js";

export function whyCantCreate({ name, missing = [], unit }) {
  if (!String(name || "").trim()) return "Name the model first.";
  if (missing.length) {
    const list = missing.length === 1 ? missing[0] : `${missing.slice(0, -1).join(", ")} and ${missing.at(-1)}`;
    return `Enter ${list} (${missing.length === 1 ? "a number" : "numbers"}).`;
  }
  if (!unitSettled(unit)) return UNIT_MISSING;
  return null;
}
