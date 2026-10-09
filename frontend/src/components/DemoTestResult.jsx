import { useEffect, useRef, useState } from "react";
import Plot from "./Plot.jsx";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { formatNumber, formatWithUnit } from "../format.js";
import { unitInText } from "./unitText.js";
import { ACCENT, COLORWAY, DANGER, INK, SUCCESS, fitLine, optimumMarker, sentence } from "../plotTheme.js";

// Series colours by allowed failures: the theme's order, never cycled (there
// are at most five columns).
const SERIES = COLORWAY;

const pct = (p, dp = 1) => (p == null ? "—" : `${(p * 100).toFixed(dp).replace(/\.0+$/, "")}%`);
// An input percentage as given: 0.999 → "99.9%", never rounded up to 100%.
const pctIn = (p) => (p == null ? "—" : `${Number((p * 100).toFixed(4))}%`);
const failuresLabel = (f) => `${f} failure${f === 1 ? "" : "s"}`;
// The target is where the consumer's risk is read (red), the good design the
// producer's (green).
const OC_POINT_COLOURS = { Target: DANGER, "Good design": SUCCESS };

// The test's operating characteristic (#223): the chance of passing against
// the design's true reliability (or MTBF), with the target and the good
// design marked — where the consumer's and producer's risks are read.
function OcCurve({ result }) {
  const oc = result.oc_curve;
  if (!oc || !oc.x?.length) return null;
  const isMtbf = oc.x_kind === "mtbf";
  const u = result.unit ? ` (${result.unit})` : "";
  const xs = isMtbf ? oc.x : oc.x.map((x) => x * 100);
  const xFmt = isMtbf ? "%{x:,.4~g}" : "%{x:.4~g}%";
  const traces = [
    fitLine({
      name: "Chance of passing",
      showlegend: false,
      x: xs,
      y: oc.pass_probability,
      hovertemplate: `${xFmt}: passes %{y:.1%}<extra></extra>`,
    }),
    ...(oc.points || []).map((pt) => ({
      type: "scatter",
      mode: "markers",
      name: `${pt.label}: passes ${pct(pt.pass_probability)}`,
      x: [isMtbf ? pt.x : pt.x * 100],
      y: [pt.pass_probability],
      cliponaxis: false,
      marker: { size: 11, color: OC_POINT_COLOURS[pt.label] || INK, line: { color: "#ffffff", width: 2 } },
      hovertemplate: `${pt.label}: ${xFmt}, passes %{y:.1%}<extra></extra>`,
    })),
  ];
  const layout = {
    height: 360,
    showlegend: true,
    xaxis: {
      title: { text: isMtbf ? `True MTBF${u}` : "True reliability over one mission (%)" },
      nticks: 7,
    },
    yaxis: {
      title: { text: "Chance of passing" },
      range: [0, 1.04],
      tickformat: ".0%",
    },
  };
  return (
    <>
      <h3 className="demo-h">Operating characteristic</h3>
      <p className="rs-note">
        The chance a design passes this test against its true {isMtbf ? "MTBF" : "reliability"}. At the target it
        is the consumer’s risk; one minus it at the good design is the producer’s risk.
      </p>
      <WhenShown>
        <Plot data={traces} layout={layout} />
      </WhenShown>
    </>
  );
}

// Mounts its children once it has a width: a chart folded under Details is
// drawn when the fold opens, at the right size.
function WhenShown({ children }) {
  const ref = useRef(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || shown) return undefined;
    if (typeof ResizeObserver === "undefined") { setShown(true); return undefined; }
    const ro = new ResizeObserver(() => { if (el.offsetWidth > 0) setShown(true); });
    ro.observe(el);
    return () => ro.disconnect();
  }, [shown]);
  return <div ref={ref}>{shown && children}</div>;
}

