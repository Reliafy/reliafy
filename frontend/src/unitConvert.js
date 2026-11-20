// A saved model fitted in another unit of the same kind as the diagram's
// (days in an hours diagram) is converted before the analysis. The backend's
// twin is unit_factor / conversion_note in backend/units.py and
// backend/services/model_units.py: the same aliases and the app's one calendar
// convention (24 hours a day, 7 days a week, 365.25 / 12 days a month,
// 365.25 days a year).
const ALIASES = {
  h: "hour", hr: "hour", hrs: "hour", hours: "hour",
  s: "second", sec: "second", secs: "second", seconds: "second",
  min: "minute", mins: "minute", minutes: "minute",
  d: "day", days: "day",
  wk: "week", wks: "week", weeks: "week",
  mo: "month", mon: "month", mth: "month", mths: "month", months: "month",
  y: "year", yr: "year", yrs: "year", years: "year",
  kms: "km", kilometre: "km", kilometres: "km", kilometer: "km", kilometers: "km",
  miles: "mile", mi: "mile",
};
const BLANK = new Set(["-", "unit", "units", "unspecified", "none", "n/a"]);
const DAYS_PER = { second: 1 / 86400, minute: 1 / 1440, hour: 1 / 24, day: 1, week: 7, month: 365.25 / 12, year: 365.25 };
const KM_PER = { km: 1, mile: 1.609344 };
const PLURAL = { second: "seconds", minute: "minutes", hour: "hours", day: "days", week: "weeks",
  month: "months", year: "years", km: "kilometres", mile: "miles" };
// Model kinds the analysis converts (model_units.convertible_kind).
const KINDS = new Set([undefined, null, "", "distribution", "regression", "repairable"]);

export function normalizeUnit(unit) {
  const key = String(unit ?? "").trim().toLowerCase().replace(/\.$/, "");
  if (!key || BLANK.has(key)) return null;
  return ALIASES[key] || key;
}

// How many of `to` make one `from` (days → hours: 24), or null when the units
// are the same, of different kinds (cycles and hours), blank or unknown.
export function unitFactor(from, to) {
  const a = normalizeUnit(from), b = normalizeUnit(to);
  if (!a || !b || a === b) return null;
  for (const table of [DAYS_PER, KM_PER]) {
    if (a in table && b in table) return table[a] / table[b];
  }
  return null;
}

// {from, to, factor, text} for a block's model the analysis converts to the
// diagram's unit, or null. `text` is what the block says: "Fitted in days,
// shown in hours".
export function blockConversion(model, diagramUnit) {
  if (!model || typeof model !== "object" || !KINDS.has(model.kind)) return null;
  const factor = unitFactor(model.unit, diagramUnit);
  if (factor == null) return null;
  const from = PLURAL[normalizeUnit(model.unit)];
  const to = PLURAL[normalizeUnit(diagramUnit)];
  return { from, to, factor, text: `Fitted in ${from}, shown in ${to}` };
}
