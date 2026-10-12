// The admin page's publishing calendar (Content tab): month arithmetic, the
// Mon–Sun grid, and how each item is labelled. Pure, so `node --test` covers
// it; the items come from GET /api/admin/content-calendar
// (backend/services/content_calendar.py).

const pad = (n) => String(n).padStart(2, "0");

// "YYYY-MM" for a Date, in local time.
export function monthOf(d = new Date()) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
}

// "YYYY-MM" moved by `delta` months.
export function shiftMonth(month, delta) {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}`;
}

function iso(d) {
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

// The month's weeks, Monday first: [[{ date, day, inMonth, weekday }] x 7].
// Leading and trailing days of the neighbouring months fill the first and
// last weeks.
export function monthGrid(month) {
  const [y, m] = month.split("-").map(Number);
  const first = new Date(Date.UTC(y, m - 1, 1));
  const start = new Date(first);
  start.setUTCDate(1 - ((first.getUTCDay() + 6) % 7));
  const weeks = [];
  const d = new Date(start);
  do {
    const week = [];
    for (let i = 0; i < 7; i += 1) {
      week.push({ date: iso(d), day: d.getUTCDate(), inMonth: d.getUTCMonth() === m - 1, weekday: i });
      d.setUTCDate(d.getUTCDate() + 1);
    }
    weeks.push(week);
  } while (d.getUTCMonth() === m - 1);
  return weeks;
}

// Items grouped by date: { "YYYY-MM-DD": [item, ...] }.
export function byDate(items = []) {
  const out = {};
  for (const it of items) (out[it.date] ||= []).push(it);
  return out;
}

const BLOG_TYPES = { technical: "Technical", commentary: "Commentary", tutorial: "Tutorial" };

// An item's kind as the chip shows it: a key for its colour and a label.
export function kindOf(item) {
  if (item.kind === "blog") {
    return item.type && BLOG_TYPES[item.type]
      ? { key: `blog-${item.type}`, label: BLOG_TYPES[item.type], long: `Blog · ${BLOG_TYPES[item.type].toLowerCase()}` }
      : { key: "blog", label: "Blog", long: "Blog" };
  }
  if (item.kind === "whatsnew") return { key: "whatsnew", label: "What's new", long: "What's new" };
  if (item.kind === "announcement") return { key: "announcement", label: "Announcement", long: "LinkedIn announcement" };
  return { key: "linkedin", label: "LinkedIn", long: "LinkedIn short post" };
}

// The legend, in the order the chips sort within a day.
export const LEGEND = [
  { key: "blog-technical", label: "Technical" },
  { key: "blog-commentary", label: "Commentary" },
  { key: "blog-tutorial", label: "Tutorial" },
  { key: "whatsnew", label: "What's new" },
  { key: "announcement", label: "LinkedIn announcement" },
  { key: "linkedin", label: "LinkedIn short post" },
];

export const STATUS = {
  published: { label: "Published", tone: "success" },
  scheduled: { label: "Scheduled", tone: "accent" },
  planned: { label: "Planned", tone: "neutral" },
  missed: { label: "Missed", tone: "warning" },
};

// The text a chip shows: short, so a day cell holds three.
export function chipText(item, max = 26) {
  const t = String(item.title || "").trim() || kindOf(item).label;
  return t.length > max ? `${t.slice(0, max - 1).trimEnd()}…` : t;
}

// "Mon 12 Oct" (or with the year when `year`).
export function dayLabel(date, { year = false } = {}) {
  const [y, m, d] = date.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.toLocaleDateString("en-AU", {
    weekday: "short",
    day: "numeric",
    month: "short",
    ...(year ? { year: "numeric" } : {}),
    timeZone: "UTC",
  });
}

export function monthLabel(month) {
  const [y, m] = month.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString("en-AU", { month: "long", year: "numeric", timeZone: "UTC" });
}

// The phone list: the month's days that have an item or a gap, in order.
export function listDays(view) {
  const items = byDate(view?.items);
  const gaps = new Set(view?.gaps || []);
  const dates = [...new Set([...Object.keys(items), ...gaps])].sort();
  return dates.map((date) => ({ date, items: items[date] || [], gap: gaps.has(date) }));
}

// The first lines of a post's text, for the detail panel.
export function firstLines(text, lines = 4, max = 240) {
  const kept = String(text || "")
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .slice(0, lines)
    .join("\n");
  return kept.length > max ? `${kept.slice(0, max - 1).trimEnd()}…` : kept;
}
