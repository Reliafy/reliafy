import Plot from "./Plot.jsx";

// Series colours by allowed failures (fixed order, never cycled); a fifth
// column — the plan's own failures when above 3 — is slate.
const SERIES = ["#0284c7", "#d97706", "#7c3aed", "#db2777", "#475569"];

// A number for display: 3 significant figures, thousands separators from
// 1,000 (the backend's fmt_num).
export function fmtNum(v) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  if (n === 0) return "0";
  if (Math.abs(n) < 1e-3 || Math.abs(n) >= 1e9) return n.toPrecision(3);
  const r = Number(n.toPrecision(3));
  if (Math.abs(r) >= 1000) return Math.round(n).toLocaleString("en-US");
  return String(r);
}

const pct = (p, dp = 1) => (p == null ? "—" : `${(p * 100).toFixed(dp).replace(/\.0+$/, "")}%`);
const failuresLabel = (f) => `${f} failure${f === 1 ? "" : "s"}`;
const OC_POINT_COLOURS = { Target: "#dc2626", "Good design": "#16a34a" };

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
    {
      type: "scatter",
      mode: "lines",
      name: "Chance of passing",
      showlegend: false,
      x: xs,
      y: oc.pass_probability,
      line: { color: "#0284c7", width: 2.5 },
      hovertemplate: `${xFmt}: passes %{y:.1%}<extra></extra>`,
    },
    ...(oc.points || []).map((pt) => ({
      type: "scatter",
      mode: "markers",
      name: `${pt.label}: passes ${pct(pt.pass_probability)}`,
      x: [isMtbf ? pt.x : pt.x * 100],
      y: [pt.pass_probability],
      cliponaxis: false,
      marker: { size: 11, color: OC_POINT_COLOURS[pt.label] || "#334155", line: { color: "#ffffff", width: 2 } },
      hovertemplate: `${pt.label}: ${xFmt}, passes %{y:.1%}<extra></extra>`,
    })),
  ];
  const layout = {
    autosize: true,
    height: 360,
    margin: { l: 70, r: 20, t: 16, b: 56 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "#ffffff",
    font: { color: "#334155", family: "Inter, system-ui, sans-serif" },
    showlegend: true,
    legend: { orientation: "h", y: -0.3, yanchor: "top" },
    xaxis: {
      title: { text: isMtbf ? `true MTBF${u}` : "true reliability over one mission (%)", standoff: 12 },
      gridcolor: "#e2e8f0",
      zeroline: false,
      nticks: 7,
      automargin: true,
    },
    yaxis: {
      title: { text: "chance of passing", standoff: 12 },
      range: [0, 1.04],
      tickformat: ".0%",
      gridcolor: "#e2e8f0",
      zeroline: false,
    },
  };
  return (
    <>
      <h3 className="demo-h">Operating characteristic</h3>
      <p className="muted-line">
        The chance a design passes this test against its true {isMtbf ? "MTBF" : "reliability"}. At the target it
        is the consumer’s risk; one minus it at the good design is the producer’s risk.
      </p>
      <Plot
        data={traces}
        layout={layout}
        config={{ displayModeBar: false, responsive: true }}
        style={{ width: "100%" }}
        useResizeHandler
      />
    </>
  );
}

