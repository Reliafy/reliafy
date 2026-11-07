// Maintainability prediction (Modelling › Maintainability prediction): the
// words, the form's rows, a pasted parts list, and the request the server
// computes from. Pure functions; the pages draw them. The maths is the
// server's (backend/services/maintainability.py).

export const MAINTAINABILITY_PATH = "/maintainability";
export const MAINTAINABILITY_GUIDE = "maintainability-prediction";
export const MAINTAINABILITY_SAMPLE = "sample-maintainability-quadcopter";

// The elements of a repair, in the order they happen: the key the server
// takes, the column heading, and the plain words.
export const ELEMENTS = [
  { key: "isolation", label: "Fault isolation", short: "Isolate", help: "Finding what failed." },
  { key: "access", label: "Access", short: "Access", help: "Getting to it: covers off, disassembly." },
  { key: "replace", label: "Remove and replace", short: "Replace", help: "Taking the failed part out and fitting the new one (or repairing it)." },
  { key: "restore", label: "Reassemble and restore", short: "Restore", help: "Putting everything back." },
  { key: "checkout", label: "Check out and align", short: "Check out", help: "Proving it works: tests, alignment, calibration." },
];

export const UNITS = [
  { value: "minutes", label: "minutes" },
  { value: "hours", label: "hours" },
];

export const RATE_UNITS = [
  { value: "per_million_hours", label: "per million hours" },
  { value: "per_hour", label: "per hour" },
];
export const rateUnitText = (unit) => (RATE_UNITS.find((u) => u.value === unit) || RATE_UNITS[0]).label;

// A blank row of the lines table (every cell a string, as typed).
export function emptyLine() {
  return { ref: "", name: "", assembly: "", quantity: "1", failure_rate: "", mttr: "", maximum: "",
           elements: { isolation: "", access: "", replace: "", restore: "", checkout: "" } };
}

// The form's settings, as it starts.
export function emptyForm() {
  return { unit: "minutes", failure_rate_unit: "per_million_hours", percentile: "95", mtbf: "", product: null,
           lines: [emptyLine()] };
}

const num = (s) => {
  const t = String(s ?? "").trim().replace(/,/g, "");
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : NaN;
};

// Whether any element of a row has a value typed.
export const hasElements = (line) => ELEMENTS.some((e) => String(line.elements?.[e.key] ?? "").trim() !== "");

// A row's repair time: the sum of its elements, else its MTTR cell; null
// when neither is typed, NaN when something isn't a number.
export function lineMttr(line) {
  if (hasElements(line)) {
    let sum = 0;
    for (const e of ELEMENTS) {
      const v = num(line.elements[e.key]);
      if (v === null) continue;
      if (Number.isNaN(v) || v < 0) return NaN;
      sum += v;
    }
    return sum;
  }
  const v = num(line.mttr);
  return v === null ? null : (Number.isNaN(v) || v < 0 ? NaN : v);
}

// Why the form can't be computed yet (null when it can): the first thing to fix.
export function formProblem(form) {
  const lines = (form.lines || []).filter((l) => !isBlank(l));
  if (!lines.length) return "Add a line: a part or item, and how long its repair takes.";
  for (const [i, line] of lines.entries()) {
    const label = line.name?.trim() || line.ref?.trim() || `line ${i + 1}`;
    if (!line.name?.trim() && !line.ref?.trim()) return `Line ${i + 1} needs a name.`;
    const q = num(line.quantity);
    if (q !== null && (Number.isNaN(q) || q < 0)) return `${label}: the quantity must be a number, 0 or more.`;
    const t = lineMttr(line);
    if (t === null) return `${label}: give its repair time (the elements, or one MTTR).`;
    if (Number.isNaN(t)) return `${label}: the repair times must be numbers, 0 or more.`;
    if (t <= 0 && (q === null || q > 0)) return `${label}: the repair time must be more than 0.`;
    const r = num(line.failure_rate);
    if (r !== null && (Number.isNaN(r) || r < 0)) return `${label}: the failure rate must be a number, 0 or more.`;
    const mx = num(line.maximum);
    if (mx !== null && (Number.isNaN(mx) || mx <= t)) return `${label}: "most done by" must be more than its repair time.`;
  }
  const p = num(form.percentile);
  if (p === null || Number.isNaN(p) || p <= 50 || p > 99.9) return "The percentile is a percentage above 50 and at most 99.9.";
  const mtbf = num(form.mtbf);
  if (mtbf !== null && (Number.isNaN(mtbf) || mtbf <= 0)) return "The MTBF must be a number of hours above 0.";
  return null;
}

