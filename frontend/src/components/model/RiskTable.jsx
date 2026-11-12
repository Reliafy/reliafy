import Plot from "../Plot.jsx";
import Chip from "../ui/Chip.jsx";
import { formatNumber } from "../../format.js";
import { bandPair, dataPoints, fitLine, referenceShape } from "../../plotTheme.js";
import { bandLevel, medianLowerText, medianText, riskText, riskTone, riskUpperText, sortColumn, sortRiskRows } from "../../joint.js";
import { PlotCard } from "./ModelLayouts.jsx";
import ChartPair from "./ChartPair.jsx";
import "./ModelFrame.css";

// Risk now, one implementation for every place it shows: the table of running
// units (chance of failing over each horizon, median life left, highest risk
// first), a chosen unit in words, and its two charts. The condition and life
// model's own page shows the units in its data (JointResultView); the
// Explorer's class fleet shows the positions under an item class (ClassFleet),
// each scored with the model linked to it.

const n3 = (v) => formatNumber(v);

export function SurvivalChart({ curve, unit, name, title, age = null, fill = false }) {
  if (!curve?.x) return null;
  const traces = [];
  if (curve.sf_lower && curve.sf_upper) traces.push(...bandPair(curve.x, curve.sf_lower, curve.sf_upper, { name: `${bandLevel(curve.alpha_ci)} band` }));
  traces.push(fitLine({ x: curve.x, y: curve.sf, name: "Survival" }));
  const layout = {
    height: 320,
    xaxis: { title: { text: `Age since new${unit ? ` (${unit})` : ""}` } },
    yaxis: { title: { text: "Probability still running" }, range: [0, 1.02] },
    shapes: age != null ? [referenceShape({ x: age })] : [],
    showlegend: true,
  };
  return <Plot fill={fill} data={traces} layout={layout} download={`${name || "Model"} — ${title}`} />;
}

export function MarkerChart({ pred, results, name, fill = false }) {
  const m = pred.marker || {};
  const unit = results.unit || "";
  const marker = results.marker || "reading";
  const pts = pred.markers || [];
  const traces = [
    ...bandPair(m.x, m.lower, m.upper, { name: `${bandLevel(pred.alpha_ci)} interval of its path` }),
    fitLine({ x: m.x, y: m.mean, name: "Its path (smoothed, then projected)" }),
    dataPoints({ x: pts.map((p) => p[0]), y: pts.map((p) => p[1]), name: "Its readings" }),
  ];
  const layout = {
    height: 320,
    xaxis: { title: { text: `Age since new${unit ? ` (${unit})` : ""}` } },
    yaxis: { title: { text: `${marker}${results.marker_unit ? ` (${results.marker_unit})` : ""}` } },
    shapes: [referenceShape({ x: pred.age })],
    showlegend: true,
  };
  return <Plot fill={fill} data={traces} layout={layout} download={`${name || "Model"} — reading trajectory`} />;
}

// Each chance, with its 90% one-sided upper bound under it where the row has one.
function RiskCells({ row, n = 3 }) {
  return Array.from({ length: n }, (_, i) => {
    const up = riskUpperText(row.risk_upper?.[i]);
    return (
      <td key={i} className="num">
        <Chip tone={riskTone(row.risk?.[i])}>{riskText(row.risk?.[i])}</Chip>
        {up && <span className="joint-risk-up" title="90% upper bound: at most this">{up}</span>}
      </td>
    );
  });
}

export { sortColumn };

// The rows a risk table shows, highest risk first (rows with no risk keep
// their order, after the rest).
export function riskOrder(rows, labels) {
  const scored = (rows || []).filter((r) => r.risk);
  return [...sortRiskRows(scored, sortColumn(labels)), ...(rows || []).filter((r) => !r.risk)];
}

