// Covariates that change over time on RBD blocks (#52): the node covariate
// modal's presets, the stored schedule shape and the stair-step picture.
// Pure, so `node --test src/` covers it. The schedule itself is checked and
// evaluated on the server (backend/services/rbd_tvc.py).

export const PRESETS = [
  { id: "constant", label: "Constant", title: "One value throughout" },
  { id: "phases", label: "Phases", title: "A value for each mission phase, changing at set times" },
  { id: "duty", label: "Duty cycle", title: "On and off in a repeating cycle" },
  { id: "ramp", label: "Ramp (stepped)", title: "Rises by a fixed step at regular intervals" },
  { id: "geometric", label: "Geometric", title: "Grows by a fixed factor at regular intervals" },
];

// A round number near v: one significant figure (3,200 → 3,000).
export function niceNumber(v) {
  const x = Number(v);
  if (!Number.isFinite(x) || x <= 0) return 1;
  return Number(x.toPrecision(1));
}

// A number as typed in an expression: up to 4 significant figures, no
// thousands separators or trailing zeros.
export function exprNumber(v) {
  const x = Number(v);
  if (!Number.isFinite(x)) return "0";
  if (x === 0) return "0";
  return String(Number(x.toPrecision(4)));
}

// The repeating cycle a duty-cycle preset starts from, in the diagram's unit:
// a day (8 h on) for hours, a week (5 days on) for days, else a twentieth of
// the window.
export function dutyCycle(unit, tMax) {
  const u = String(unit || "").trim().toLowerCase();
  if (/^(h|hr|hrs|hour|hours)$/.test(u)) return { period: 24, on: 8 };
  if (/^(d|day|days)$/.test(u)) return { period: 7, on: 5 };
  const period = niceNumber((Number(tMax) || 1000) / 20);
  return { period, on: niceNumber(period / 3) };
}

// The editable template a preset inserts for a numeric covariate: built from
// its fitted range (low / high), its current value and the window `tMax`.
export function presetExpression(id, field, { value, tMax, unit } = {}) {
  const lo = Number.isFinite(Number(field?.min)) ? Number(field.min) : null;
  const hi = Number.isFinite(Number(field?.max)) ? Number(field.max) : null;
  const v = Number.isFinite(Number(value)) ? Number(value) : Number(field?.default) || 0;
  const low = lo ?? v;
  const high = hi ?? (v ? v * 1.2 : 1);
  const T = Number(tMax) > 0 ? Number(tMax) : 1000;
  const n = exprNumber;
  switch (id) {
    case "constant":
      return n(v);
    case "phases": {
      const t1 = niceNumber(T / 3);
      const t2 = niceNumber((T * 2) / 3) > t1 ? niceNumber((T * 2) / 3) : t1 * 2;
      return `${n(low)} if t < ${n(t1)} else (${n(high)} if t < ${n(t2)} else ${n(v)})`;
    }
    case "duty": {
      const { period, on } = dutyCycle(unit, T);
      return `${n(high)} if t % ${n(period)} < ${n(on)} else ${n(low)}`;
    }
    case "ramp": {
      const every = niceNumber(T / 5);
      const step = Number(field?.step) > 0 ? Number(field.step) : niceNumber((high - low) / 4 || Math.abs(v) / 10 || 1);
      return `${n(low)} + ${n(step)} * floor(t / ${n(every)})`;
    }
    case "geometric": {
      const every = niceNumber(T / 5);
      return `${n(low || v || 1)} * 1.1 ** floor(t / ${n(every)})`;
    }
    default:
      return n(v);
  }
}

// A categorical covariate's phase table to start from: its current level from 0.
export function initialTable(field, value) {
  const level = value ?? field?.default ?? (field?.options || [])[0] ?? "";
  return [{ t: "0", value: String(level) }];
}

// The modal's draft for one scheduled covariate -> the stored schedule
// ({expression} or {table, period?}); null when there's nothing to store.
export function scheduleSpec(draft) {
  if (!draft) return null;
  if (draft.table) {
    const table = draft.table
      .filter((r) => String(r.t).trim() !== "")
      .map((r) => ({ t: Number(r.t), value: r.value }));
    if (!table.length) return null;
    const period = String(draft.period ?? "").trim();
    return period ? { table, period: Number(period) } : { table };
  }
  const expression = String(draft.expression ?? "").trim();
  return expression ? { expression } : null;
}

// A stored schedule -> the modal's draft.
export function draftFromSpec(spec) {
  if (!spec) return null;
  if (spec.table) {
    return {
      table: spec.table.map((r) => ({ t: String(r.t), value: String(r.value) })),
      period: spec.period != null ? String(spec.period) : "",
    };
  }
  return { expression: String(spec.expression ?? "") };
}

// Every scheduled covariate of one block ({name: spec}), or null for none.
export function blockSchedules(modes, drafts) {
  const out = {};
  for (const [name, mode] of Object.entries(modes || {})) {
    if (mode !== "schedule") continue;
    const spec = scheduleSpec((drafts || {})[name]);
    if (spec) out[name] = spec;
  }
  return Object.keys(out).length ? out : null;
}

// The calculator bar's words for a covariate: its value, or that it follows
// a schedule.
export function covariateWords(name, value, spec) {
  return spec ? `${name} follows a schedule` : `${name}=${value}`;
}

// A stair-step path through (times[i], values[i]) out to xMax: each value
// held flat until the next time. Returns [[x, y], ...].
export function stairPoints(times, values, xMax) {
  const pts = [];
  const n = Math.min(times?.length || 0, values?.length || 0);
  for (let i = 0; i < n; i++) {
    const end = i + 1 < n ? Number(times[i + 1]) : Number(xMax);
    const start = Number(times[i]);
    if (!(start <= xMax)) break;
    pts.push([start, values[i]], [Math.min(end, xMax), values[i]]);
  }
  return pts;
}

// The value of a stair-step path at x.
export function stairValueAt(times, values, x) {
  let v = values?.[0];
  for (let i = 0; i < (times?.length || 0); i++) {
    if (Number(times[i]) <= x) v = values[i];
    else break;
  }
  return v;
}