// A row with nothing typed (the trailing blank row is skipped).
export function isBlank(line) {
  return !line.name?.trim() && !line.ref?.trim() && !line.assembly?.trim() && !hasElements(line)
    && !String(line.mttr ?? "").trim() && !String(line.failure_rate ?? "").trim();
}

// The request the server computes from (analyse, or a saved prediction's
// inputs): numbers parsed, blank cells left out.
export function toInputs(form) {
  const lines = (form.lines || []).filter((l) => !isBlank(l)).map((l) => {
    const out = { name: l.name?.trim() || "", ref: l.ref?.trim() || "", assembly: l.assembly?.trim() || "" };
    const q = num(l.quantity);
    out.quantity = q === null ? 1 : q;
    const r = num(l.failure_rate);
    if (r !== null) out.failure_rate = r;
    if (hasElements(l)) {
      out.elements = {};
      for (const e of ELEMENTS) {
        const v = num(l.elements[e.key]);
        if (v !== null) out.elements[e.key] = v;
      }
    } else {
      out.mttr = num(l.mttr);
    }
    const mx = num(l.maximum);
    if (mx !== null) out.maximum = mx;
    return out;
  });
  const inputs = {
    unit: form.unit || "hours",
    failure_rate_unit: form.failure_rate_unit || "per_million_hours",
    percentile: Number(form.percentile) / 100,
    lines,
  };
  const mtbf = num(form.mtbf);
  if (mtbf !== null) inputs.mtbf = mtbf;
  if (form.product?.id) {
    inputs.product_id = form.product.id;
    inputs.product_name = form.product.name || "";
  }
  return inputs;
}

// A saved prediction's inputs back as the form (to edit a copy).
export function fromInputs(inputs = {}) {
  const form = emptyForm();
  form.unit = inputs.unit || "hours";
  form.failure_rate_unit = inputs.failure_rate_unit || "per_million_hours";
  form.percentile = inputs.percentile != null ? String(Math.round(inputs.percentile * 1000) / 10) : "95";
  form.mtbf = inputs.mtbf != null ? String(inputs.mtbf) : "";
  form.product = inputs.product_id ? { id: inputs.product_id, name: inputs.product_name || "" } : null;
  form.lines = (inputs.lines || []).map((l) => {
    const row = emptyLine();
    row.ref = l.ref || "";
    row.name = l.name || "";
    row.assembly = l.assembly || "";
    row.quantity = l.quantity != null ? String(l.quantity) : "1";
    row.failure_rate = l.failure_rate != null ? String(l.failure_rate) : "";
    row.mttr = l.mttr != null ? String(l.mttr) : "";
    row.maximum = l.maximum != null ? String(l.maximum) : "";
    for (const e of ELEMENTS) row.elements[e.key] = l.elements?.[e.key] != null ? String(l.elements[e.key]) : "";
    // A spread saved as sigma has no "most done by" cell: keep it in the row, unseen but sent back.
    if (l.sigma != null && l.maximum == null) row.sigma = l.sigma;
    return row;
  });
  if (!form.lines.length) form.lines = [emptyLine()];
  return form;
}

// Rows from a product's parts list (the product-lines read): the names,
// refs, assemblies and quantities filled in, the times left to type.
export function linesFromProduct(data) {
  return (data?.lines || []).map((l) => {
    const row = emptyLine();
    row.ref = l.ref || "";
    row.name = l.name || "";
    row.assembly = l.assembly || "";
    row.quantity = l.quantity != null ? String(l.quantity) : "1";
    row.failure_rate = l.failure_rate != null ? String(l.failure_rate) : "";
    return row;
  });
}

