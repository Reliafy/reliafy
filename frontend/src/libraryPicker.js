// The logic behind "Pick a library record" (components/LibraryRecordPicker.jsx): a wide modal
// search over the data library, opened from a cramped dialog (the Fit dialog's Prior, the
// Explorer's Life model › From the data library…). Derryn, 9 Nov 2026: the inline list in the Fit
// dialog's left column was too crowded to tell near-identical records apart.

import { KIND_LABEL, familyName, isLife, rangeText, sig, usableSource } from "./libraryModels.js";

// The library last picked from in this browser tab (sessionStorage when it works, else memory).
const LAST_KEY = "reliafy.libraryPicker.last";
let lastInMemory = null;

export function rememberLibrary(id) {
  lastInMemory = id ?? "";
  try { window.sessionStorage.setItem(LAST_KEY, lastInMemory); } catch { /* private window: memory only */ }
}

export function lastLibrary() {
  try {
    const v = window.sessionStorage.getItem(LAST_KEY);
    if (v !== null) return v;
  } catch { /* no storage */ }
  return lastInMemory;
}

// The library the picker opens on: the last one used in this session if it's still listed ("" is
// "Every library"), else the first with records usable as a model or a prior, else the first.
export function defaultLibrary(sources, last = null) {
  const list = sources || [];
  if (last === "" || (last && list.some((s) => s.id === last))) return last;
  return (list.find(usableSource) || list[0])?.id || "";
}

// The Library dropdown: the user's own first ("<name> (yours)"), then the published ones.
export function libraryOptions(sources) {
  const list = sources || [];
  return [...list.filter((s) => s.mine), ...list.filter((s) => !s.mine)]
    .map((s) => ({ value: s.id, label: s.mine ? `${s.name} (yours)` : s.short_name || s.name }));
}

// A filter's choices from the search's facets ({value: count}), each with its count, plus the one
// chosen even when nothing has it now (so the dropdown still shows it). ``labels`` names the values.
export function facetOptions(counts, chosen = "", labels = {}) {
  const out = Object.entries(counts || {}).map(([value, n]) => ({ value, label: `${labels[value] || value} (${n})` }));
  if (chosen && !out.some((o) => o.value === chosen)) out.push({ value: chosen, label: `${labels[chosen] || chosen} (0)` });
  return out;
}

// The Kind filter shows only where there's a choice to make: two kinds or more in what's found.
export const showsKind = (kinds, chosen = "") => !!chosen || Object.keys(kinds || {}).length > 1;

// Where the highlight goes for a key: up and down one row, Home and End, a page of ten. Null when
// the key isn't one of these (or there's nothing to move over).
export function moveHighlight(index, key, count) {
  if (!count) return null;
  const i = index == null || index < 0 ? -1 : Math.min(index, count - 1);
  switch (key) {
    case "ArrowDown": return Math.min(i + 1, count - 1);
    case "ArrowUp": return i <= 0 ? 0 : i - 1;
    case "Home": return 0;
    case "End": return count - 1;
    case "PageDown": return Math.min(Math.max(i, 0) + 10, count - 1);
    case "PageUp": return Math.max(i - 10, 0);
    default: return null;
  }
}

// A record's value with its unit: a rate's mean ("2.26e−6 per hour (running)"), a life record's
// mean life ("mean life 691,000 hours").
export function valueText(r) {
  if (!r) return "";
  if (isLife(r)) return r.mean != null ? `mean life ${sig(r.mean)} ${r.units || ""}`.trim() : familyName(r.family) || "Life model";
  return r.mean != null ? `${sig(r.mean)} ${r.units || ""}`.trim() : "—";
}

// The one summary line the Fit dialog keeps once a record is picked:
// "Motor-driven pump: fails to run · 2.26e−6 per hour (running) · NRC/INL 2020".
export const recordSummary = (r) => (r ? [r.label, valueText(r), r.source].filter(Boolean).join(" · ") : "");

// A row's grey detail line on a phone (the table's other columns in one line).
export function rowDetail(r, equipmentLabels = {}) {
  return [equipmentLabels[r.equipment_type] || r.equipment_type, r.failure_mode, KIND_LABEL[r.kind] || r.kind, valueText(r),
    r.p05 != null && r.p95 != null ? `5–95%: ${rangeText(r)}` : null, r.source].filter(Boolean).join(" · ");
}

// A full record (GET /api/library/records/{id}) as the search's row shape, for a dialog opened with
// a record already chosen (Use as a prior… on a record's page). ``sources``: the sources list, for
// the short name.
export function rowFromDetail(detail, sources = []) {
  const rec = detail?.record;
  if (!rec) return null;
  const src = (sources || []).find((s) => s.id === rec.source);
  const s = rec.summary || {};
  return {
    id: rec.id, label: rec.label, kind: rec.kind, equipment_type: rec.equipment_type, failure_mode: rec.failure_mode?.name || "",
    mean: s.mean ?? null, p05: s.p05 ?? null, p95: s.p95 ?? null, b10: s.b10 ?? null, units: detail.units || "",
    source: src ? src.short_name || src.name : rec.source, basis: rec.basis,
    family: rec.distribution?.family, params: rec.distribution?.params,
  };
}
