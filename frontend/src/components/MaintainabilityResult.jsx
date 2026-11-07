import { Fragment } from "react";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { formatNumber, formatPercent, formatWithUnit } from "../format.js";
import { ELEMENTS, availabilityText, rateUnitText, usedElements, weightsText } from "../maintainability.js";

// A maintainability prediction's results: the answer first (Mct, M_max,
// availability), then where the time goes, the Pareto of the lines, the
// roll-up by assembly, and every line's figures folded under Details.
//
//   result   the server's results (analyse, or a saved prediction's)
//   actions  node — buttons under the answer (Save)

const pctText = (p) => `${Math.round(p * 1000) / 10}%`;

function Bar({ share, tone = "acc" }) {
  const w = Math.max(0, Math.min(100, Math.round((share || 0) * 1000) / 10));
  return (
    <span className={`mp-bar mp-bar-${tone}`} aria-hidden="true">
      <span className="mp-bar-fill" style={{ width: `${w}%` }} />
    </span>
  );
}

export default function MaintainabilityResult({ result, actions }) {
  if (!result) return null;
  const unit = result.unit || "hours";
  const p = pctText(result.percentile ?? 0.95);
  const stats = [
    { label: "Mean repair time (Mct)", value: formatWithUnit(result.mct, unit) },
    { label: `Most repairs done by (M_max, ${p})`, value: result.m_max != null ? formatWithUnit(result.m_max, unit) : "—",
      hint: result.m_max == null ? "Needs a spread on the lines" : null },
    { label: "Inherent availability", value: availabilityText(result.availability),
      hint: result.availability == null ? "Needs failure rates or an MTBF" : null },
    result.mtbf_hours != null
      ? { label: "MTBF", value: formatWithUnit(result.mtbf_hours, "hours"),
          hint: result.mtbf_source === "typed" ? "As typed" : "1 ÷ the summed failure rates" }
      : null,
  ];
  const top = result.pareto?.[0];
  const sentence = (
    <>
      A repair takes <b>{formatWithUnit(result.mct, unit)}</b> on average
      {result.m_max != null && <>, and {p} of repairs are done within <b>{formatWithUnit(result.m_max, unit)}</b></>}
      {result.availability != null && <>; inherent availability is <b>{availabilityText(result.availability)}</b></>}.
      {top && <> The biggest share of the maintenance time is <b>{top.name || top.ref}</b> ({formatPercent(top.share)}).</>}
    </>
  );
  const tone = result.weights?.source === "equal" || result.m_max == null ? "caveat" : "neutral";
  const elementCols = usedElements(result);
  const rateUnit = rateUnitText(result.failure_rate_unit);
  const rated = result.weights?.source !== "equal";
  return (
    <div className="mp-result">
      <ResultSummary tone={tone} sentence={sentence} stats={stats} wt="mp-result">
        {weightsText(result)}
        {result.weights?.source === "equal" && result.weights?.note ? ` ${result.weights.note}` : ""}
        {result.m_max_note ? ` ${result.m_max_note}` : ""}
        {result.availability_note ? ` ${result.availability_note}` : ""}
      </ResultSummary>
      {actions && <div className="mp-actions">{actions}</div>}

      <section className="mp-section">
        <h3>Where the repair time goes</h3>
        <p className="muted-line">Each element's share of the mean repair time, over every line, weighted the same way.</p>
        <div className="maint-scroll">
          <table className="lib-table mp-table">
            <thead><tr><th>Element</th><th className="mp-num">Time ({unit})</th><th className="mp-num">Share</th><th className="mp-barcol"><span className="sr-only">Share</span></th></tr></thead>
            <tbody>
              {Object.values(result.elements || {}).map((e) => (
                <tr key={e.label}>
                  <td>{e.label}</td>
                  <td className="mp-num">{formatNumber(e.time)}</td>
                  <td className="mp-num">{formatPercent(e.share)}</td>
                  <td className="mp-barcol"><Bar share={e.share} tone="muted" /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mp-section">
        <h3>What takes the time: the lines, largest share first</h3>
        <p className="muted-line">
          A line's share is its failure rate × quantity × repair time, out of the total. Shorten the repair of the
          lines at the top, or make them fail less often, and Mct comes down most.
        </p>
        <div className="maint-scroll">
          <table className="lib-table mp-table">
            <thead>
              <tr>
                <th>Line</th>
                <th className="mp-num">Qty</th>
                {rated && <th className="mp-num">Failure rate ({rateUnit})</th>}
                <th className="mp-num">MTTR ({unit})</th>
                <th className="mp-num">Share</th>
                <th className="mp-num">Cumulative</th>
                <th className="mp-barcol"><span className="sr-only">Share</span></th>
              </tr>
            </thead>
            <tbody>
              {(result.pareto || []).map((l) => (
                <tr key={l.index}>
                  <td>
                    <div className="lib-name">{l.name || l.ref}</div>
                    {(l.ref || l.assembly) && <div className="lib-date">{[l.ref, l.assembly].filter(Boolean).join(" · ")}</div>}
                  </td>
                  <td className="mp-num">{formatNumber(l.quantity)}</td>
                  {rated && <td className="mp-num">{formatNumber(l.failure_rate)}</td>}
                  <td className="mp-num">{formatNumber(l.mttr)}</td>
                  <td className="mp-num">{formatPercent(l.share)}</td>
                  <td className="mp-num">{formatPercent(l.cumulative)}</td>
                  <td className="mp-barcol"><Bar share={l.share} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {result.assemblies?.length > 0 && (
        <section className="mp-section">
          <h3>By assembly</h3>
          <p className="muted-line">Each assembly's lines together: its own mean repair time and its share of the total.</p>
          <div className="maint-scroll">
            <table className="lib-table mp-table">
              <thead>
                <tr>
                  <th>Assembly</th>
                  <th className="mp-num">Lines</th>
                  {rated && <th className="mp-num">Failure rate ({rateUnit})</th>}
                  <th className="mp-num">Mct ({unit})</th>
                  <th className="mp-num">Share</th>
                  <th className="mp-barcol"><span className="sr-only">Share</span></th>
                </tr>
              </thead>
              <tbody>
                {result.assemblies.map((a) => (
                  <tr key={a.path}>
                    <td style={{ paddingLeft: `${12 + (a.level - 1) * 18}px` }}>{a.path.split(" › ").pop()}</td>
                    <td className="mp-num">{a.lines}</td>
                    {rated && <td className="mp-num">{formatNumber(a.failure_rate)}</td>}
                    <td className="mp-num">{formatNumber(a.mct)}</td>
                    <td className="mp-num">{formatPercent(a.share)}</td>
                    <td className="mp-barcol"><Bar share={a.share} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <ResultDetails summary="Every line's figures" rows={[
        { label: "Lines", value: result.counts?.lines },
        { label: "Lines with a failure rate", value: result.counts?.with_rates },
        { label: "Lines with a spread (for M_max)", value: result.counts?.with_spread },
        result.system_failure_rate != null
          ? { label: `System failure rate (${rateUnit})`, value: formatNumber(result.system_failure_rate, { sig: 4 }) }
          : null,
        { label: "Mct in hours", value: formatNumber(result.mct_hours, { sig: 4 }) },
      ]}>
        <div className="maint-scroll">
          <table className="lib-table mp-table">
            <thead>
              <tr>
                <th>Line</th>
                <th className="mp-num">Qty</th>
                {rated && <th className="mp-num">Failure rate</th>}
                {elementCols.map((e) => <th key={e.key} className="mp-num" title={e.label}>{e.short}</th>)}
                <th className="mp-num">MTTR ({unit})</th>
                <th className="mp-num">Sigma</th>
                <th className="mp-num">M_max ({p})</th>
              </tr>
            </thead>
            <tbody>
              {(result.lines || []).map((l) => (
                <tr key={l.index}>
                  <td>
                    <div className="lib-name">{l.name || l.ref}</div>
                    {(l.ref || l.assembly) && <div className="lib-date">{[l.ref, l.assembly].filter(Boolean).join(" · ")}</div>}
                  </td>
                  <td className="mp-num">{formatNumber(l.quantity)}</td>
                  {rated && (
                    <td className="mp-num">
                      {formatNumber(l.failure_rate)}
                      {l.rate_source === "reliability_prediction" && <span className="lib-date" title="From the reliability prediction"> (pred.)</span>}
                    </td>
                  )}
                  {elementCols.map((e) => (
                    <Fragment key={e.key}><td className="mp-num">{l.elements?.[e.key] != null ? formatNumber(l.elements[e.key]) : "—"}</td></Fragment>
                  ))}
                  <td className="mp-num">{formatNumber(l.mttr)}</td>
                  <td className="mp-num">{l.sigma != null ? formatNumber(l.sigma) : "—"}</td>
                  <td className="mp-num">{l.m_max != null ? formatNumber(l.m_max) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted-line">
          Mct = Σ(λ·q·MTTR) ÷ Σ(λ·q). M_max: each line's repair time is lognormal with its MTTR as the mean and its
          spread; the system's repair time is the mix of the lines' (weighted by λ·q), and M_max is that mix's {p} point.
          Inherent availability = MTBF ÷ (MTBF + Mct), both in hours.
          {" "}{ELEMENTS.map((e) => e.short).join(", ")}: the elements of a repair, in order.
        </p>
      </ResultDetails>
    </div>
  );
}
