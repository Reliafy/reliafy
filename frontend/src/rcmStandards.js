// A function's performance standards as a list (the Explorer's function
// dialog and Details): what the list shows, when the split helper is offered,
// and the lines it proposes. Pure functions, tested in rcmStandards.test.js.
// The server (backend/maintenance/service.py) keeps the rules: a function's
// old single text stays and shows until a list stands in for it; the app
// never splits it on its own.

export const COMPARATORS = ["<", "<=", "=", ">=", ">", "between", "not"];
export const COMPARATOR_LABEL = { "<": "below", "<=": "at most", "=": "exactly", ">=": "at least", ">": "above", between: "between", not: "not" };

// The standards a function shows: its list, or its one text as the first (and
// only) item, with `legacy: true` (edited as the function's text, not a standard).
export function standardsShown(fn) {
  const listed = fn?.standards || [];
  if (listed.length) return listed.map((st) => ({ ...st, legacy: false }));
  const text = String(fn?.standard || "").trim();
  return text ? [{ id: null, text, order: 1, legacy: true, failures: 0 }] : [];
}

// Whether the split helper is offered: the function has its one text, no
// list, and the text reads as several (';' or line breaks in it).
export const canSplit = (fn) => !(fn?.standards || []).length && /[;\n\r]/.test(String(fn?.standard || ""));

// The lines a single text splits into, as the server proposes them.
export function proposeSplit(text) {
  return String(text || "").split(/\s*(?:;|\r?\n)+\s*/).map((x) => x.trim()).filter(Boolean);
}

// The structured limit in words, for a line under the text: "TA between 80-120 ppm · in summer · E25 manual".
export function limitWords(st) {
  const limit = [st.parameter, st.comparator ? COMPARATOR_LABEL[st.comparator] || st.comparator : null,
    st.value != null && st.value !== "" ? String(st.value) : null, st.unit].filter(Boolean).join(" ");
  // A condition keeps its own conjunction ("while the filter pump runs"); one without gets "when".
  const when = st.when ? (/^(while|when|whenever|given|if|unless|during|after|before|at|in|on|once)\b/i.test(st.when) ? st.when : `when ${st.when}`) : null;
  return [limit || null, when, st.source || null].filter(Boolean).join(" · ");
}

// "2 standards have no functional failure yet": the quiet hint under a
// function with a list; nothing for one standard or none.
export function unbreachedWords(fn) {
  const n = fn?.standards_without_failure || 0;
  if (!(fn?.standards || []).length || !n) return "";
  return `${n} performance standard${n === 1 ? " has" : "s have"} no functional failure yet.`;
}

// The split helper's lines, as edited: each kept line a standard, or the
// condition (when) of the standard before it. Returns the standards to write,
// or null when none is left.
export function splitLines(lines) {
  const out = [];
  for (const line of lines) {
    const text = String(line.text || "").trim();
    if (line.drop || !text) continue;
    if (line.kind === "when") {
      if (out.length) out[out.length - 1].when = [out[out.length - 1].when, text].filter(Boolean).join("; ");
      continue;
    }
    out.push({ text });
  }
  return out.length ? out : null;
}
