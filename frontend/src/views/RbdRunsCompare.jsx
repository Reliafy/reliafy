import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { compareRbdRuns } from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import ResultSummary from "../components/ui/ResultSummary.jsx";
import Chip from "../components/ui/Chip.jsx";
import Plot from "../components/Plot.jsx";
import { COLORWAY, bandPair, fitLine } from "../plotTheme.js";
import { rollingMean } from "../components/RbdCalculator.jsx";
import { unitInText } from "../components/unitText.js";
import { formatNumber } from "../format.js";
import { availabilityText, compareSummary, runsPath, runtimeText } from "../rbdRuns.js";
import "../components/RbdRuns.css";

const when = (iso) =>
  iso ? new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";

function tint(hex, alpha) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

// Several runs' A(t), each with its band, on one chart (#112): the same
// diagram run again, over another window, or after a change.
function OverlayChart({ runs, unit }) {
  const traces = [];
  let lo = 1;
  let hi = 0;
  runs.forEach((r, i) => {
    const c = r.curve;
    if (!(c?.t?.length > 1)) return;
    const color = COLORWAY[i % COLORWAY.length];
    const mid = rollingMean(c.t, c.availability).y;
    const band = c.lower?.length === c.t.length && c.upper?.length === c.t.length;
    const lower = band ? rollingMean(c.t, c.lower).y : null;
    const upper = band ? rollingMean(c.t, c.upper).y : null;
    // Scaled to the curves: a short run's band can span far more than the
    // differences between runs, and would flatten them.
    for (const v of mid) {
      if (v != null && Number.isFinite(v)) {
        lo = Math.min(lo, v);
        hi = Math.max(hi, v);
      }
    }
    if (band) traces.push(...bandPair(c.t, lower, upper, { fillcolor: tint(color, 0.1) }));
    traces.push(fitLine({
      x: c.t, y: mid, name: `Run ${i + 1}`, line: { color },
      hovertemplate: `Run ${i + 1}<br>t = %{x:,.4~g}${unit ? ` ${unitInText(unit)}` : ""}<br>A(t) = %{y:.5f}<extra></extra>`,
    }));
  });
  if (!traces.length) return null;
  const pad = Math.max((hi - lo) * 0.25, 1e-5);
  return (
    <Plot
      data={traces}
      layout={{
        height: 320,
        xaxis: { title: { text: unit ? `Time (${unit}) · each run's A(t), smoothed` : "Time" } },
        yaxis: { title: { text: "Availability" }, tickformat: ".4~%", range: [Math.max(0, lo - pad), Math.min(1, hi) + pad] },
        showlegend: false,
      }}
    />
  );
}

// Compare simulation runs (#112): the answer, then the runs' curves overlaid,
// then a row per run (its colour is its line's).
export default function RbdRunsCompare() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const ids = (params.get("ids") || "").split(",").filter(Boolean);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const key = ids.join(",");

  useEffect(() => {
    setData(null);
    setError(null);
    if (ids.length < 2) {
      setError("Pick two or more finished runs to compare.");
      return;
    }
    compareRbdRuns(ids).then(setData).catch((err) => setError(err.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const runs = data?.runs || [];
  const sum = compareSummary(runs);
  const names = [...new Set(runs.map((r) => r.rbd_name).filter(Boolean))];
  const unit = runs[0]?.unit || "";
  const u = unit ? ` ${unitInText(unit)}` : "";
  const rbdId = runs.length && runs.every((r) => r.rbd_id === runs[0].rbd_id) ? runs[0].rbd_id : null;

  return (
    <div className="app rbd-runs">
      <PageHeader
        crumbs={[{ label: "RBDs", to: "/rbds" }, { label: "Simulation runs", to: runsPath(rbdId) }]}
        title="Compare runs"
        meta={names.length ? names.join(" · ") : null}
      />
      {error && <div className="card error">{error}</div>}
      {!data && !error && <div className="card empty">Loading…</div>}
      {data && (
        <div className="card">
          {sum ? (
            <ResultSummary
              sentence={
                <>
                  Over their windows, the <b>{sum.count} runs</b> put availability between <b>{sum.low}</b> and{" "}
                  <b>{sum.high}</b>
                  {sum.overlap === true && "; their intervals overlap."}
                  {sum.overlap === false && "; their intervals don't all overlap."}
                  {sum.overlap == null && "."}
                </>
              }
            >
              {data.missing?.length ? `${data.missing.length} run${data.missing.length === 1 ? " isn't" : "s aren't"} shown: not finished, or no longer kept.` : null}
            </ResultSummary>
          ) : (
            <p className="rbd-runs-note">These runs have no simulated figures to compare.</p>
          )}
          <OverlayChart runs={runs} unit={unit} />
          <div className="lib">
            <table className="lib-table rbd-runs-table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Availability over the window</th>
                  <th className="lib-opt">Long run</th>
                  <th className="lib-opt">Window</th>
                  <th className="lib-opt">Replications</th>
                  <th className="lib-opt">Runtime</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r, i) => {
                  const a = availabilityText(r.availability);
                  const ss = r.steady_state_availability;
                  return (
                    <tr key={r.run_id} className="lib-row" onClick={() => navigate(`/rbds/runs/${r.run_id}`)}>
                      <td>
                        <Chip dot={COLORWAY[i % COLORWAY.length]}>Run {i + 1}</Chip>{" "}
                        <span className="lib-date">{when(r.created_at)}</span>
                      </td>
                      <td className="lib-n">
                        {a.value}
                        {a.interval && <span className="rbd-runs-ci"> {a.interval}</span>}
                      </td>
                      <td className="lib-opt lib-n">{ss != null ? `${(ss * 100).toFixed(3)}%` : "—"}</td>
                      <td className="lib-opt lib-n">{r.window != null ? `${formatNumber(r.window)}${u}` : "—"}</td>
                      <td className="lib-opt lib-n">{r.replications != null ? r.replications.toLocaleString() : "—"}</td>
                      <td className="lib-opt lib-n">{runtimeText(r.runtime_s)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
