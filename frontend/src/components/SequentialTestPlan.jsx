// Test planning › Sequential test: test, count failures as they come, and
// stop as soon as the evidence is clear either way (Wald's sequential test,
// stopped at the fixed-length test with the same risks).
import { useState } from "react";
import Plot from "./Plot.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { Assumptions, ComputeButton, Field, PlanAnswer, usePlan } from "./TestPlanShared.jsx";
import { formatNumber, formatWithUnit } from "../format.js";
import { DANGER, INK, SUCCESS, SURFACE, fitLine } from "../plotTheme.js";
import { frac, given, num } from "../testPlanning.js";
import { unitInText } from "./unitText.js";

const pct = (p) => (p == null ? "—" : `${(p * 100).toFixed(1).replace(/\.0$/, "")}%`);

function BoundaryChart({ result }) {
  const b = result.boundaries;
  const mtbf = result.method === "mtbf";
  const x = mtbf ? b.failures : b.units;
  const line = (values, name, color) => ({
    type: "scatter",
    mode: "lines",
    name,
    line: { color, width: 2, shape: "hv" },
    x: mtbf ? values : x,
    y: mtbf ? b.failures : values,
    connectgaps: false,
    hovertemplate: mtbf
      ? `${name}: %{x:,.4~g} at %{y} failures<extra></extra>`
      : `${name}: %{y} failures at %{x} units<extra></extra>`,
  });
  const traces = [line(b.accept, "Accept line", SUCCESS), line(b.reject, "Reject line", DANGER)];
  const d = result.decision;
  if (d) {
    traces.push({
      type: "scatter",
      mode: "markers",
      name: `So far: ${d.verdict === "continue" ? "keep testing" : d.verdict}`,
      x: [mtbf ? d.test_time : d.units],
      y: [d.failures],
      cliponaxis: false,
      marker: { size: 12, color: INK, line: { color: SURFACE, width: 2 } },
    });
  }
  const layout = {
    height: 340,
    showlegend: true,
    xaxis: { title: { text: b.x_label }, rangemode: "tozero" },
    yaxis: { title: { text: "Failures" }, rangemode: "tozero", dtick: mtbf ? undefined : 1 },
  };
  return <Plot data={traces} layout={layout} download="Sequential test — accept and reject lines" />;
}

function OcCharts({ result }) {
  const oc = result.oc_curve;
  const mtbf = oc.x_kind === "mtbf";
  const u = result.unit ? ` (${result.unit})` : "";
  const xs = mtbf ? oc.x : oc.x.map((v) => v * 100);
  const xTitle = mtbf ? `True MTBF${u}` : "True reliability over one mission (%)";
  const xFmt = mtbf ? "%{x:,.4~g}" : "%{x:.4~g}%";
  const marks = (ys) => oc.points.map((pt, i) => ({
    type: "scatter",
    mode: "markers",
    name: pt.label,
    showlegend: false,
    x: [mtbf ? pt.x : pt.x * 100],
    y: [ys(pt, i)],
    cliponaxis: false,
    marker: { size: 11, color: pt.label === "Target" ? DANGER : SUCCESS, line: { color: SURFACE, width: 2 } },
    hovertemplate: `${pt.label}: ${xFmt}<extra></extra>`,
  }));
  const expectedAt = [result.expected.at_target, result.expected.at_good];
  return (
    <>
      <h3 className="demo-h">Operating characteristic</h3>
      <p className="rs-note">
        The chance a design passes, against how good it really is. At the target it is the consumer&apos;s risk; one
        minus it at the good design is the producer&apos;s risk.
      </p>
      <Plot
        data={[
          fitLine({ name: "Chance of passing", showlegend: false, x: xs, y: oc.pass_probability,
            hovertemplate: `${xFmt}: passes %{y:.1%}<extra></extra>` }),
          ...marks((pt) => pt.pass_probability),
        ]}
        layout={{ height: 300, xaxis: { title: { text: xTitle } },
          yaxis: { title: { text: "Chance of passing" }, range: [0, 1.04], tickformat: ".0%" } }}
      />
      <h3 className="demo-h">How long it runs</h3>
      <p className="rs-note">
        The average {mtbf ? "test time" : "number of units"} before the test decides, against how good the design
        really is. Designs near the middle take longest; clearly good or clearly bad ones are decided quickly.
      </p>
      <Plot
        data={[
          fitLine({ name: oc.expected_label, showlegend: false, x: xs, y: oc.expected,
            hovertemplate: `${xFmt}: %{y:,.4~g}<extra></extra>` }),
          ...marks((pt, i) => expectedAt[i]),
        ]}
        layout={{ height: 300, xaxis: { title: { text: xTitle } },
          yaxis: { title: { text: oc.expected_label }, rangemode: "tozero" } }}
      />
    </>
  );
}

