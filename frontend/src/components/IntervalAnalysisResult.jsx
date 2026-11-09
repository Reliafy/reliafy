import "./IntervalCalculator.css";
import { money, pct, withUnit } from "../rcmIntervals.js";

// A saved interval calculation from an RCM task card (on_condition_interval: the P-F
// calculator; failure_finding_interval: the test interval), read-only from its stored
// results: what it works out in words, the answer, then the numbers that went in.
export default function IntervalAnalysisResult({ kind, result: r }) {
  if (!r) return null;
  const pf = kind === "on_condition_interval";
  const facts = pf ? [
    ["P-F interval", withUnit(r.pf_interval, r.pf_unit)],
    Number(r.act_time) > 0 && ["Time needed to act", withUnit(r.act_time, r.pf_unit)],
    r.onset_rate != null && ["Failures a year, if nothing is done", r.onset_rate],
    r.run_to_failure_cost_rate != null
      && ["Costs", `check ${money(r.inspection_cost)}, found ${money(r.found_cost)}, failure ${money(r.failure_cost)}`],
    r.cost_optimal && ["Cheapest interval", withUnit(r.cost_optimal.interval, r.cost_optimal.unit)],
    ["Chance a check finds the warning", pct(r.detection_probability)],
    r.rule_of_thumb && ["Rule of thumb", r.rule_of_thumb.text.replace(/^Rule of thumb: /, "")],
  ] : [
    ["Device", r.device?.source === "model" ? `${r.device.distribution} model (${r.device.unit})` : `${r.device?.rate} failures a year`],
    r.target_unavailability != null && ["Target unavailability", pct(r.target_unavailability)],
    r.at_recommended && ["Failed when needed", pct(r.at_recommended.mean_unavailability)],
    r.at_recommended?.cost_rate != null && ["Cost a year", money(r.at_recommended.cost_rate)],
    r.cost_optimal && ["Cheapest interval", withUnit(r.cost_optimal.interval, r.cost_optimal.unit)],
  ];
  return (
    <div className="ivc-saved">
      <p>{r.explanation}</p>
      <p className="ivc-answer">{r.summary}</p>
      <dl className="ivc-facts">
        {facts.filter(Boolean).map(([k, v]) => <div key={k} className="ivc-fact"><dt>{k}</dt><dd>{v}</dd></div>)}
      </dl>
    </div>
  );
}
