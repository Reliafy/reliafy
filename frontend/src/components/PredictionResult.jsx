import Plot from "./Plot.jsx";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { ACCENT, REFERENCE } from "../plotTheme.js";
import {
  csvFileName, factorsText, fmtHours, fmtPerHour, fmtPerMillion, fmtQuantity, fmtReliability, fmtShare, linesCsv,
  paretoBars,
} from "../predictions.js";

// A reliability prediction's results (backend/services/reliability_prediction.py:
// compute): the answer first, the Pareto, the rate per assembly, every line,
// and what the handbook method applies and leaves out. Rendered from the
// stored results alone, so a saved prediction reads as it was computed.
export default function PredictionResult({ results, name = "Reliability prediction" }) {
  if (!results) return null;
  const r = results;
  const rate = r.failure_rate_per_million_hours;
  const none = !rate;
  const t = r.mission_time_hours;
  const counts = r.counts || {};
  const env = r.environment || {};
  const bars = paretoBars(r.pareto?.by_line, 10);
  const byCategory = r.pareto?.by_category || [];
  const assemblies = r.assemblies || [];
  const warnings = r.warnings || [];

  const sentence = none ? (
    <>No line has a handbook part type yet, so there is no failure rate to show.</>
  ) : (
    <>
      The parts count predicts <b>{fmtPerMillion(rate)} failures per million hours</b> ({fmtPerHour(r.failure_rate_per_hour)} per hour):
      an MTBF of <b>{fmtHours(r.mtbf_hours)} hours</b> and a <b>{fmtReliability(r.reliability_at_mission)}</b> chance of no failure
      over {fmtHours(t)} hours, in the {env.name ? `${env.name.toLowerCase()} (${env.code})` : env.code} environment.
    </>
  );

  const chart = bars.length ? {
    data: [{
      type: "bar", orientation: "h",
      y: bars.map((b) => b.label), x: bars.map((b) => b.rate),
      customdata: bars.map((b) => b.share),
      marker: { color: bars.map((b) => (b.other ? REFERENCE : ACCENT)) },
      hovertemplate: "%{y}: %{x:.3g} per million hours (%{customdata:.1%})<extra></extra>",
    }],
    layout: {
      height: 90 + 30 * bars.length,
      margin: { l: 10, r: 20, t: 10, b: 40 },
      xaxis: { title: { text: "Failures per million hours" }, rangemode: "tozero" },
      yaxis: { automargin: true, autorange: "reversed" },
      showlegend: false,
    },
  } : null;

  return (
    <div className="pred-result">
      <ResultSummary
        tone={none || warnings.length ? "caveat" : "neutral"}
        sentence={sentence}
        stats={[
          { label: "Failure rate (per million hours)", value: none ? "—" : fmtPerMillion(rate),
            hint: none ? undefined : `${fmtPerHour(r.failure_rate_per_hour)} per hour` },
          { label: "MTBF", value: none ? "—" : `${fmtHours(r.mtbf_hours)} hours`, hint: "1 ÷ the failure rate" },
          { label: `Reliability over ${fmtHours(t)} hours`, value: fmtReliability(r.reliability_at_mission), hint: "chance of no failure in that time" },
          { label: "Parts counted", value: `${fmtQuantity(counts.parts_assigned)} in ${counts.assigned ?? 0} ${counts.assigned === 1 ? "line" : "lines"}`,
            hint: [
              counts.unassigned ? `${counts.unassigned} ${counts.unassigned === 1 ? "line" : "lines"} with no part type, left out` : "",
              counts.excluded ? `${counts.excluded} not electronic, left out` : "",
            ].filter(Boolean).join("; ") || "every line has a part type" },
        ]}
      >
        Every part in series with a constant failure rate: the lines' rates add up. A handbook estimate for comparing designs, not a
        measure of how the equipment will fail.
      </ResultSummary>

      {r.left_out_note && <p className="hint" role="note">{r.left_out_note}</p>}

      {warnings.length > 0 && (
        <div className="calc-warn" role="status">
          {warnings.map((w, i) => <div key={i}>{w}</div>)}
        </div>
      )}

      {chart && (
        <section className="pred-block">
          <h3>What drives it</h3>
          <div className="pred-pareto">
            <Plot data={chart.data} layout={chart.layout} download={`${name} — Pareto`} />
            <table className="pred-small" aria-label="Failure rate by part category">
              <thead><tr><th>Category</th><th className="num">Lines</th><th className="num">Share</th></tr></thead>
              <tbody>
                {byCategory.map((c) => (
                  <tr key={c.name}>
                    <td>{c.name}</td>
                    <td className="num">{c.lines}</td>
                    <td className="num">{fmtShare(c.share)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {assemblies.length > 0 && (
        <section className="pred-block">
          <h3>By assembly</h3>
          <div className="pred-scroll">
            <table className="lib-table pred-table">
              <thead>
                <tr>
                  <th>Assembly</th><th className="num">Lines</th><th className="num">Parts</th>
                  <th className="num">Failure rate<span className="th-unit">per million hours</span></th>
                  <th className="num">Share</th><th className="num">MTBF<span className="th-unit">hours</span></th>
                </tr>
              </thead>
              <tbody>
                {assemblies.map((a) => (
                  <tr key={a.label || "loose"} className={a.depth ? "pred-sub" : ""}>
                    <td style={{ paddingLeft: `${14 + a.depth * 18}px` }}>{a.name}</td>
                    <td className="num">{a.lines}</td>
                    <td className="num">{fmtQuantity(a.parts)}</td>
                    <td className="num">{fmtPerMillion(a.rate_per_million_hours)}</td>
                    <td className="num">{rate ? fmtShare(a.rate_per_million_hours / rate) : "—"}</td>
                    <td className="num">{fmtHours(a.mtbf_hours)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="hint">An assembly's rate is everything under it, at any depth; the top-level rows add up to the total.</p>
        </section>
      )}

      <section className="pred-block">
        <div className="card-head">
          <h3>Every line</h3>
          <div className="card-head-actions">
            <button type="button" className="secondary sm" onClick={() => downloadCsv(r, name)}>Download as CSV</button>
          </div>
        </div>
        <div className="pred-scroll">
          <table className="lib-table pred-table">
            <thead>
              <tr>
                <th>Part</th><th>Assembly</th><th className="num">Qty</th><th>Handbook part type</th>
                <th className="num" title="The handbook's base failure rate for the part type (λb), or its parts-count generic rate for the environment (λg, environment included), per million hours">Base rate<span className="th-unit">λb or λg, per million hours</span></th>
                <th className="num" title="The handbook's factor for the environment">Environment<span className="th-unit">πE</span></th>
                <th className="num" title="The quality factor: the line's, else the part type's default grade (1, or the lowest grade for a parts-count type)">Quality<span className="th-unit">πQ</span></th>
                <th className="num">Failure rate<span className="th-unit">per million hours</span></th><th className="num">Share</th>
              </tr>
            </thead>
            <tbody>
              {(r.lines || []).map((l, i) => (
                <tr key={i} className={l.assigned ? "" : "pred-unassigned"}>
                  <td>
                    {l.name}
                    {l.reference && <div className="lib-date">{l.reference}</div>}
                  </td>
                  <td className="lib-date">{l.assembly_label || "—"}</td>
                  <td className="num">{fmtQuantity(l.quantity)}</td>
                  <td>
                    {l.assigned ? (
                      <>
                        {l.part_type}
                        {l.section && <div className="lib-date">{l.section}{l.generic_rate ? " · parts count (λg)" : ""}</div>}
                        {l.quality_factor_source === "default" && l.quality_level && (
                          <div className="lib-date">πQ {fmtQuantity(l.quality_factor)}: {l.quality_level.toLowerCase()} (the default)</div>
                        )}
                        {(l.line_warnings || []).map((w, j) => <div key={j} className="muted-line warn">{w}</div>)}
                      </>
                    ) : l.excluded ? <span className="lib-date">Not an electronic part: left out</span>
                      : <span className="lib-date">No handbook part type: left out of the total</span>}
                  </td>
                  <td className="num">{l.assigned ? fmtPerMillion(l.base_rate_per_million_hours) : "—"}</td>
                  <td className="num" title={l.generic_rate ? "Included in the generic rate λg" : undefined}>
                    {l.assigned ? (l.generic_rate ? "in λg" : l.environment_factor == null ? "—" : fmtQuantity(l.environment_factor)) : "—"}
                  </td>
                  <td className="num" title={l.quality_factor_range ? `Handbook range ${l.quality_factor_range[0]}–${l.quality_factor_range[1]}` : undefined}>
                    {l.assigned && l.quality_factor != null ? fmtQuantity(l.quality_factor) : "—"}
                  </td>
                  <td className="num">{l.assigned ? fmtPerMillion(l.rate_per_million_hours) : "—"}</td>
                  <td className="num">{l.assigned ? fmtShare(l.share) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="hint">A line's failure rate is its base rate × the environment factor × its quality factor × its quantity (a parts-count type: its generic rate for the environment × the quality factor × the quantity; a rate you gave: that rate × the quantity).</p>
      </section>

      <ResultDetails summary="How it was worked out">
        <p>{r.method}</p>
        <p>{factorsText(r.factors)}</p>
        {r.factors?.note && <p className="hint">{r.factors.note}</p>}
        {(r.sources || []).map((s) => (
          <div key={s.id} className="pred-source">
            <p><b>{s.name || s.id}</b>{s.edition ? ` (${s.edition})` : ""}.{s.attribution ? ` ${s.attribution}` : ""}</p>
            {(s.caveats || []).length > 0 && (
              <ul className="hint">
                {s.caveats.map((c, i) => <li key={i}>{c}</li>)}
              </ul>
            )}
          </div>
        ))}
      </ResultDetails>
    </div>
  );
}

function downloadCsv(results, name) {
  const blob = new Blob([linesCsv(results)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = csvFileName(name);
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