export default function SequentialTestPlan() {
  const [method, setMethod] = useState("mtbf");
  const [target, setTarget] = useState("1000");
  const [good, setGood] = useState("2000");
  const [rTarget, setRTarget] = useState("90");
  const [rGood, setRGood] = useState("97");
  const [confidence, setConfidence] = useState("90");
  const [producerRisk, setProducerRisk] = useState("10");
  const [unit, setUnit] = useState("hours");
  const [failuresSeen, setFailuresSeen] = useState("");
  const [seen, setSeen] = useState("");
  const { result, error, loading, run } = usePlan("sequential");
  const mtbf = method === "mtbf";

  const compute = () => {
    const body = { method, confidence: frac(confidence), producer_risk: frac(producerRisk) };
    if (mtbf) Object.assign(body, { mtbf: num(target), good_mtbf: num(good), unit: unit.trim() || null });
    else Object.assign(body, { reliability: frac(rTarget), good_reliability: frac(rGood) });
    if (given(failuresSeen) || given(seen)) {
      body.failures_seen = num(failuresSeen) ?? 0;
      if (mtbf) body.time_seen = num(seen);
      else body.units_seen = num(seen);
    }
    run(body);
  };

  const u = result?.unit ? unitInText(result.unit) : "";
  const stats = result && (result.method === "mtbf"
    ? [
        { label: "Good design, on average", value: formatWithUnit(result.expected.at_good, u) },
        { label: "Fixed-length test", value: formatWithUnit(result.expected.fixed_length, u) },
        { label: "Longest it runs", value: formatWithUnit(result.max_time, u) },
        { label: "Most failures", value: String(result.max_failures) },
      ]
    : [
        { label: "Good design, on average", value: `${formatNumber(result.expected.at_good)} units` },
        { label: "Fixed-length test", value: `${formatNumber(result.expected.fixed_length, { sig: 7 })} units` },
        { label: "Most units", value: formatNumber(result.max_units, { sig: 7 }) },
        { label: "Most failures", value: String(result.max_failures) },
      ]);
  const verdict = result?.decision;
  const tone = verdict ? { accept: "good", reject: "bad", continue: "caveat" }[verdict.verdict] : "neutral";

  return (
    <div className="strategy-tool">
      <p className="tp-explain">
        A sequential test checks the evidence after every failure (and as test time builds up) and stops as soon
        as it is clear. Cross the green line and the design passes; cross the red line and it fails. On average
        it needs much less testing than a fixed-length test with the same risks, but you don&apos;t know the length
        in advance, so plan for the longest.
      </p>
      <div className="strategy-form">
        <div className="demo-toggles">
          <SegmentedControl
            label="Test type"
            showLabel
            value={method}
            onChange={setMethod}
            options={[
              { value: "mtbf", label: "MTBF (failures against test time)" },
              { value: "attribute", label: "Pass/fail (failures against units)" },
            ]}
          />
        </div>
        <div className="strategy-costs">
          {mtbf ? (
            <>
              <Field label="MTBF to demonstrate" value={target} onChange={setTarget} min="0" />
              <Field label="A good design's MTBF" value={good} onChange={setGood} min="0" />
              <Field label="Unit" type="text" value={unit} onChange={setUnit} placeholder="e.g. hours" />
            </>
          ) : (
            <>
              <Field label="Reliability to demonstrate (%)" value={rTarget} onChange={setRTarget} min="0.1" max="99.999" />
              <Field label="A good design's reliability (%)" value={rGood} onChange={setRGood} min="0.1" max="99.999" />
            </>
          )}
          <Field label="Confidence (%)" value={confidence} onChange={setConfidence} min="1" max="99.999" />
          <Field label="Producer's risk (%)" value={producerRisk} onChange={setProducerRisk} min="0.1" max="99.9" />
        </div>
        <div className="strategy-costs">
          <Field label="Failures so far (optional)" value={failuresSeen} onChange={setFailuresSeen} min="0" step="1" />
          <Field
            label={mtbf ? "Total test time so far" : "Units tested so far"}
            value={seen}
            onChange={setSeen}
            min="0"
            placeholder="optional"
          />
          <ComputeButton loading={loading} onClick={compute} />
        </div>
        <p className="hint">
          The consumer&apos;s risk (one minus the confidence) is the chance a design only as good as the target
          passes. The producer&apos;s risk is the chance a good design fails. The closer the good design is to the
          target, the longer any test must run to tell them apart.
        </p>
      </div>

      {error && <div className="error">{error}</div>}
      {result && (
        <>
          <PlanAnswer
            result={result}
            stats={stats}
            tone={tone}
            note={verdict ? <b>{verdict.text}</b> : `Risks as run: a design at the target passes ${pct(
              result.consumer_risk)} of the time; a good design fails ${pct(result.producer_risk)}.`}
          />
          <BoundaryChart result={result} />
          <OcCharts result={result} />
          <Assumptions items={result.assumptions} />
        </>
      )}
    </div>
  );
}
