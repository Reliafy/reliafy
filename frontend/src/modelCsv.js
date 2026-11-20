// The rows of a model's "Download CSV" files: the Calculator's curve, the
// B-lives and the parameters. Each is [[header…], [cell…], …] for
// downloadCsv (csv.js). Numbers stay as the model gave them (full
// precision); units and the bounds' confidence are in the column names, so
// the file reads on its own.
import { unitInText } from "./components/unitText.js";
import { perUnit } from "./lifeResults.js";

// The curve's functions, in the order a reliability engineer reads them.
// Probabilities are fractions (0 to 1), as SurPyval gives them.
const CURVE_FNS = [
  ["sf", "Reliability R(t) (0 to 1)"],
  ["ff", "Probability of failure F(t) (0 to 1)"],
  ["hf", "Hazard rate h(t)", "rate"],
  ["Hf", "Cumulative hazard H(t)"],
  ["df", "Density f(t)", "rate"],
];
const FN_NAME = Object.fromEntries(CURVE_FNS.map(([id, label]) => [id, label]));

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : "");
const inUnit = (unit) => {
  const u = unitInText(unit);
  return u ? ` (${u})` : "";
};

// Linear interpolation of (xs, ys) at x; "" outside the range.
function at(xs, ys, x) {
  if (!xs?.length || !ys?.length || x < xs[0] || x > xs[xs.length - 1]) return "";
  let i = 1;
  while (i < xs.length && xs[i] < x) i++;
  if (xs[i] === x || i >= xs.length) return num(ys[Math.min(i, xs.length - 1)]);
  const [x0, x1, y0, y1] = [xs[i - 1], xs[i], ys[i - 1], ys[i]];
  if (y0 == null || y1 == null) return "";
  return num(y0 + ((y1 - y0) * (x - x0)) / (x1 - x0));
}
const sameGrid = (a, b) => a?.length === b?.length && a.every((v, i) => v === b[i]);

// The bound columns' names: "Reliability R(t) (0 to 1), 90% lower bound".
function boundHeads(band) {
  const name = FN_NAME[band.fn] || band.fn;
  const level = `${band.level}%${band.credible ? " credible" : ""}`;
  const out = [];
  if (band.lower) out.push(band.upper ? `${name}, ${level} two-sided, lower` : `${name}, ${level} lower bound`);
  if (band.upper) out.push(band.lower ? `${name}, ${level} two-sided, upper` : `${name}, ${level} upper bound`);
  return out;
}

// The Calculator's curve.
//   series  [{ label, curve: { x, sf, ff, hf, Hf, df } }] — one per covariate
//           combination; with several, the first column names it
//   unit    the model's time unit
//   band    { fn, level, credible, x, lower?, upper? } on the first series, or null
//           (a series' own ``band`` takes its place: each combination's)
//   given   the survived-to age when the curve is conditional (time is then the further time)
export function curveCsvRows({ series, unit, band = null, given = 0 }) {
  const multi = series.length > 1;
  const u = inUnit(unit);
  const rate = perUnit(unit);
  const timeHead = given > 0 ? `Further time${u}, having survived ${given}` : `Time${u}`;
  const fns = CURVE_FNS.filter(([id]) => series.some((s) => s.curve?.[id]));
  // Each series' own band (a combination's), else ``band`` on the first.
  const bandOf = (s, i) => {
    const b = s.band !== undefined ? s.band : i === 0 ? band : null;
    return b && (b.lower || b.upper) ? b : null;
  };
  const first = series.map(bandOf).find(Boolean) || null;
  const heads = first ? boundHeads(first) : [];
  const head = [
    ...(multi ? ["Combination"] : []),
    timeHead,
    ...fns.map(([, label, kind]) => (kind === "rate" && rate ? `${label} (${rate})` : label)),
    ...heads,
  ];
  const rows = [head];
  series.forEach((s, si) => {
    const c = s.curve;
    if (!c?.x) return;
    const b = bandOf(s, si);
    // Only a band of the same kind as the columns (the same function, sides and level).
    const fits = b && b.fn === first.fn && b.level === first.level && boundHeads(b).join() === heads.join();
    const exact = fits && sameGrid(b.x, c.x);
    c.x.forEach((x, i) => {
      const bounds = !first ? [] : !fits ? heads.map(() => "")
        : [b.lower, b.upper].filter(Boolean).map((ys) => (exact ? num(ys[i]) : at(b.x, ys, x)));
      rows.push([...(multi ? [s.label] : []), num(x), ...fns.map(([id]) => num(c[id]?.[i])), ...bounds]);
    });
  });
  return rows;
}

// The B-lives card: each B-life, its estimate and its one-sided lower bound
// (or, for inspection data, the two inspections it lies between; for a
// library model, its range across plants).
//   rows    [{ label, p, value, lower?, between?: [a, b] }]
//   spread  (b) => { lower, upper } | null, a library model's range
export function bLivesCsvRows({ rows, unit, level, credible = false, spread = null }) {
  const u = inUnit(unit);
  const hasBetween = rows.some((b) => b.between);
  const head = ["B-life", "Fraction failed (0 to 1)", `Estimate${u}`];
  if (hasBetween) head.push(`Between, from${u}`, `Between, to${u}`);
  if (spread) head.push(`Across plants, 5%${u}`, `Across plants, 95%${u}`);
  else head.push(`Lower bound${u}, ${level}% one-sided${credible ? " credible" : ""}`);
  const out = [head];
  for (const b of rows) {
    const r = [b.label, num(b.p), num(b.value)];
    if (hasBetween) r.push(num(b.between?.[0]), num(b.between?.[1]));
    if (spread) {
      const s = spread(b);
      r.push(num(s?.lower), num(s?.upper));
    } else r.push(num(b.lower));
    out.push(r);
  }
  return out;
}

// A model's parameters: their plain name (with the unit), SurPyval's name,
// the value and the interval at the level stated.
//   params   [{ name, label, value, ci?: [lo, hi] }]
//   ciLabel  "90%", "90% credible" or "Source's 5–95%"
export function paramsCsvRows({ params, ciLabel }) {
  const hasCi = params.some((p) => p.ci);
  const words = /^[\d.]+%( credible)?$/.test(ciLabel) ? `${ciLabel} two-sided` : ciLabel;
  const head = ["Parameter", "Name", "Value"];
  if (hasCi) head.push(`${words}, lower`, `${words}, upper`);
  return [head, ...params.map((p) => [p.label || p.name, p.name, num(p.value),
    ...(hasCi ? [num(p.ci?.[0]), num(p.ci?.[1])] : [])])];
}