// The plan in one sentence (#311): "Test 15 units for 100,000 cycles each;
// pass if ≤ 3 fail."
function planSentence(result, unit) {
  const r = result.failures;
  const time = (v) => <b>{formatWithUnit(v, unit)}</b>;
  if (result.method === "mtbf") {
    const pass = r === 0 ? <>pass with <b>no</b> failures</> : <>pass with <b>≤ {r}</b> failure{r === 1 ? "" : "s"}</>;
    return result.units ? (
      <>Test <b>{formatNumber(result.units, { sig: 7 })} units</b> for {time(result.test_time_per_unit)} each
        ({formatWithUnit(result.total_test_time, unit)} in total); {pass}.</>
    ) : (
      <>Run {time(result.total_test_time)} of total test time; {pass}.</>
    );
  }
  const n = <b>{formatNumber(result.units, { sig: 7 })} unit{result.units === 1 ? "" : "s"}</b>;
  const each = result.test_time_per_unit != null
    ? time(result.test_time_per_unit)
    : result.test_multiple === 1
    ? <b>one mission</b>
    : <b>{formatNumber(result.test_multiple)}× the mission</b>;
  const pass = r === 0 ? <>pass if <b>none</b> fail</> : <>pass if <b>≤ {r}</b> fail</>;
  return <>Test {n} for {each} each; {pass}.</>;
}

// What the plan demonstrates, and its two risks, as one muted line.
function planNote(result, unit) {
  const conf = pctIn(result.confidence);
  const target = result.method === "mtbf"
    ? `MTBF ≥ ${formatWithUnit(result.mtbf, unit)}`
    : result.mission_time != null
    ? `≥ ${pctIn(result.reliability)} reliability over ${formatWithUnit(result.mission_time, unit)}`
    : `≥ ${pctIn(result.reliability)} mission reliability`;
  let risks = "";
  if (result.consumer_risk != null) {
    risks = ` A design at the target still passes ${pct(result.consumer_risk)} of the time`;
    if (result.pass_probability != null) {
      const good = result.method === "mtbf"
        ? `an MTBF of ${formatWithUnit(result.design_mtbf, unit)}`
        : `${pctIn(result.design_reliability)} reliability`;
      risks += `; one with ${good} fails ${pct(result.producer_risk ?? 1 - result.pass_probability)}`;
    }
    risks += ".";
  }
  const shape = result.method !== "mtbf" && result.test_multiple !== 1 && result.shape != null
    ? `, assuming a Weibull shape of ${formatNumber(result.shape)}`
    : "";
  return `Shows ${target} at ${conf} confidence${shape}.${risks}`;
}

