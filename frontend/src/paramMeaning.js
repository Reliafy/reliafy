// "What do these mean?" beside a fit's parameters (components/LifeSummary.jsx): each parameter in
// plain words, with the fitted value read for this model, before any formula. Null for a parameter
// with nothing plain to say (the panel then just links the guide).
import { formatNumber } from "./format.js";
import { unitInText } from "./components/unitText.js";

const SHAPED = new Set(["weibull", "loglogistic", "expo_weibull"]);

function shapeReading(beta) {
  if (!Number.isFinite(beta)) return "";
  if (beta < 0.95) return ` Here it is ${formatNumber(beta)}, below 1: failures get less likely with age (early-life failures).`;
  if (beta <= 1.05) return ` Here it is ${formatNumber(beta)}, about 1: age makes little difference (random failures).`;
  return ` Here it is ${formatNumber(beta)}, above 1: failures get more likely with age (wear-out).`;
}

// { name: "Shape β", text } for one fitted parameter of distribution `distId`, in unit `unit`.
export function paramMeaning(distId, name, value, unit = "") {
  const v = Number(value);
  const u = unit ? ` ${unitInText(unit)}` : "";
  const at = Number.isFinite(v) ? `${formatNumber(v)}${u}` : null;
  if (SHAPED.has(distId) && name === "beta") {
    return { name: "Shape β", text: "How the chance of failing changes as a unit ages. Below 1, it falls with age; about 1, "
      + "age makes no difference; above 1, it rises with age." + shapeReading(v) };
  }
  if (SHAPED.has(distId) && name === "alpha") {
    return { name: "Scale α", text: distId === "weibull"
      ? `The characteristic life: the age by which about 63% of units have failed, whatever the shape.${at ? ` Here, ${at}.` : ""} A larger α means longer lives.`
      : `The typical life: the age by which half the units have failed.${at ? ` Here, ${at}.` : ""} A larger α means longer lives.` };
  }
  if (distId === "expo_weibull" && name === "mu") {
    return { name: "Exponent μ", text: "A second shape that bends the curve at early ages; 1 makes it a plain Weibull." };
  }
  if (distId === "exponential" && name === "failure_rate") {
    return { name: "Failure rate λ", text: `How many failures to expect per unit of time, the same at every age (random failures).${
      Number.isFinite(v) && v > 0 ? ` The mean life is 1 ÷ λ = ${formatNumber(1 / v)}${u}.` : ""}` };
  }
  if (distId === "lognormal" && name === "mu") {
    return { name: "Log-mean μ", text: `The typical life on a log scale: half the units have failed by e^μ${
      Number.isFinite(v) ? ` = ${formatNumber(Math.exp(v))}${u}` : ""}.` };
  }
  if (distId === "lognormal" && name === "sigma") {
    return { name: "Log-std σ", text: "How spread out the lives are: a larger σ means some units fail much earlier, and some much later, than the typical life." };
  }
  if (distId === "normal" && name === "mu") {
    return { name: "Mean μ", text: `The average life, and the age by which half the units have failed.${at ? ` Here, ${at}.` : ""}` };
  }
  if (distId === "normal" && name === "sigma") {
    return { name: "Std dev σ", text: "How spread out the lives are around the mean: about two in three units fail within one σ of it." };
  }
  if (distId === "gamma" && name === "alpha") {
    return { name: "Shape α", text: "How the chance of failing changes with age: above 1 it rises (wear-out), below 1 it falls." };
  }
  if (distId === "gamma" && name === "beta") {
    return { name: "Rate β", text: `Sets the time scale: the mean life is α ÷ β.` };
  }
  return null;
}
