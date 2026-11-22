import { useEffect, useMemo, useRef, useState } from "react";
import { rbdRepairAvailability } from "../api.js";
import { diagramGap } from "../rbdReadiness.js";
import { isNetwork, reliabilityPercent } from "../rbdMission.js";
import { graphSignature } from "./RbdValidation.jsx";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import ScrollCue from "./ui/ScrollCue.jsx";
import { formatNumber, formatPercent } from "../format.js";
import { unitInText } from "./unitText.js";
import { repairSpecFromMean, typedRepairs } from "../rbdRepairAvailability.js";
import "./RbdMission.css";

// The Calculator tab's "Availability with repairs" section, under a non-repairable diagram's
// results (the RBD Calculator, a mission's diagram, a diagram built from the tree): how much of
// the time the system is up when each block is repaired after it fails, over a period and in
// the long run, and which blocks drive the downtime. Each block's mean time to repair comes from
// the block, its outage history or its position's maintainability prediction, and says which; a
// block with none is asked for here, never guessed. Worked out on request, then again as the
// times or the period change. ``onNodeData`` (the editor's) keeps typed times on the blocks.

// As a mission reliability is shown: enough decimals to tell 99.7% from 99.97%.
const pct = reliabilityPercent;

export default function RbdRepairAvailability({ graph, rbdId = null, active, onNodeData = null }) {
  const eligible = !!graph && !graph.repairable && !isNetwork(graph) && !diagramGap(graph);
  const [typed, setTyped] = useState({});
  const [period, setPeriod] = useState("");
  const [asked, setAsked] = useState(false);
  const repairs = useMemo(() => typedRepairs(typed), [typed]);
  const periodSent = period !== "" && Number(period) > 0 ? Number(period) : null;
  const sig = useMemo(
    () => JSON.stringify({ g: graphSignature(graph), p: graph?.phases || null, r: repairs, t: periodSent, id: rbdId }),
    [graph, repairs, periodSent, rbdId]
  );
  const [state, setState] = useState({ sig: null, result: null, error: null, loading: false });
  const latest = useRef(null);

  // A different diagram: its own times and period.
  useEffect(() => { setTyped({}); setPeriod(""); setAsked(false); }, [rbdId]);

  useEffect(() => {
    if (!active || !eligible || !asked || state.sig === sig) return undefined;
    const timer = window.setTimeout(() => {
      latest.current = sig;
      setState((s) => ({ ...s, loading: true }));
      rbdRepairAvailability({ graph, rbdId, repairs, period: periodSent })
        .then((result) => latest.current === sig && setState({ sig, result, error: null, loading: false }))
        .catch((e) => latest.current === sig && setState({ sig, result: null, error: e.message, loading: false }));
    }, 400);
    return () => window.clearTimeout(timer);
    // graph, repairs and the period are read through sig.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, eligible, asked, sig]);

  if (!eligible) return null;
  const { result, error, loading } = state;
  const stale = state.sig !== sig;
  const unit = graph.unit || "";
  const periodLabel = result?.period?.basis === "mission" ? "the mission's length" : result?.period?.basis === "year" ? "a year" : "";
  return (
    <section className="rbd-mission rbd-repair-avail" aria-label="Availability with repairs" aria-busy={loading}>
      <div className="rbd-mission-head">
        <h3>Availability with repairs</h3>
        <label className="rbd-repair-period">
          <span>Over</span>
          <input type="number" min="0" step="any" inputMode="decimal" value={period}
                 placeholder={result?.period?.length ? formatNumber(result.period.length, { sig: 4 }) : "a year"}
                 aria-label={`Period${unit ? ` (${unit})` : ""}`} onChange={(e) => setPeriod(e.target.value)} />
          <span>{unit ? unitInText(unit) : ""}</span>
        </label>
      </div>
      <p className="muted-line rbd-repair-purpose">
        Reliability says whether it lasts the mission. This says how much of the time it's up when each block is
        repaired after it fails{periodLabel ? `, over ${periodLabel} unless you set a period` : ""}.
      </p>
      {!asked && (
        <button type="button" className="secondary" onClick={() => setAsked(true)}>Work out availability</button>
      )}
      {asked && error && !stale && <p className="rbd-mission-error" role="alert">{error}</p>}
      {asked && !result && !error && <p className="muted-line">Working out the availability…</p>}
      {result && (
        <div className={"rbd-mission-body" + (stale || loading ? " is-stale" : "")}>
          <AvailabilityAnswer result={result} graph={graph} />
          <RepairTimes result={result} typed={typed} onType={(id, v) => setTyped((t) => ({ ...t, [id]: v }))}
                       onKeep={onNodeData ? () => { onNodeData(keepOnBlocks(result, repairs, graph)); setTyped({}); } : null} />
          <ResultDetails summary="How it's worked out">
            <p className="muted-line">
              {result.kind_words ? `${result.kind_words[0].toUpperCase()}${result.kind_words.slice(1)}. ` : ""}
              Every block is repaired on its own after it fails, and redundancy stays as drawn (parallel paths,
              k-of-n votes and standby groups). {(result.notes || []).join(" ")} {result.bound_note}
            </p>
            {result.achieved_note && <p className="muted-line">{result.achieved_note}</p>}
          </ResultDetails>
        </div>
      )}
    </section>
  );
}

// Typed times kept on their blocks as each one's repair-time model (exponential with that
// mean), saved with the diagram on the next save.
function keepOnBlocks(result, repairs, graph) {
  const out = {};
  for (const r of result.repairs || []) {
    const v = repairs[r.id];
    if (v != null) out[r.id] = { repair: repairSpecFromMean(v, graph.unit, result.repair_unit) };
  }
  return out;
}

function AvailabilityAnswer({ result, graph }) {
  if (result.status === "needs_repairs") {
    return (
      <ResultSummary tone="caveat" sentence={<>{result.answer}</>}>
        Type each one's mean time to repair below.
      </ResultSummary>
    );
  }
  if (result.status === "simulation_only") {
    return <ResultSummary tone="caveat" sentence={<>{result.answer}</>} />;
  }
  const lead = result.achieved || result.inherent || {};
  const top = (result.drivers || [])[0];
  const hours = lead.downtime_hours;
  const down = hours != null
    ? `${formatNumber(hours, { sig: 3 })} hours`
    : lead.downtime != null ? `${formatNumber(lead.downtime, { sig: 3 })} ${unitInText(graph.unit || "")}` : null;
  const period = result.period?.words || "the period";
  const guessed = result.placeholders || [];
  const without = result.without_placeholders;
  const withoutV = without?.period_availability ?? without?.steady_state ?? null;
  const sentence = lead.period_availability != null ? (
    <>
      Available <b>{pct(lead.period_availability)}</b> of the time over {period}
      {down ? <>: about <b>{down}</b> down</> : null}
      {top ? <>, mostly <b>{top.label}</b> ({formatPercent(top.share, { sig: 2 })} of it)</> : null}.
    </>
  ) : lead.steady_state != null ? (
    <>Available <b>{pct(lead.steady_state)}</b> of the time in the long run{top ? <>, mostly down for <b>{top.label}</b></> : null}.</>
  ) : <>{result.answer}</>;
  const stats = [
    lead.period_availability != null ? { label: `Over ${period}`, value: pct(lead.period_availability) } : null,
    { label: "In the long run", value: pct(lead.steady_state) },
    down ? { label: "Down over the period", value: down,
             hint: lead.expected_failures != null ? `${formatNumber(lead.expected_failures, { sig: 3 })} system failures expected` : undefined } : null,
    result.achieved && result.inherent
      ? { label: "Repairs alone", value: pct(result.inherent.period_availability ?? result.inherent.steady_state), hint: "Inherent: no planned work" }
      : null,
  ];
  return (
    <>
      <ResultSummary tone={guessed.length ? "caveat" : "neutral"} sentence={sentence} stats={stats}>
        {guessed.length ? (
          <>
            Not a real figure yet: {guessed.join(", ")} {guessed.length === 1 ? "has" : "have"} no model, so a
            placeholder life stands in.{withoutV != null ? ` With ${guessed.length === 1 ? "it" : "them"} left out: ${pct(withoutV)}.` : ""}
          </>
        ) : null}
      </ResultSummary>
      {(result.drivers || []).length > 0 && (
        <div className="rbd-repair-drivers">
          <h4>What drives the downtime</h4>
          <ol>
            {result.drivers.slice(0, 5).map((d) => (
              <li key={d.id}>
                <span className="rbd-repair-bar" style={{ width: `${Math.max(2, Math.round(d.share * 100))}%` }} aria-hidden="true" />
                <span>{d.label}</span>
                <span className="rbd-repair-share">{formatPercent(d.share, { sig: 2 })}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </>
  );
}

const SOURCE_HINT = {
  typed: "Typed here, for this calculation",
  block: "The block's own repair-time model",
  recorded: "From the outages recorded in the diagram's outage history",
  prediction: "From the maintainability prediction of the position the block stands for",
};

function RepairTimes({ result, typed, onType, onKeep }) {
  const rows = result.repairs || [];
  const ru = result.repair_unit || "hours";
  const anyTyped = rows.some((r) => r.source === "typed");
  return (
    <div className="rbd-repair-times">
      <h4>Repair times</h4>
      <ScrollCue className="rbd-avail-imp-scroll">
        <table className="calc-table rbd-repair-table">
          <thead>
            <tr>
              <th>Block</th>
              <th>Mean time to repair ({ru})</th>
              <th>From</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const missing = r.mttr == null && !r.pinned;
              return (
                <tr key={r.id} className={missing ? "is-missing" : undefined}>
                  <td className="calc-row-label">{r.label}</td>
                  <td>
                    <input type="number" min="0" step="any" inputMode="decimal"
                           aria-label={`${r.label}: mean time to repair (${ru})`}
                           value={typed[r.id] ?? ""}
                           placeholder={r.mttr != null ? formatNumber(r.mttr, { sig: 3 }) : "needed"}
                           onChange={(e) => onType(r.id, e.target.value)} />
                  </td>
                  <td title={SOURCE_HINT[r.source] || ""}>
                    {r.pinned ? "Pinned: needs none"
                      : missing ? <span className="rbd-repair-missing">! None yet</span>
                        : <>{r.source_words}{r.detail ? <span className="rbd-mission-needs">{r.detail}</span> : null}</>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </ScrollCue>
      {anyTyped && onKeep && (
        <p className="muted-line">
          Typed times are for this calculation.{" "}
          <button type="button" className="link" onClick={onKeep}>Keep them on the blocks</button> (saved with the diagram).
        </p>
      )}
    </div>
  );
}