// Presentational renderer for a demonstration-test plan — used by the live
// tool, saved analyses and the public link (stored payload, no refetch).
export default function DemoTestResult({ result }) {
  const u = result.unit ? ` ${result.unit}` : "";
  const t = result.tradeoff || { failures: [], rows: [] };
  const isMtbf = result.method === "mtbf";
  const isUnitsCell = t.solve_for === "units";
  const cell = (v) => (v == null ? "—" : isUnitsCell ? Number(v).toLocaleString("en-US") : fmtNum(v));
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
      line: { color: SERIES[Math.min(j, SERIES.length - 1)], width: 2 },
      marker: { size: 8, color: SERIES[Math.min(j, SERIES.length - 1)] },
      connectgaps: false,
      hovertemplate: `%{x:,.4~g}: %{y:,.4~g}<extra>${failuresLabel(f)}</extra>`,
    }));
    const sel = lineRows.find((r) => r.selected);
    if (sel && planCol >= 0 && sel.values[planCol] != null) {
      traces.push({
        type: "scatter",
        mode: "markers",
        name: "This plan",
        x: [sel.x],
        y: [sel.values[planCol]],
        marker: { size: 13, symbol: "diamond", color: "#16a34a", line: { color: "#ffffff", width: 2 } },
        hovertemplate: "This plan: %{y:,.4~g}<extra></extra>",
      });
    }
    layoutAxes = {
      xaxis: {
        title: { text: t.x_label, standoff: 12 },
        gridcolor: "#e2e8f0",
        zeroline: false,
        tickangle: 0,
        nticks: 6,
        automargin: true,
      },
      yaxis: {
        title: { text: t.value_label, standoff: 12 },
        gridcolor: "#e2e8f0",
        rangemode: "tozero",
        zeroline: false,
      },
    };
  } else {
    const row = t.rows.find((r) => r.selected) || t.rows[0];
    traces = row
      ? [{
          type: "bar",
          x: t.failures.map((f) => String(f)),
          y: row.values,
          marker: {
            color: t.failures.map((f) => (f === result.failures ? "#0284c7" : "#93c5fd")),
          },
          text: row.values.map(cell),
          textposition: "outside",
          cliponaxis: false,
          hovertemplate: "%{x} allowed: %{text}<extra></extra>",
          name: t.value_label,
        }]
      : [];
    layoutAxes = {
      xaxis: { title: { text: "allowed failures", standoff: 12 }, type: "category" },
      yaxis: { title: { text: t.value_label, standoff: 12 }, gridcolor: "#e2e8f0", rangemode: "tozero", zeroline: false },
    };
  }
  const layout = {
    autosize: true,
    height: 340,
    margin: { l: 70, r: 20, t: 24, b: 60 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "#ffffff",
    font: { color: "#334155", family: "Inter, system-ui, sans-serif" },
    showlegend: asLines,
    legend: { orientation: "h", y: -0.3, yanchor: "top" },
    bargap: 0.45,
    ...layoutAxes,
  };

  const stats = isMtbf
    ? [
        [fmtNum(result.total_test_time), `total test time${u}`],
        ...(result.units ? [[fmtNum(result.test_time_per_unit), `per unit (${result.units} units)${u}`]] : []),
        [fmtNum(result.mtbf), `MTBF to show${u}`],
        [String(result.failures), "failures allowed"],
      ]
    : [
        [Number(result.units).toLocaleString("en-US"), result.solve_for === "test_time" ? "units on test" : "units to test"],
        [
          result.test_time_per_unit != null ? fmtNum(result.test_time_per_unit) : `${fmtNum(result.test_multiple)}×`,
          result.test_time_per_unit != null ? `test time per unit${u}` : "missions per unit",
        ],
        [String(result.failures), "failures allowed"],
        [pct(result.demonstrated_reliability, 2), "reliability shown"],
      ];
  if (result.pass_probability != null) {
    // Both risks (#223); a plan saved before them has only the pass chance.
    const producer = result.producer_risk ?? 1 - result.pass_probability;
    const target = result.producer_risk_target;
    stats.push([pct(result.consumer_risk), `consumer’s risk (≤ ${pct(1 - result.confidence)})`]);
    stats.push([pct(producer), target != null ? `producer’s risk (≤ ${pct(target)})` : "producer’s risk"]);
  }

  return (
    <>
      <div className="strategy-reco">
        <span className="strategy-reco-icon">✓</span>
        <span>{result.summary}</span>
      </div>

      <div className="params">
        {stats.map(([v, name]) => (
          <div className="stat" key={name}>
            <div className="value">{v}</div>
            <div className="name">{name}</div>
          </div>
        ))}
      </div>

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
        <p className="muted-line">
          Cells: {t.value_label.charAt(0).toLowerCase() + t.value_label.slice(1)}. The highlighted
          cell is this plan.
        </p>
      )}

      <Plot
        data={traces}
        layout={layout}
        config={{ displayModeBar: false, responsive: true }}
        style={{ width: "100%" }}
        useResizeHandler
      />

      <OcCurve result={result} />

      <h3 className="demo-h">Assumptions</h3>
      <ul className="demo-assumptions">
        {(result.assumptions || []).map((a) => (
          <li key={a}>{a}</li>
        ))}
      </ul>
    </>
  );
}
