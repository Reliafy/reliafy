// Standby as plants run it (#363): a standby block's arrangement in plain
// words, and its units with models of their own. Mirrors
// backend/services/rbd_standby.py (describe, unit_specs); the server is the
// authority on how a block is worked out (exact, numerical or simulated).

// The most units (running and spares together) that take a model of their own.
export const MAX_OWN_UNITS = 12;

function whole(v, fallback) {
  const n = Number(v);
  return Number.isInteger(n) && n >= 1 ? n : fallback;
}

function percent(v) {
  const pct = v * 100;
  return Math.abs(pct - Math.round(pct)) < 1e-9 ? `${Math.round(pct)}%` : `${Number(pct.toPrecision(3))}%`;
}

// 0 cold, 1 hot, in between warm (older diagrams carry only `cold`).
export function dormancyOf(data) {
  const raw = data?.dormancy;
  if (raw == null || raw === "") return data?.cold ? 0 : 1;
  const d = Number(raw);
  return Number.isFinite(d) ? Math.min(Math.max(d, 0), 1) : 0;
}

export function kindOf(data) {
  const d = dormancyOf(data);
  return d <= 0 ? "cold" : d >= 1 ? "hot" : "warm";
}

function ownList(data, key) {
  return Array.isArray(data?.[key]) ? data[key] : [];
}

// Whether any single unit has a model of its own.
export function hasOwnUnits(data) {
  return ["runningModels", "spareModels"].some((k) => ownList(data, k).some((m) => m && typeof m === "object"));
}

// "2 running, 1 warm spare ageing at 30% while waiting; each spare starts 95% of the time".
export function describeStandby(data) {
  const k = whole(data?.k, 1);
  const spares = whole(data?.spares, 1);
  const kind = kindOf(data);
  let text = `${k} running, ${spares} ${kind} spare${spares === 1 ? "" : "s"}`;
  if (kind === "warm") text += ` ageing at ${percent(dormancyOf(data))} while waiting`;
  else if (kind === "cold") text += " (not ageing while waiting)";
  else text += " (ageing as if running)";
  const start = data?.startProb == null || data.startProb === "" ? 1 : Number(data.startProb);
  if (Number.isFinite(start) && start >= 0 && start < 1) text += `; each spare starts ${percent(start)} of the time`;
  const own = ownList(data, "runningModels").map((m, i) => (m ? i + 1 : 0)).filter(Boolean);
  const spareOwn = ownList(data, "spareModels").map((m, i) => (m ? i + 1 : 0)).filter(Boolean);
  const shared = !!data?.standbyModel && typeof data.standbyModel === "object";
  if (own.length || spareOwn.length || shared) {
    const parts = [];
    if (own.length) parts.push(`running unit${own.length > 1 ? "s" : ""} ${own.join(", ")}`);
    if (spareOwn.length) parts.push(`spare${spareOwn.length > 1 ? "s" : ""} ${spareOwn.join(", ")}`);
    else if (shared) parts.push("the spares");
    const many = own.length + spareOwn.length > 1 || (!spareOwn.length && shared);
    text += `; ${parts.join(" and ")} ${many ? "have their own models" : "has its own model"}`;
  }
  return text;
}

// The units in order, each with the model it fails by and whether that's its
// own: [{ role: "running" | "spare", index, label, model, own }].
export function standbyUnits(data) {
  const k = whole(data?.k, 1);
  const spares = whole(data?.spares, 1);
  const running = ownList(data, "runningModels");
  const spareOwn = ownList(data, "spareModels");
  const base = data?.model ?? null;
  const spareBase = data?.standbyModel ?? base;
  const out = [];
  for (let i = 0; i < k; i++) {
    const own = running[i] || null;
    out.push({ role: "running", index: i, label: k > 1 ? `Running unit ${i + 1}` : "Running unit", model: own || base, own: !!own });
  }
  for (let j = 0; j < spares; j++) {
    const own = spareOwn[j] || null;
    out.push({ role: "spare", index: j, label: spares > 1 ? `Spare ${j + 1}` : "Spare", model: own || spareBase, own: !!own });
  }
  return out;
}

// A per-unit list trimmed to its count, trailing defaults dropped; null when
// no unit in it has a model of its own.
export function tidyOwn(list, count) {
  const out = (Array.isArray(list) ? list : []).slice(0, count).map((m) => m || null);
  while (out.length && !out[out.length - 1]) out.pop();
  return out.length ? out : null;
}
