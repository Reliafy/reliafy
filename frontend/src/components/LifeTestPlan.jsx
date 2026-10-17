// Test planning › Life test: how precisely a test will pin down a B-life or
// the mean life, or how many units (or how long) it takes to get there.
import { useState } from "react";
import Plot from "./Plot.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { Assumptions, Choice, ComputeButton, Field, PlanAnswer, SimulationCheck, usePlan } from "./TestPlanShared.jsx";
import { formatNumber, formatWithUnit } from "../format.js";
import { optimumMarker, fitLine } from "../plotTheme.js";
import { PLAN_DISTRIBUTIONS, frac, num } from "../testPlanning.js";
import { unitInText } from "./unitText.js";

const PARAMS = { weibull: ["alpha", "beta"], lognormal: ["mu", "sigma"] };
const PARAM_LABEL = {
  alpha: "Scale α (characteristic life)",
  beta: "Shape β",
  mu: "μ (log-scale location)",
  sigma: "σ (log-scale spread)",
};

function PrecisionCurve({ result }) {
  const c = result.curve;
  const sel = c.x.indexOf(c.selected);
  const traces = [
    fitLine({ name: "Precision", showlegend: false, x: c.x, y: c.precision,
      hovertemplate: "%{x} units: within a factor of %{y:.3~g}<extra></extra>" }),
  ];
  if (sel >= 0) {
    traces.push(optimumMarker({ name: "This plan", x: [c.x[sel]], y: [c.precision[sel]],
      hovertemplate: "This plan: %{y:.3~g}<extra></extra>" }));
  }
  return (
    <>
      <h3 className="demo-h">More units, more precision</h3>
      <p className="rs-note">
        The precision factor against the units on test, with the test stopping the same way. Each doubling of the
        units narrows the interval less than the one before.
      </p>
      <Plot
        data={traces}
        layout={{ height: 300, showlegend: false, xaxis: { title: { text: c.x_label }, type: "log" },
          yaxis: { title: { text: "Precision factor (lower is better)" } } }}
      />
    </>
  );
}

