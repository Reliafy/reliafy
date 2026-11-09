// Dates as people read them: day first, a 24-hour clock, and the same text
// whatever language the browser is set to ("1 Nov 2026", never "Nov 1, 2026";
// "14:05", never "2:05 PM"). Every date on a page is written here:
// dates.test.js fails on a locale call anywhere else. Dates for machines
// (exports, file names, `datetime` attributes, feeds) stay ISO and don't come
// through here.
//
// A day on its own ("2026-11-01") is shown as written, so it never moves with
// the viewer's time zone. Anything else (a timestamp, a Date) is an instant,
// shown in the viewer's zone, or in UTC with `utc`. A value that isn't a date
// gives "": the caller chooses what stands in for it.

export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const LONG_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
  "October", "November", "December"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const DAY_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;
const pad = (n) => String(n).padStart(2, "0");

function parts(value, utc) {
  if (value == null || value === "") return null;
  const day = typeof value === "string" ? DAY_ONLY.exec(value.trim()) : null;
  const d = day ? new Date(Date.UTC(Number(day[1]), Number(day[2]) - 1, Number(day[3])))
    : value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  // "2026-02-31" isn't a day (the Date would roll it into March).
  if (day && d.getUTCMonth() !== Number(day[2]) - 1) return null;
  return utc || day
    ? { year: d.getUTCFullYear(), month: d.getUTCMonth(), day: d.getUTCDate(), weekday: d.getUTCDay(),
        hour: d.getUTCHours(), minute: d.getUTCMinutes() }
    : { year: d.getFullYear(), month: d.getMonth(), day: d.getDate(), weekday: d.getDay(),
        hour: d.getHours(), minute: d.getMinutes() };
}

const dayWords = (p, { weekday = false, year = true, long = false } = {}) =>
  [weekday ? WEEKDAYS[p.weekday] : null, p.day, (long ? LONG_MONTHS : MONTHS)[p.month], year ? p.year : null]
    .filter((x) => x != null).join(" ");

// "1 Nov 2026". `weekday`: "Sun 1 Nov 2026"; `year: false`: "1 Nov";
// `long` (prose: an article's date): "1 November 2026".
export function formatDate(value, { utc = false, ...how } = {}) {
  const p = parts(value, utc);
  return p ? dayWords(p, how) : "";
}

// "1 Nov 2026, 14:05" (`year: false`: "1 Nov, 14:05").
export function formatDateTime(value, { utc = false, ...how } = {}) {
  const p = parts(value, utc);
  return p ? `${dayWords(p, how)}, ${pad(p.hour)}:${pad(p.minute)}` : "";
}

// "Nov 2026": a month, or a date known only to the month.
export function formatMonth(value, { utc = false } = {}) {
  const p = parts(value, utc);
  return p ? `${MONTHS[p.month]} ${p.year}` : "";
}
