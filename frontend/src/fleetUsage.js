// Whether a fleet forecast has the usage it needs (FleetForecastPage).
//
// Items age by their usage per period: their own rate, else (rates from API
// readings) their estimated rate, else the fleet's usage per period. A new
// forecast's usage per period is 0, and with it an item that relies on it never
// ages, so the forecast quietly answers "≈ 0 failures". The page asks for the
// usage instead of saving that.

const positive = (v) => v !== null && v !== undefined && v !== "" && Number(v) > 0;
const blank = (v) => v === null || v === undefined || v === "";

// The fleet's usage per period as the form shows it: a stored 0 is "not set
// yet" (blank, so the box asks for it); a typed "0" stays, so "0.5" can be typed.
export function usageInputValue(defaultRate) {
  return blank(defaultRate) || defaultRate === 0 ? "" : defaultRate;
}

// The items that take the fleet's usage per period: no own rate and, when rates
// come from API readings, no estimate either. An own rate of 0 is the user's
// choice (an item kept in store), so it doesn't rely on the fleet's.
export function itemsOnFleetRate(settings, items) {
  const estimated = (settings?.rate_source || "manual") === "estimated";
  return (items || []).filter((it) => blank(it.rate) && !(estimated && Number(it.estimated_rate_n) >= 1));
}

// The number of items left without usage: they rely on the fleet's usage per
// period and it is blank or 0. Zero means the forecast can be computed.
export function itemsWithoutUsage(settings, items) {
  if (positive(settings?.default_rate)) return 0;
  return itemsOnFleetRate(settings, items).length;
}