const HEAD = {
  ref: ["ref", "reference", "part number", "part no", "part_number", "partnumber", "pn", "p/n", "id"],
  name: ["name", "description", "part", "item", "component", "part name"],
  assembly: ["assembly", "subsystem", "sub-system", "group", "parent", "level", "path", "where"],
  quantity: ["qty", "quantity", "q", "n", "count", "number"],
  failure_rate: ["failure rate", "failure_rate", "rate", "lambda", "λ", "fpmh", "fr"],
  mttr: ["mttr", "repair time", "repair", "time", "hours", "minutes", "mct"],
  maximum: ["maximum", "max", "mmax", "m_max", "most done by", "95%"],
  isolation: ["isolation", "fault isolation", "isolate", "diagnose", "diagnosis"],
  access: ["access", "disassembly", "disassemble"],
  replace: ["replace", "remove and replace", "remove/replace", "r&r", "repair/replace"],
  restore: ["restore", "reassemble", "reassembly", "restoration"],
  checkout: ["checkout", "check out", "check-out", "alignment", "align", "test"],
};

function splitRow(row) {
  if (row.includes("\t")) return row.split("\t");
  if (row.includes(";")) return row.split(";");
  return row.split(",");
}

const looksLikeRef = (s) => /^[A-Za-z0-9][A-Za-z0-9._/-]*$/.test(s) && /\d/.test(s) && s.length <= 40;

// Rows from a pasted parts list: tab-, comma- or semicolon-separated. With a
// header row the columns are read by name (ref, name, assembly, qty, failure
// rate, mttr, the elements, maximum); without one, "ref, name, qty", "name,
// qty" or just "name" per row (a part number is told by its digits).
export function parsePartsList(text) {
  const rows = String(text || "").split(/\r?\n/).map((r) => r.trim()).filter(Boolean);
  if (!rows.length) return [];
  const first = splitRow(rows[0]).map((c) => c.trim().toLowerCase());
  const cols = first.map((c) => Object.keys(HEAD).find((k) => HEAD[k].includes(c)) || null);
  const headed = cols.some(Boolean) && !first.some((c) => /^\d/.test(c));
  const out = [];
  for (const raw of headed ? rows.slice(1) : rows) {
    const cells = splitRow(raw).map((c) => c.trim().replace(/^"|"$/g, ""));
    if (!cells.some(Boolean)) continue;
    const row = emptyLine();
    if (headed) {
      cells.forEach((cell, i) => {
        const key = cols[i];
        if (!key || !cell) return;
        if (ELEMENTS.some((e) => e.key === key)) row.elements[key] = cell;
        else row[key] = cell;
      });
      if (!row.quantity) row.quantity = "1";
    } else {
      let rest = cells.filter(Boolean);
      if (rest.length >= 2 && num(rest[rest.length - 1]) !== null && !Number.isNaN(num(rest[rest.length - 1]))) {
        row.quantity = rest[rest.length - 1];
        rest = rest.slice(0, -1);
      }
      if (rest.length >= 2 && looksLikeRef(rest[0])) {
        row.ref = rest[0];
        row.name = rest.slice(1).join(", ");
      } else {
        row.name = rest.join(", ");
      }
    }
    if (row.name || row.ref) out.push(row);
  }
  return out;
}

// The columns a results table shows for the elements (those any line uses).
export function usedElements(result) {
  const used = new Set();
  for (const line of result?.lines || []) for (const k of Object.keys(line.elements || {})) used.add(k);
  return ELEMENTS.filter((e) => used.has(e.key));
}

// The answer in one sentence's parts: the Mct, and M_max when there is one.
export function headlineParts(result) {
  if (!result) return null;
  return {
    mct: result.mct, mMax: result.m_max, unit: result.unit, percentile: result.percentile,
    availability: result.availability, mtbfHours: result.mtbf_hours,
  };
}

// Inherent availability as a percentage with its decimals: 0.9997 reads
// "99.97%", never "100%" (two decimals at least, three when that close to 1).
export function availabilityText(a) {
  if (a == null || !Number.isFinite(Number(a))) return "—";
  const p = Number(a) * 100;
  const digits = p >= 99.995 ? 3 : 2;
  return `${p.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: digits })}%`;
}

// The weights' source in a few words.
export function weightsText(result) {
  const w = result?.weights;
  if (!w) return "";
  if (w.source === "equal") return "Every line counts the same (no failure rates).";
  if (w.source === "reliability_prediction") return `Weighted by failure rate × quantity, from the reliability prediction “${w.prediction?.name}”.`;
  if (w.source === "mixed") return `Weighted by failure rate × quantity (typed, and from “${w.prediction?.name}”).`;
  return `Weighted by failure rate × quantity (${rateUnitText(result.failure_rate_unit)}).`;
}