export default function LifeTestPlan() {
  const [solveFor, setSolveFor] = useState("precision");
  const [distribution, setDistribution] = useState("weibull");
  const [values, setValues] = useState({ alpha: "1000", beta: "2", mu: "6.5", sigma: "0.6" });
  const [quantity, setQuantity] = useState("b_life");
  const [bLife, setBLife] = useState("10");
  const [units, setUnits] = useState("30");
  const [precision, setPrecision] = useState("30");
  const [testEnd, setTestEnd] = useState("time");
  const [censorTime, setCensorTime] = useState("500");
  const [share, setShare] = useState("50");
  const [confidence, setConfidence] = useState("90");
  const [unit, setUnit] = useState("hours");
  const { result, inputs, error, loading, run } = usePlan("life");

  const compute = () => {
    const names = PARAMS[distribution];
    const body = {
      solve_for: solveFor,
      distribution,
      params: names.map((name) => ({ name, value: num(values[name]) })),
      quantity,
      b_life: quantity === "b_life" ? num(bLife) : null,
      confidence: frac(confidence),
      test_end: solveFor === "length" && testEnd === "all" ? "time" : testEnd,
      unit: unit.trim() || null,
    };
    if (solveFor !== "units") body.units = num(units);
    if (solveFor !== "precision") body.precision = num(precision);
    if (solveFor !== "length" && testEnd === "time") body.censor_time = num(censorTime);
    if (solveFor !== "length" && testEnd === "failures") body.failure_fraction = frac(share);
    run(body);
  };

  const u = result?.unit ? unitInText(result.unit) : "";
  const stats = result && [
    { label: "Units", value: formatNumber(result.n, { sig: 7 }) },
    result.censor_time != null
      ? { label: "Test length", value: formatWithUnit(result.censor_time, u) }
      : result.failures != null
      ? { label: "Stop at failure", value: String(result.failures) }
      : { label: "Test length", value: "Until all fail" },
    { label: "Expected failures", value: formatNumber(result.expected_failures) },
    { label: "Precision", value: `±${formatNumber((result.precision - 1) * 100, { sig: 2 })}%` },
  ];

  return (
    <div className="strategy-tool">
      <p className="tp-explain">
        A life test estimates how long the part lasts. With a handful of failures the answer is rough; with many it
        is tight. Give your best guess of the life distribution (the shape matters most: take it from a similar part
        or an earlier test) and see how tight the estimate will be, or how many units or how long a test it takes to
        reach the precision you need.
      </p>
      <div className="strategy-form">
        <div className="demo-toggles">
          <SegmentedControl
            label="Solve for"
            showLabel
            value={solveFor}
            onChange={setSolveFor}
            options={[
              { value: "precision", label: "Precision of a test" },
              { value: "units", label: "Units to test" },
              { value: "length", label: "Test length" },
            ]}
          />
          <SegmentedControl
            label="Estimate"
            showLabel
            value={quantity}
            onChange={setQuantity}
            options={[
              { value: "b_life", label: "A B-life (e.g. B10)" },
              { value: "mean", label: "The mean life" },
            ]}
          />
        </div>
        <div className="strategy-costs">
          <Choice label="Life distribution" value={distribution} onChange={setDistribution} options={PLAN_DISTRIBUTIONS} />
          {PARAMS[distribution].map((name) => (
            <Field
              key={name}
              label={PARAM_LABEL[name]}
              value={values[name]}
              onChange={(v) => setValues((prev) => ({ ...prev, [name]: v }))}
            />
          ))}
          {quantity === "b_life" && <Field label="B-life (% failed)" value={bLife} onChange={setBLife} min="0.1" max="99" />}
          <Field label="Confidence (%)" value={confidence} onChange={setConfidence} min="1" max="99.999" />
          <Field label="Unit" type="text" value={unit} onChange={setUnit} placeholder="e.g. hours" />
        </div>
        <div className="strategy-costs">
          {solveFor !== "units" && <Field label="Units on test" value={units} onChange={setUnits} min="2" step="1" />}
          {solveFor !== "precision" && (
            <Field label="Precision wanted (within ± %)" value={precision} onChange={setPrecision} min="1" />
          )}
          <Choice
            label="The test stops"
            value={solveFor === "length" && testEnd === "all" ? "time" : testEnd}
            onChange={setTestEnd}
            options={solveFor === "length"
              ? { time: "At a set time", failures: "At a set failure" }
              : { time: "At a set time", failures: "When a share have failed", all: "When every unit has failed" }}
          />
          {solveFor !== "length" && testEnd === "time" && (
            <Field label="Test length" value={censorTime} onChange={setCensorTime} min="0" />
          )}
          {solveFor !== "length" && testEnd === "failures" && (
            <Field label="Share failed at the stop (%)" value={share} onChange={setShare} min="1" max="100" />
          )}
          <ComputeButton loading={loading} onClick={compute} />
        </div>
        <p className="hint">
          Precision here means the width of the confidence interval: ±30% means the interval runs from about the
          estimate ÷ 1.3 to the estimate × 1.3.
        </p>
      </div>

      {error && <div className="error">{error}</div>}
      {result && (
        <>
          <PlanAnswer result={result} stats={stats} />
          <PrecisionCurve result={result} />
          <SimulationCheck kind="life" inputs={inputs} />
          <Assumptions
            items={result.assumptions}
            rows={[
              { label: `Planned ${result.label}`, value: formatWithUnit(result.estimate, u) },
              { label: "Interval", value: `${formatWithUnit(result.interval[0], u)} to ${formatWithUnit(result.interval[1], u)}` },
              { label: "Precision factor", value: formatNumber(result.precision) },
            ]}
          />
        </>
      )}
    </div>
  );
}
