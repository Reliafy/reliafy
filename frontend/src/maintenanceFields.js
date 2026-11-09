// Reliafy Maintenance: showing the structured fields (dates known only roughly,
// costs, warranties, document links) honestly, and reading them from forms.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export const PRECISIONS = [
  { id: "exact", label: "Exact day" },
  { id: "month", label: "Month only" },
  { id: "year", label: "Year only" },
  { id: "estimated", label: "Estimate" },
];

export const DOCUMENT_KINDS = ["manual", "datasheet", "invoice", "drawing", "certificate", "other"];

// "2022", "Mar 2022", "~Mar 2022", or the day (by `exact`, default "5 Mar 2022").
// Never a made-up day for a date known only to the month or year.
export function datedText(day, precision, exact) {
  if (!day) return "—";
  const month = MONTHS[Number(day.slice(5, 7)) - 1];
  if (precision === "year") return day.slice(0, 4);
  if (precision === "month") return `${month} ${day.slice(0, 4)}`;
  if (precision === "estimated") return `~${month} ${day.slice(0, 4)}`;
  return exact ? exact(day) : `${Number(day.slice(8, 10))} ${month} ${day.slice(0, 4)}`;
}

// The value a rough-date input sends: "2022" for a year, "2022-03" for a month,
// the day otherwise. `text` is what the input holds (a year, a yyyy-mm, or a day).
export function roughDateValue(text, precision) {
  const t = String(text || "").trim();
  if (!t) return "";
  if (precision === "year") return t.slice(0, 4);
  if (precision === "month") return t.slice(0, 7);
  return t;
}

// What a rough-date input shows for a stored date at a precision.
export function roughDateInput(day, precision) {
  if (!day) return "";
  if (precision === "year") return day.slice(0, 4);
  if (precision === "month") return day.slice(0, 7);
  return day;
}

// A fitment's life in days: one number, or the range a rough date allows.
export function daysText(row) {
  if (row.xl != null && row.xr != null && row.xl !== row.xr) return `${row.xl}–${row.xr}`;
  return String(row.x);
}

// Only http(s) links become hrefs: anything else (javascript:, data:) is shown as text.
export function safeHref(url) {
  const text = String(url || "").trim();
  if (!/^https?:\/\//i.test(text)) return null;
  try {
    const u = new URL(text);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}

export function moneyText(cost) {
  if (!cost) return "—";
  const amount = Number(cost.amount).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  return cost.currency ? `${cost.currency} ${amount}` : amount;
}

// "AUD 1,150 (supplier quote, as of 1 Sep 2026)".
export function costText(cost, exact) {
  if (!cost) return "—";
  const notes = [cost.source, cost.as_of && `as of ${datedText(cost.as_of, "exact", exact)}`].filter(Boolean);
  return notes.length ? `${moneyText(cost)} (${notes.join(", ")})` : moneyText(cost);
}

// A number field's text as a cost to send, or null when the amount is blank.
export function costValue({ amount, currency, source, as_of: asOf }) {
  if (amount === "" || amount == null) return null;
  return { amount: Number(amount), currency: currency || "", source: source || "", as_of: asOf || null };
}

// PDFs kept in the workspace (not links): the most one can be, and what's wrong
// with a chosen file before it's sent (null when nothing is). The server checks
// again, by the bytes.
export const MAX_DOCUMENT_MB = 20;

export function documentFileProblem(file) {
  if (!file) return "Choose a PDF file.";
  const name = String(file.name || "");
  if (file.type !== "application/pdf" && !/\.pdf$/i.test(name)) {
    return "Only PDF files can be kept here. For anything else, add a link instead.";
  }
  if (!file.size) return "That file is empty. Choose the PDF again.";
  if (file.size > MAX_DOCUMENT_MB * 1024 * 1024) {
    return `That PDF is ${(file.size / 1048576).toFixed(1)} MB; the most is ${MAX_DOCUMENT_MB} MB. `
      + "Save it again with a smaller size, or add a link instead.";
  }
  return null;
}

// A size people read: "820 KB", "3.4 MB".
export function fileSizeText(bytes) {
  if (!(bytes >= 0)) return "";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}
