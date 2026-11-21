// Availability with repairs (components/RbdRepairAvailability.jsx): the pure parts.
import { unitFactor } from "./unitConvert.js";

// The repair times typed in the section ({block id: text}) as numbers above 0; blanks and
// anything else left out (the block then takes its other source, or is asked for).
export function typedRepairs(typed) {
  const out = {};
  for (const [id, raw] of Object.entries(typed || {})) {
    if (raw === "" || raw == null) continue;
    const v = Number(raw);
    if (Number.isFinite(v) && v > 0) out[id] = v;
  }
  return out;
}

// A block's repair-time model from a mean time to repair typed in `repairUnit` ("hours" where
// the diagram's clock is a time, else the diagram's own unit): exponential with that mean, in
// the diagram's unit, as the server takes a typed time.
export function repairSpecFromMean(mean, diagramUnit, repairUnit = "hours") {
  const f = repairUnit === "hours" ? unitFactor("hour", diagramUnit || "") : null;
  const inDiagram = Number(mean) * (f ?? 1);
  return {
    source: "params", distribution: "Exponential", distribution_id: "exponential",
    params: [{ name: "failure_rate", value: 1 / inDiagram }],
  };
}
