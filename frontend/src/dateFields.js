// What the shared date and time fields (components/ui/DateTimeInput.jsx) read and show. A
// browser's own date and time inputs follow its language, so an English (US) browser shows
// "11/22/2026" and "04:00 PM"; these fields show "22 Nov 2026" and "16:00" whatever the browser
// is set to (dates.js), while the value they hand back stays ISO ("2026-11-22", "16:00"). Pure,
// so the tests can hold it.

import { MONTHS, formatDate } from "./dates.js";

const pad = (n) => String(n).padStart(2, "0");
const ISO_DAY = /^(\d{4})-(\d{2})-(\d{2})$/;

// "2026-11-22" as "22 Nov 2026"; anything else as "".
export const dayText = (iso) => (ISO_DAY.test(iso || "") ? formatDate(iso) : "");

function isoOf(y, m, d) {
  if (!(m >= 1 && m <= 12 && d >= 1 && d <= 31 && y >= 1000 && y <= 9999)) return null;
  const t = new Date(Date.UTC(y, m - 1, d));
  if (t.getUTCDate() !== d) return null; // 31 Feb
  return `${y}-${pad(m)}-${pad(d)}`;
}

const monthOf = (word) => {
  const w = word.toLowerCase().slice(0, 3);
  const i = MONTHS.findIndex((m) => m.toLowerCase() === w);
  return i < 0 ? null : i + 1;
};

// A typed day as ISO, or null. Day first: "22/11/2026", "22-11-2026", "22.11.2026", "22 11 2026",
// "22 Nov 2026", "22 November 2026", or ISO "2026-11-22". `loose` (on leaving the field) also
// takes a two-digit year ("22/11/26": 2026) and a day with no year ("22 Nov": in `year`).
export function parseDayText(text, { loose = false, year = null } = {}) {
  const s = String(text || "").trim().replace(/,/g, " ").replace(/\s+/g, " ");
  if (!s) return null;
  let m = ISO_DAY.exec(s);
  if (m) return isoOf(Number(m[1]), Number(m[2]), Number(m[3]));
  const yearOf = (y) => {
    if (y == null) return loose && year ? Number(year) : null;
    if (y.length === 4) return Number(y);
    if (y.length === 2 && loose) return 2000 + Number(y);
    return null;
  };
  m = /^(\d{1,2})[/.\- ](\d{1,2})(?:[/.\- ](\d{2}|\d{4}))?$/.exec(s);
  if (m) {
    const y = yearOf(m[3]);
    return y == null ? null : isoOf(y, Number(m[2]), Number(m[1]));
  }
  m = /^(\d{1,2})[ \-/]?([A-Za-z]{3,9})\.?(?:[ \-/](\d{2}|\d{4}))?$/.exec(s);
  if (m) {
    const mo = monthOf(m[2]);
    const full = m[2].length === 3 || LONG.some((l) => l.startsWith(m[2].toLowerCase()));
    const y = yearOf(m[3]);
    return mo && full && y != null ? isoOf(y, mo, Number(m[1])) : null;
  }
  return null;
}
const LONG = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
  "november", "december"];

// A typed clock time as "HH:MM" (24-hour), or null: "8" or "08" (08:00), "830" or "0830" (08:30),
// "8:30", "8.30", "20:00", "8pm", "8:30 pm", "12am" (00:00).
export function parseClockText(text) {
  const s = String(text || "").trim().toLowerCase().replace(/\s+/g, "");
  if (!s) return null;
  const m = /^(\d{1,2})(?:[:.h]?(\d{2}))?(am|pm|a|p)?$/.exec(s);
  if (!m) return null;
  let h = Number(m[1]);
  const mi = m[2] == null ? 0 : Number(m[2]);
  if (mi > 59) return null;
  if (m[3]) {
    if (h < 1 || h > 12) return null;
    const pm = m[3].startsWith("p");
    h = (h % 12) + (pm ? 12 : 0);
  }
  if (h > 23) return null;
  return `${pad(h)}:${pad(mi)}`;
}

// A time value ("16:00", or "16:00:00" from a browser) as the field shows it: "16:00".
export const clockText = (v) => (/^\d{2}:\d{2}/.test(v || "") ? v.slice(0, 5) : "");

// Is a day outside [min, max] (ISO days; either may be missing)?
export const outOfRange = (iso, min, max) => !!iso && ((min && iso < min) || (max && iso > max));
