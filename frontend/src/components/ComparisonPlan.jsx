// Test planning › Comparison: "did the change work?" planning. Either old and
// new units side by side (a log-rank test), or one fleet's failure rate before
// and after a change (the exact test of two failure rates).
import { useState } from "react";
import Plot from "./Plot.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { Assumptions, ComputeButton, Field, PlanAnswer, usePlan } from "./TestPlanShared.jsx";
import { formatNumber, formatWithUnit } from "../format.js";
import { REFERENCE, fitLine, optimumMarker } from "../plotTheme.js";
import { frac, num } from "../testPlanning.js";
import { unitInText } from "./unitText.js";

const pct = (p) => (p == null ? "—" : `${Math.round(p * 100)}%`);

function Curve({ result }) {
  const c = result.curve;
  if (!c) return null;
  const isPower = Array.isArray(c.power);
  const ys = isPower ? c.power : c.detectable_drop;
  const traces = [fitLine({ name: c.y_label, showlegend: false, x: c.x, y: ys,
    hovertemplate: `%{x:,.4~g}: %{y:.0%}<extra></extra>` })];
  if (c.selected != null) {
    const i = c.x.reduce((best, v, j) => (Math.abs(v - c.selected) < Math.abs(c.x[best] - c.selected) ? j : best), 0);
    if (ys[i] != null) traces.push(optimumMarker({ name: "This plan", x: [c.x[i]], y: [ys[i]],
      hovertemplate: "This plan: %{y:.0%}<extra></extra>" }));
  }
  const shapes = isPower && c.target != null ? [{
    type: "line", xref: "paper", x0: 0, x1: 1, y0: c.target, y1: c.target,
    line: { color: REFERENCE, width: 1.5, dash: "dash" },
  }] : [];
  return (
    <>
      <h3 className="demo-h">{isPower ? "Power against test size" : "What it can detect against test size"}</h3>
      <p className="rs-note">
        {isPower
          ? "The chance of detecting the change, against how much testing you do. The dashed line is the power asked for."
          : "The smallest drop in the failure rate that would reliably show, against the operating time after the change."}
      </p>
      <Plot
        data={traces}
        layout={{ height: 300, showlegend: false, shapes, xaxis: { title: { text: c.x_label }, type: "log" },
          yaxis: { title: { text: c.y_label }, range: [0, 1.04], tickformat: ".0%" } }}
      />
    </>
  );
}

