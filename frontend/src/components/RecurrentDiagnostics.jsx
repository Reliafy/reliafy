// A repairable model's Diagnostics tab: "Can I trust this model?" as small
// checks titled with their question, the technical name in brackets and a
// one-line verdict (components/model/ModelLayouts.jsx CheckCard), from what
// the fit already returns: the trend tests, the Duane plot of the data, each
// system against the model, the Cramér-von Mises test, the repair test
// (imperfect repair) and the fit statistics.
import Plot from "./Plot.jsx";
import { CheckCard, ChecksGrid } from "./model/ModelLayouts.jsx";
import { FitStatsCard } from "./model/Diagnostics.jsx";
import { DATA_INK, dataPoints, fitLine } from "../plotTheme.js";
import { formatNumber } from "../format.js";
import { cvmCheck, dataText, duanePoints, growingCheck, systemsCheck, trendCheck } from "../recurrentResults.js";
import { xTitle } from "./RecurrentCharts.jsx";

const SMALL = { margin: { t: 6, r: 10, b: 40, l: 54 } };
const pText = (p) => (p < 0.001 ? "p < 0.001" : `p = ${formatNumber(p, { sig: 2 })}`);
const LEGEND = { x: 0.015, xanchor: "left", y: 0.985, yanchor: "top", bgcolor: "rgba(255,255,255,0.85)" };

// "Is the failure rate changing?": the data's MCF against a straight line to
// its end (a constant rate). Bending above the line, failures come faster.
function TrendCheck({ r, name }) {
  const c = trendCheck(r);
  const obs = r.mcf?.observed || {};
  const end = r.end_of_observation ?? obs.x?.[obs.x.length - 1];
  const last = obs.mcf?.[obs.mcf.length - 1];
  const traces = [];
  if (end && last != null) {
    traces.push({ type: "scatter", mode: "lines", x: [0, end], y: [0, last],
                  line: { color: "#9aa0a8", width: 1, dash: "dash" }, hoverinfo: "skip", name: "A constant rate" });
  }
  traces.push(dataPoints({ x: obs.x, y: obs.mcf, mode: "lines+markers", line: { color: DATA_INK, width: 1.25, shape: "hv" },
                           marker: { size: 4, line: { width: 0 } }, name: "The data" }));
  return (
    <CheckCard chart question="Is the failure rate changing?" term="Laplace and MIL-HDBK-189C trend tests"
               tone={c?.tone} verdict={c?.words || "No trend test for this model."}>
      <Plot fill data={traces} download={`${name} — trend`}
            layout={{ ...SMALL, legend: LEGEND, showlegend: true, xaxis: { title: { text: xTitle(r.unit) }, rangemode: "tozero" },
                      yaxis: { title: { text: "Failures per system" }, rangemode: "tozero" } }} />
    </CheckCard>
  );
}

// "Is reliability growing?": the Duane plot, the cumulative MTBF against time
// on log-log axes: rising is growth.
function GrowthCheck({ r, name }) {
  const c = growingCheck(r);
  const d = duanePoints(r);
  const unit = r.unit ? ` (${String(r.unit).toLowerCase()})` : "";
  const traces = [
    dataPoints({ x: d.observed.x, y: d.observed.y, name: "The data", marker: { size: 5, color: DATA_INK } }),
  ];
  if (d.fitted.x.length) traces.push(fitLine({ x: d.fitted.x, y: d.fitted.y, name: "The model" }));
  return (
    <CheckCard chart question="Is reliability growing?" term="Duane plot" verdict={c?.words || null}>
      {d.observed.x.length > 1 ? (
        <Plot fill data={traces} download={`${name} — Duane plot`}
              layout={{ ...SMALL, legend: LEGEND, showlegend: true,
                        xaxis: { type: "log", dtick: "D2", title: { text: `${xTitle(r.unit)}, log scale` } },
                        yaxis: { type: "log", dtick: "D2", title: { text: `Cumulative MTBF${unit}` } } }} />
      ) : <p className="muted-line">Too few failures to draw.</p>}
    </CheckCard>
  );
}

// "Does any system fail more than the model expects?": each system's
// failures against the model's expectation over its own window.
function SystemsCheck({ r }) {
  const c = systemsCheck(r);
  if (!c) return null;
  return (
    <CheckCard question="Does any system fail more than the model expects?" term="martingale residuals"
               verdict={c.words} className="rec-systems"
               footer={<p className="muted-line">Most excess failures first, each over its own window.</p>}>
      <table className="mini-table rec-stats-table">
        <thead><tr><th>System</th><th>Failures</th><th>Expected</th></tr></thead>
        <tbody>
          {c.rows.map((s) => (
            <tr key={s.system}>
              <td>{s.system}</td>
              <td>{formatNumber(s.failures)}</td>
              <td>{formatNumber(s.expected, { sig: 3 })}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </CheckCard>
  );
}

// "Is repair as good as new, or as bad as old?": the likelihood-ratio tests
// of the fit against each kind of repair (imperfect repair).
function RepairCheck({ rt }) {
  if (!rt) return null;
  const rows = [rt.perfect, rt.minimal].filter(Boolean);
  return (
    <CheckCard question="Is repair as good as new, or as bad as old?" term="repair test" verdict={rt.sentence}
               footer={<p className="muted-line">Likelihood-ratio tests at 5%: a kind of repair that can't be ruled out may fit as well.</p>}>
      <dl className="rec-stats-dl">
        {rows.map((h) => (
          <div key={h.hypothesis}>
            <dt>{h.hypothesis === "perfect repair" ? "As good as new" : h.hypothesis === "minimal repair" ? "As bad as old" : h.hypothesis}</dt>
            <dd>{h.rejected ? "ruled out" : "can't be ruled out"} · {pText(h.p_value)}</dd>
          </div>
        ))}
      </dl>
    </CheckCard>
  );
}

export default function RecurrentDiagnostics({ r, name }) {
  const cvm = cvmCheck(r);
  return (
    <ChecksGrid
      className="rec-diag"
      side={
        <>
          {cvm && (
            <CheckCard question="Do the failure times follow the model?" term="Cramér-von Mises" tone={cvm.tone || undefined}
                       verdict={cvm.words} />
          )}
          <RepairCheck rt={r.repair_test} />
          <SystemsCheck r={r} />
          <FitStatsCard gof={r.gof} note={dataText(r) ? `Fitted to ${dataText(r)}.` : null} />
        </>
      }
    >
      <TrendCheck r={r} name={name} />
      <GrowthCheck r={r} name={name} />
    </ChecksGrid>
  );
}