// The table. `rows`: [{id, risk: [..], median_remaining, median_reached}] (a
// row with no `risk` has none to show: a dash in each cell, or `whyNot(row)`
// in words across them). `lead`: the columns before the risk ([{id, label,
// num, cell(row)}]); `unit`: the time unit the median life left is in.
export function RiskTable({
  rows: given, labels = [], unit = "", lead, selected, onPick, live = true, whyNot = null,
  empty = "No units are still running in the data.",
}) {
  const rows = riskOrder(given, labels);
  if (!rows.length) return <p className="mf-note">{empty}</p>;
  const columns = lead || [
    { id: "unit", label: "Unit", cell: (r) => r.id },
    { id: "age", label: `Age${unit ? ` (${unit})` : ""}`, num: true, cell: (r) => n3(r.age) },
  ];
  return (
    <table className="calc-table joint-risk">
      <thead>
        <tr>
          {columns.map((c) => <th key={c.id} className={`col-${c.id}${c.num ? " num" : ""}`}>{c.label}</th>)}
          {labels.map((l) => <th key={l} className="num">Fails in next {l}</th>)}
          <th className="num">Median life left</th>
          <th><span className="sr-only">View</span></th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const why = !r.risk && whyNot ? whyNot(r) : null;
          const pick = r.risk ? () => onPick(r.id) : undefined;
          return (
            <tr key={r.id} className={(selected === r.id ? "is-selected" : "") + (r.risk ? "" : " no-risk")} onClick={pick}>
              {columns.map((c) => <td key={c.id} className={`col-${c.id}${c.num ? " num" : ""}`}>{c.cell(r)}</td>)}
              {r.risk ? (
                <>
                  <RiskCells row={r} n={labels.length} />
                  <td className="num">
                    {medianText({ ...r, life_level: null }, unit)}
                    {medianLowerText(r, unit) && (
                      <span className="joint-risk-up" title="90% lower bound: at least this">{medianLowerText(r, unit)}</span>
                    )}
                  </td>
                </>
              ) : why ? (
                <td colSpan={labels.length + 1} className="joint-risk-why">{why}</td>
              ) : (
                <>
                  {labels.map((l) => <td key={l} className="num">—</td>)}
                  <td className="num">—</td>
                </>
              )}
              <td>
                {r.risk && (
                  <button type="button" className="link" aria-pressed={selected === r.id}
                          onClick={(e) => { e.stopPropagation(); onPick(r.id); }}>
                    {selected === r.id && live ? "Shown" : "View"}
                  </button>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// A unit's prediction in words. `what`: what it's called here ("Unit", or
// the Explorer's "Position").
export function UnitSummary({ view, results, what = "Unit" }) {
  const unit = results.unit || "";
  return (
    <p className="joint-unit-sum" role="status">
      {view.unit_id ? <>{what} <b>{view.unit_id}</b>, </> : "This unit, "}
      age {n3(view.age)}{unit ? ` ${unit.toLowerCase()}` : ""}, {view.markers.length} reading{view.markers.length === 1 ? "" : "s"}.{" "}
      {(results.horizons?.labels || []).map((l, i) => `${riskText(view.risk?.[i])} chance of failing in the next ${l}`
        + (view.risk_upper?.[i] != null ? ` (at most ${riskText(view.risk_upper[i])}, 90%)` : "")).join("; ")}.
      {" "}Median life left: {medianText(view, unit)}.
    </p>
  );
}

// Its two charts, read together (its survival from now follows from where
// its reading is heading): side by side where each is wide enough to read,
// else one under the other (ChartPair).
export function UnitCharts({ view, results, name }) {
  const unit = results.unit || "";
  return (
    <ChartPair
      together
      items={[
        { id: "survival", label: "Survival from now", node: (
          <PlotCard title="Survival from now">
            <SurvivalChart fill curve={view.prediction} unit={unit} name={name} title="unit survival" age={view.age} />
          </PlotCard>
        ) },
        { id: "reading", label: `Its ${results.marker || "reading"}`, node: (
          <PlotCard title={`Its ${results.marker || "reading"}`}>
            <MarkerChart fill pred={view.prediction} results={results} name={name} />
          </PlotCard>
        ) },
      ]}
    />
  );
}
