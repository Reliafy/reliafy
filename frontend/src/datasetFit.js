// What a dataset can be fitted with, from its tags (#261), usual fit first:
// the Data list's row menu. A dataset stands alone: every fit takes this one
// dataset, condition and life included (its life data with its measurements,
// or one table holding both).
export function fitOptions(d) {
  const id = encodeURIComponent(d.id);
  const t = d.tags || [];
  if (t.includes("Repairable")) return [{ label: "Repairable model", to: `/models/recurrent/new?dataset=${id}` }];
  const covs = t.includes("Covariates") || t.includes("Time-varying covariates");
  const life = { label: covs ? "Non-repairable model with covariates" : "Non-repairable model", to: `/models/new?dataset=${id}` };
  const degradation = { label: "Degradation model", to: `/models/degradation?dataset=${id}` };
  if (t.includes("Measurements") && t.includes("Non-repairable")) {
    return [{ label: "Condition and life model", to: `/models/joint/new?dataset=${id}` }, life, degradation];
  }
  if (t.includes("Measurements")) return [degradation];
  return [life];
}

// The saved datasets a "new model" flow can use, from their tags: each flow
// offers only these. Datasets with no tags field (an older server) are kept.
//   life        Non-repairable model (with or without covariates)
//   repairable  Repairable model
//   accelerated accelerated-life model: lifetimes with a stress covariate
//   degradation readings: a measurements part, or a table of readings
//   joint       condition and life: life data with measurements (or one
//               table holding both)
const USABLE = {
  life: (t) => t.includes("Non-repairable"),
  repairable: (t) => t.includes("Repairable"),
  accelerated: (t) => t.includes("Non-repairable") && t.includes("Covariates"),
  degradation: (t) => t.includes("Measurements"),
  joint: (t) => t.includes("Measurements") && t.includes("Non-repairable"),
};

export function usableFor(kind, d) {
  if (!Array.isArray(d?.tags)) return true;
  const rule = USABLE[kind];
  return rule ? rule(d.tags) : true;
}

export const usableDatasets = (kind, datasets) => (datasets || []).filter((d) => usableFor(kind, d));

// ---- The two parts of a dataset, as its page shows them ---------------------
// A dataset holds one table (its life data, or readings alone) and, when
// added, its measurements. The page shows two tabs either way: the part a
// dataset lacks is an empty tab that says how to add it.
//   life          { columns, preview, n_rows, … } of the life data, or null
//   measurements  the same for the readings, or null
//   readingsOnly  the one table is readings (no life data yet)
//   combined      the one table holds both (the server offers a split)
export function datasetParts(d) {
  if (!d) return { life: null, measurements: null, readingsOnly: false, combined: false };
  const t = d.tags || [];
  const table = {
    columns: d.preview_columns || (d.columns || []).map((c) => c.name),
    preview: d.preview || [], n_rows: d.n_rows ?? 0, n_columns: d.n_columns ?? (d.columns || []).length,
    dtypes: d.dtypes, blanks: d.blanks, values: d.values, whole: d.whole, n_unique: d.n_unique,
    types: Object.fromEntries((d.columns || []).map((c) => [c.name, c.dtype])),
  };
  if (d.measurements) {
    const m = d.measurements;
    return {
      life: table,
      measurements: {
        columns: m.preview_columns || (m.columns || []).map((c) => c.name),
        preview: m.preview || [], n_rows: m.n_rows ?? 0, n_columns: m.n_columns ?? (m.columns || []).length,
        dtypes: m.dtypes, blanks: m.blanks, values: m.values, whole: m.whole, n_unique: m.n_unique,
        types: Object.fromEntries((m.columns || []).map((c) => [c.name, c.dtype])),
      },
      readingsOnly: false, combined: false,
    };
  }
  const readingsOnly = t.includes("Measurements") && !t.includes("Non-repairable") && !t.includes("Repairable");
  if (readingsOnly) return { life: null, measurements: table, readingsOnly: true, combined: false };
  return { life: table, measurements: null, readingsOnly: false, combined: !!d.profile?.split };
}

// The page's headline count: "40 rows · 4 columns · 314 readings".
export function datasetMeta(d) {
  const parts = datasetParts(d);
  const n = (x) => (x ?? 0).toLocaleString();
  const words = [];
  if (parts.life) words.push(`${n(parts.life.n_rows)} row${parts.life.n_rows === 1 ? "" : "s"} · ${n(parts.life.n_columns)} column${parts.life.n_columns === 1 ? "" : "s"}`);
  if (parts.measurements) words.push(`${n(parts.measurements.n_rows)} reading${parts.measurements.n_rows === 1 ? "" : "s"}`);
  return words.join(" · ");
}

// The one sentence the split notice says about a combined table.
export function splitText(plan) {
  if (!plan) return "";
  const n = (x) => (x ?? 0).toLocaleString();
  let text = `This table holds life data and readings together: ${n(plan.n_units)} unit${plan.n_units === 1 ? "" : "s"}, `
    + `${n(plan.n_readings)} reading${plan.n_readings === 1 ? "" : "s"}. `
    + `Split it into Life data (${[plan.unit, plan.age, plan.censor, ...(plan.life_columns || [])].join(", ")}) `
    + `and Measurements (${[plan.unit, plan.age, ...(plan.measurement_columns || [])].join(", ")})?`;
  if (plan.n_without_outcome > 0) {
    text += ` ${n(plan.n_without_outcome)} unit${plan.n_without_outcome === 1 ? " has" : "s have"} no outcome flag and would be left out of the life data.`;
  }
  return text;
}