// Presentational renderer for a demonstration-test plan — used by the live
// tool, saved analyses and the public link (stored payload, no refetch).
// Answer first (#311): the plan in a sentence with three tiles and its risks
// in one muted line (#313: said once), the trade-off chart, then the
// trade-off table, operating characteristic and assumptions under Details.
// ``actions`` (the live tool's Save) sits with the answer.
export default function DemoTestResult({ result, actions = null }) {
  const unit = result.unit ? unitInText(result.unit) : "";
  const t = result.tradeoff || { failures: [], rows: [] };
  const isMtbf = result.method === "mtbf";
  const isUnitsCell = t.solve_for === "units";
  const cell = (v) => (v == null ? "—" : formatNumber(v, { sig: isUnitsCell ? 7 : 3 }));
  const planCol = t.failures.indexOf(result.failures);

  // Chart: one line per allowed-failures count against test length (or
  // units on test); a bar per allowed-failures count when there's one row.
  const lineRows = t.rows.filter((r) => r.x != null);
  const asLines = !isMtbf && lineRows.length > 1;
  let traces;
  let layoutAxes;
  if (asLines) {
    traces = t.failures.map((f, j) => ({
      type: "scatter",
      mode: "lines+markers",
      name: failuresLabel(f),
      x: lineRows.map((r) => r.x),
      y: lineRows.map((r) => r.values[j]),
      line: { color: SERIES[j], width: 2 },
      marker: { size: 7, color: SERIES[j] },
      connectgaps: false,
      hovertemplate: `%{x:,.4~g}: %{y:,.4~g}<extra>${failuresLabel(f)}</extra>`,
    }));
    const sel = lineRows.find((r) => r.selected);
    if (sel && planCol >= 0 && sel.values[planCol] != null) {
      traces.push(optimumMarker({
        name: "This plan",
        x: [sel.x],
        y: [sel.values[planCol]],
        marker: { size: 12 },
        hovertemplate: "This plan: %{y:,.4~g}<extra></extra>",
      }));
    }
    layoutAxes = {
      xaxis: { title: { text: sentence(t.x_label) } },
      yaxis: { title: { text: sentence(t.value_label) }, rangemode: "tozero" },
    };
  } else {
    const row = t.rows.find((r) => r.selected) || t.rows[0];
    traces = row
      ? [{
          type: "bar",
          x: t.failures.map((f) => String(f)),
          y: row.values,
          marker: {
            // This plan's bar is the accent; the alternatives a tint of it.
            color: t.failures.map((f) => (f === result.failures ? ACCENT : "rgba(47, 109, 246, 0.35)")),
          },
          text: row.values.map(cell),
          textposition: "outside",
          cliponaxis: false,
          hovertemplate: "%{x} allowed: %{text}<extra></extra>",
          name: t.value_label,
        }]
      : [];
    layoutAxes = {
      xaxis: { title: { text: "Allowed failures" }, type: "category" },
      yaxis: { title: { text: sentence(t.value_label) }, rangemode: "tozero" },
    };
  }
  const layout = {
    height: 340,
    showlegend: asLines,
    bargap: 0.45,
    ...layoutAxes,
  };

  const timeEach = result.test_time_per_unit != null
    ? formatWithUnit(result.test_time_per_unit, unit)
    : isMtbf
    ? null
    : result.test_multiple === 1
    ? "1 mission"
    : `${formatNumber(result.test_multiple)} missions`;
  const stats = [
    result.units
      ? { label: "Units", value: formatNumber(result.units, { sig: 7 }) }
      : { label: "Total test time", value: formatWithUnit(result.total_test_time, unit) },
    timeEach && { label: "Time each", value: timeEach },
    { label: "Failures allowed", value: String(result.failures) },
  ].filter(Boolean);

  // The risks are in the note line; the assumptions keep the rest.
  const assumptions = (result.assumptions || []).filter((a) => !/the (consumer|producer)['’]s risk[,)]/.test(a));
  const details = [
    !isMtbf && { label: "Reliability shown", value: pct(result.demonstrated_reliability, 2) },
    result.units && result.total_test_time != null && {
      label: "Total test time", value: formatWithUnit(result.total_test_time, unit),
    },
    isMtbf && { label: "MTBF to show", value: formatWithUnit(result.mtbf, unit) },
  ].filter(Boolean);

  return (
    <>
      <ResultSummary tone="neutral" sentence={planSentence(result, unit)} stats={stats}>
        {planNote(result, unit)}
      </ResultSummary>
      {actions && <div className="rs-actions">{actions}</div>}

      <Plot data={traces} layout={layout} />

      <ResultDetails rows={details}>
        <h3 className="demo-h">Trade-off</h3>
        <div className="demo-table-wrap">
          <table className="calc-table strategy-table">
            <thead>
              <tr>
                <th>{t.row_label || t.value_label}</th>
                {t.failures.map((f) => (
                  <th key={f}>{failuresLabel(f)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {t.rows.map((r) => (
                <tr key={r.label} className={r.selected ? "demo-selected" : ""}>
                  <td className="calc-row-label">{r.label}</td>
                  {r.values.map((v, j) => (
                    <td key={j} className={r.selected && j === planCol ? "strategy-best" : ""}>
                      {cell(v)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {t.row_label && (
          <p className="rs-note">
            Cells: {t.value_label.charAt(0).toLowerCase() + t.value_label.slice(1)}. The highlighted
            cell is this plan.
          </p>
        )}

        <OcCurve result={result} />

        {assumptions.length > 0 && (
          <>
            <h3 className="demo-h">Assumptions</h3>
            <ul className="demo-assumptions">
              {assumptions.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </>
        )}
      </ResultDetails>
    </>
  );
}
