import { useEffect, useMemo, useRef, useState } from "react";
import Plot from "./Plot.jsx";
import { rbdPhases } from "../api.js";
import { diagramGap } from "../rbdReadiness.js";
import { isNetwork, reliabilityPercent } from "../rbdMission.js";
import { graphSignature } from "./RbdValidation.jsx";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { ACCENT, REFERENCE } from "../plotTheme.js";
import { formatNumber, formatPercent } from "../format.js";
import { unitInText } from "./unitText.js";
import "./RbdMission.css";

// The Calculator tab's "Phased mission" section (#160), under the diagram's
// own results when it has phases: the mission's reliability (exact, or
// simulated and said so), which phase is riskiest, one chart of where the
// missions fail, and the reliability at the end of each phase under Details.
// Worked out when the tab is open and the diagram or its phases change.

const pct = reliabilityPercent;

export default function RbdPhasesResult({ graph, active, name, onEdit }) {
  const phases = graph?.phases;
  const eligible = !!phases?.length && !graph.repairable && !isNetwork(graph) && !diagramGap(graph);
  const sig = useMemo(
    () => JSON.stringify({ g: graphSignature(graph), p: phases || null, c: graph?.ccf_groups || null }),
    [graph, phases]
  );
  const [state, setState] = useState({ sig: null, result: null, error: null, loading: false });
  const latest = useRef(null);

  useEffect(() => {
    if (!active || !eligible || state.sig === sig) return undefined;
    const timer = window.setTimeout(() => {
      latest.current = sig;
      setState((s) => ({ ...s, loading: true }));
      rbdPhases(graph)
        .then((result) => latest.current === sig && setState({ sig, result, error: null, loading: false }))
        .catch((e) => latest.current === sig && setState({ sig, result: null, error: e.message, loading: false }));
    }, 300);
    return () => window.clearTimeout(timer);
    // graph is read through sig.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, eligible, sig]);

  if (!phases?.length) return null;
  if (graph.repairable) {
    return (
      <section className="rbd-mission" aria-label="Phased mission">
        <MissionHead onEdit={onEdit} />
        <p className="muted-line">This diagram's phases apply when it's non-repairable: in a repairable diagram
          failed blocks are repaired, which a phased mission doesn't model.</p>
      </section>
    );
  }
  if (!eligible) return null;
  const { result, error, loading } = state;
  const stale = state.sig !== sig;
  return (
    <section className="rbd-mission" aria-label="Phased mission" aria-busy={loading}>
      <MissionHead onEdit={onEdit} />
      {error && !stale && <p className="rbd-mission-error" role="alert">{error}</p>}
      {!result && !error && <p className="muted-line">Working out the mission…</p>}
      {result && <MissionAnswer result={result} unit={graph.unit} name={name} dim={stale || loading} />}
    </section>
  );
}

function MissionHead({ onEdit }) {
  return (
    <div className="rbd-mission-head">
      <h3>Phased mission</h3>
      {onEdit && (
        <button type="button" className="secondary sm" onClick={onEdit}>Edit phases</button>
      )}
    </div>
  );
}

function MissionAnswer({ result, unit, name, dim }) {
  const u = unit ? ` ${unitInText(unit)}` : "";
  const simulated = result.method === "simulated";
  const iv = result.interval;
  const risky = result.riskiest;
  const rows = result.phases || [];
  const how = simulated
    ? <>, simulated from {iv?.n_samples?.toLocaleString() || "many"} missions
        {iv ? <> ({Math.round((iv.confidence || 0.95) * 100)}% interval {pct(iv.lower)} to {pct(iv.upper)})</> : null}</>
    : ", worked out exactly";
  const sentence = (
    <>
      The mission succeeds with probability <b>{pct(result.reliability)}</b>{how}.
      {risky && rows.length > 1 && (
        <> <b>{risky.name}</b> is the riskiest phase: <b>{formatPercent(risky.failure_probability, { sig: 3 })}</b> of missions fail in it.</>
      )}
    </>
  );
  const stats = [
    { label: "Mission reliability", value: pct(result.reliability) },
    { label: "Mission length", value: `${formatNumber(result.duration)}${u}` },
    risky && rows.length > 1
      ? { label: "Riskiest phase", value: risky.name, hint: `${formatPercent(risky.share, { sig: 2 })} of the mission's failures` }
      : null,
  ];
  // Where the missions fail: one bar per phase, first phase on top.
  const names = rows.map((r) => r.name);
  const traces = [{
    type: "bar",
    orientation: "h",
    y: names,
    x: rows.map((r) => r.failure_probability),
    marker: { color: ACCENT },
    hovertemplate: "%{y}: %{x:.3~%} of missions fail in it<extra></extra>",
  }];
  const chartH = Math.min(360, 70 + 34 * rows.length);
  return (
    <div className={"rbd-mission-body" + (dim ? " is-stale" : "")}>
      <ResultSummary tone="neutral" sentence={sentence} stats={stats} />
      {rows.length > 1 && (
        <div className="rbd-mission-chart">
          <Plot
            data={traces}
            layout={{
              height: chartH,
              showlegend: false,
              margin: { l: 8, r: 16, t: 8, b: 40 },
              xaxis: { title: { text: "Missions that fail in the phase" }, tickformat: ".2~%", rangemode: "tozero" },
              yaxis: { autorange: "reversed", automargin: true, linecolor: REFERENCE },
            }}
            download={`${name || "Mission"} — failures by phase`}
          />
        </div>
      )}
      <ResultDetails summary="Each phase">
        <div className="rbd-avail-imp-scroll">
          <table className="calc-table rbd-mission-table">
            <thead>
              <tr>
                <th>Phase</th>
                <th>Duration{unit ? ` (${unit})` : ""}</th>
                <th>Ends at{unit ? ` (${unit})` : ""}</th>
                <th title="The chance the mission fails in this phase">Fails in it</th>
                <th title="The chance the mission is still going at the phase's end">Reliability at its end</th>
                <th title="Of the missions that reach this phase, the share that fail in it">If reached, fails in it</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.name}>
                  <td className="calc-row-label">
                    {r.name}
                    {(r.not_needed?.length || r.votes?.length) ? (
                      <span className="rbd-mission-needs">
                        {[
                          r.not_needed?.length ? `without ${r.not_needed.join(", ")}` : null,
                          ...(r.votes || []).map((v) => `${v.label} needs ${v.n}`),
                        ].filter(Boolean).join(" · ")}
                      </span>
                    ) : null}
                  </td>
                  <td>{formatNumber(r.duration)}</td>
                  <td>{formatNumber(r.end)}</td>
                  <td>{formatNumber(r.failure_probability)}</td>
                  <td>{pct(r.reliability_at_end)}</td>
                  <td>{r.conditional_failure == null ? "—" : formatNumber(r.conditional_failure)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted-line">
          A block that fails in one phase stays failed in the later ones, so the mission's reliability isn't the
          product of the phases'. {(result.notes || []).join(" ")}
          {result.method_reason ? ` ${result.method_reason}` : ""}
        </p>
      </ResultDetails>
    </div>
  );
}
