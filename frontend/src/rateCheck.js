// A failure rate λ that reads like a mean life (an MTBF typed into the rate box): above 1 per
// unit of time, the mean life is under one unit (50,000 per hour is a failure every 0.07 s).
// Pure, tested in rateCheck.test.js; shown under the λ box by ModelPicker.
import { formatPlain } from "./format.js";
import { unitInText } from "./components/unitText.js";
import { singular } from "./paramLabels.js";

// The parameters that are a rate per unit of time and can be mistaken for a mean life.
const RATE_PARAMS = { exponential: ["failure_rate"] };

// {text, rate} when ``value`` for distId's ``name`` looks like a mean life, else null:
// ("exponential", "failure_rate", 4000, "hours") → "This looks like an MTBF of 4,000 hours; did you
// mean a rate of 0.00025 per hour?", rate 0.00025.
export function rateLooksLikeMean(distId, name, value, unit = "") {
  if (!RATE_PARAMS[distId]?.includes(name)) return null;
  const n = Number(value);
  if (String(value ?? "").trim() === "" || !Number.isFinite(n) || n <= 1) return null;
  const u = unit ? unitInText(unit) : "";
  const rate = Number((1 / n).toPrecision(3));
  const life = u ? `${formatPlain(n, { sig: 6 })} ${u}` : formatPlain(n, { sig: 6 });
  const per = u ? `per ${singular(unit)}` : "per unit of time";
  return {
    rate,
    text: `This looks like an MTBF of ${life}; did you mean a rate of ${formatPlain(rate)} ${per}?`,
  };
}
