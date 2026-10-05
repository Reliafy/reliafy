// A time unit in running text (#265). Units are stored and shown in the
// pickers' spelling ("Hours", "Months"), but a sentence reads "over 8,760
// hours" and "per hour", never "over 8,760 Hours". A picker unit comes back
// lower-case; anything else (a typed "kWh", "Flights") as given. Labels,
// headers and axis titles keep the stored spelling. The backend's twin is
// unit_in_text in backend/units.py.
const PICKER_UNITS = new Set([
  "seconds", "minutes", "hours", "days", "weeks", "months", "years",
  "cycles", "kilometres", "miles", "operations", "rounds",
]);

export function unitInText(unit) {
  const text = String(unit ?? "").trim();
  return PICKER_UNITS.has(text.toLowerCase()) ? text.toLowerCase() : text;
}