export default function ComparisonPlan() {
  const [kind, setKind] = useState("rate_ratio");
  const [rrSolve, setRrSolve] = useState("exposure");
  const [lrSolve, setLrSolve] = useState("sample_size");
  const [failuresBefore, setFailuresBefore] = useState("40");
  const [exposureBefore, setExposureBefore] = useState("100000");
  const [exposureAfter, setExposureAfter] = useState("50000");
  const [drop, setDrop] = useState("50");
  const [hrDrop, setHrDrop] = useState("40");
  const [eventPct, setEventPct] = useState("50");
  const [perGroup, setPerGroup] = useState("100");
  const [power, setPower] = useState("80");
  const [confidence, setConfidence] = useState("95");
  const [oneSided, setOneSided] = useState(false);
  const [unit, setUnit] = useState("hours");
  const { result, error, loading, run } = usePlan("comparison");
  const rate = kind === "rate_ratio";
  const solve = rate ? rrSolve : lrSolve;

  const compute = () => {
    const body = { kind, solve_for: solve, power: frac(power), confidence: frac(confidence), one_sided: oneSided };
    if (rate) {
      Object.assign(body, { failures_before: num(failuresBefore), exposure_before: num(exposureBefore),
        unit: unit.trim() || null });
      if (solve !== "exposure") body.exposure_after = num(exposureAfter);
      if (solve !== "detectable") body.rate_ratio = drop === "" ? null : 1 - Number(drop) / 100;
    } else {
      Object.assign(body, { hazard_ratio: hrDrop === "" ? null : 1 - Number(hrDrop) / 100,
        event_probability: frac(eventPct) });
      if (solve === "power") body.units_per_group = num(perGroup);
    }
    run(body);
  };

  const u = result?.unit ? unitInText(result.unit) : "";
  let stats = null;
  if (result?.kind === "logrank") {
    stats = [
      { label: "Failures needed", value: formatNumber(result.events, { sig: 7 }) },
      { label: "New units", value: formatNumber(result.units_new, { sig: 7 }) },
      { label: "Old units", value: formatNumber(result.units_old, { sig: 7 }) },
      { label: "Power", value: pct(result.power) },
    ];
  } else if (result) {
    stats = [
      { label: "Failure rate before", value: `${formatNumber(result.rate_before * 1000)} per 1,000${u ? ` ${u}` : ""}` },
      result.solve_for === "exposure"
        ? { label: "Operating time after", value: result.exposure_after == null ? "Not reachable" : formatWithUnit(result.exposure_after, u) }
        : { label: "Operating time after", value: formatWithUnit(result.exposure_after, u) },
      result.solve_for === "detectable"
        ? { label: "Smallest detectable drop", value: result.detectable_ratio == null ? "—" : pct(1 - result.detectable_ratio) }
        : { label: "Change to detect", value: `${pct(Math.abs(1 - result.rate_ratio))} ${result.rate_ratio < 1 ? "drop" : "rise"}` },
      result.solve_for === "power" && { label: "Power", value: pct(result.power) },
    ].filter(Boolean);
  }
  const tone = result && ((result.solve_for === "exposure" && result.exposure_after == null)
    || (result.power != null && result.solve_for === "power" && result.power < (result.power_target ?? 0.8)))
    ? "caveat" : "neutral";

  return (
    <div className="strategy-tool">
      <p className="tp-explain">
        After a change (a new design, a new supplier, a new maintenance procedure) you want to know whether it
        really reduced failures, or whether the drop is luck. That takes enough operating time, or enough failures,
        for the difference to stand out from chance. Plan it before you start, so you know how long to wait before
        judging.
      </p>
      <div className="strategy-form">
        <div className="demo-toggles">
          <SegmentedControl
            label="Comparison"
            showLabel
            value={kind}
            onChange={setKind}
            options={[
              { value: "rate_ratio", label: "Before and after a change (one fleet)" },
              { value: "logrank", label: "Old and new side by side (two groups)" },
            ]}
          />
          {rate ? (
            <SegmentedControl
              label="Solve for"
              showLabel
              value={rrSolve}
              onChange={setRrSolve}
              options={[
                { value: "exposure", label: "Operating time needed" },
                { value: "detectable", label: "Smallest detectable change" },
                { value: "power", label: "Chance of detecting" },
              ]}
            />
          ) : (
            <SegmentedControl
              label="Solve for"
              showLabel
              value={lrSolve}
              onChange={setLrSolve}
              options={[
                { value: "sample_size", label: "Units needed" },
                { value: "power", label: "Chance of detecting" },
              ]}
            />
          )}
        </div>
        <div className="strategy-costs">
          {rate ? (
            <>
              <Field label="Failures before the change" value={failuresBefore} onChange={setFailuresBefore} min="1" step="1" />
              <Field label="Operating time before" value={exposureBefore} onChange={setExposureBefore} min="0" />
              {solve !== "exposure" && (
                <Field label="Operating time after" value={exposureAfter} onChange={setExposureAfter} min="0" />
              )}
              {solve !== "detectable" && (
                <Field label="Drop in failure rate to detect (%)" value={drop} onChange={setDrop} min="1" max="99" />
              )}
              <Field label="Unit" type="text" value={unit} onChange={setUnit} placeholder="e.g. hours" />
            </>
          ) : (
            <>
              <Field label="Drop in failure rate to detect (%)" value={hrDrop} onChange={setHrDrop} min="1" max="99" />
              <Field label="Share of units failing during the study (%)" value={eventPct} onChange={setEventPct} min="1" max="100" />
              {solve === "power" && (
                <Field label="Units in each group" value={perGroup} onChange={setPerGroup} min="2" step="1" />
              )}
            </>
          )}
          {solve !== "power" && <Field label="Power (%)" value={power} onChange={setPower} min="1" max="99.9" />}
          <Field label="Confidence (%)" value={confidence} onChange={setConfidence} min="50" max="99.999" />
          <label className="calc-t tp-check">
            <span>Only looking for an improvement</span>
            <input type="checkbox" checked={oneSided} onChange={(e) => setOneSided(e.target.checked)} />
          </label>
          <ComputeButton loading={loading} onClick={compute} />
        </div>
        <p className="hint">
          Power is the chance the test detects the change if it is real; 80% is usual. Operating time is the
          fleet&apos;s total: ten units for 100 hours is 1,000 hours.
        </p>
      </div>

      {error && <div className="error">{error}</div>}
      {result && (
        <>
          <PlanAnswer result={result} stats={stats} tone={tone} note={result.note || null} />
          <Curve result={result} />
          <Assumptions items={result.assumptions} />
        </>
      )}
    </div>
  );
}
