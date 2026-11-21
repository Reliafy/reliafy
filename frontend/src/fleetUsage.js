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

// Days in one calendar period, singular or plural, any case (mirrors
// backend/services/fleet.py PERIOD_DAYS). Other labels ("cycles") have no
// calendar length, so nothing can be converted to or from them.
const PERIOD_DAYS = { day: 1, week: 7, month: 30.4375, quarter: 91.3125, year: 365.25 };

export function periodDays(label) {
  const key = String(label || "").trim().toLowerCase();
  if (PERIOD_DAYS[key]) return PERIOD_DAYS[key];
  if (key.endsWith("s") && PERIOD_DAYS[key.slice(0, -1)]) return PERIOD_DAYS[key.slice(0, -1)];
  return null;
}

const scaled = (v, k, sig = 6) => {
  if (blank(v) || Number.isNaN(Number(v))) return v;
  return Number((Number(v) * k).toPrecision(sig));
};

// A change of period (say months → quarters) changes what every "per period"
// number means. Usage per period is per period, so it scales up with the
// period's length; the horizon, lead time, review interval and warranty are
// counts of periods, so they scale down. The forecast then covers the same
// calendar span at the same usage. Returns null when either period has no
// calendar length (nothing to convert).
export function convertPeriod(settings, items, fromLabel, toLabel) {
  const from = periodDays(fromLabel);
  const to = periodDays(toLabel);
  if (!from || !to || from === to) return null;
  const up = to / from;
  const down = from / to;
  const next = { ...settings, period_label: toLabel, default_rate: scaled(settings.default_rate, up) };
  if (!blank(settings.periods)) {
    next.periods = Math.min(120, Math.max(1, Math.round(Number(settings.periods) * down)));
  }
  if (!blank(settings.warranty_periods)) next.warranty_periods = scaled(settings.warranty_periods, down, 4);
  if (settings.spares) {
    next.spares = { ...settings.spares };
    for (const key of ["lead_time", "review"]) {
      if (!blank(settings.spares[key])) next.spares[key] = scaled(settings.spares[key], down, 4);
    }
  }
  const nextItems = (items || []).map((it) => (blank(it.rate) ? it : { ...it, rate: scaled(it.rate, up) }));
  return { settings: next, items: nextItems };
}
