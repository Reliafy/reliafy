import { useEffect, useMemo, useRef, useState } from "react";
import Plot from "./Plot.jsx";
import Select from "./Select.jsx";
import { TabEmptyState } from "./RbdEmptyState.jsx";
import { rbdNetwork } from "../api.js";
import { networkGap, reliabilityPercent, terminalOptions, terminals, topBlocks } from "../rbdMission.js";
import { graphSignature } from "./RbdValidation.jsx";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { fitLine, pointMarker } from "../plotTheme.js";
import { formatNumber } from "../format.js";
import { unitInText } from "./unitText.js";
import "./RbdMission.css";

// The Calculator tab of a network diagram (#160): an undirected network's
// two-terminal reliability. The terminals are chosen here (Input and Output
// by default); the answer is the chance they stay connected at a time (where
// it's about 90% unless one is given), the mean time until they part, the
// curve over time, and each block's importance under Details. Exact, or
// simulated for a very large network (said so). Worked out when the tab is
// open and the network, its terminals or the time change.

const pct = reliabilityPercent;

export default function RbdNetworkPanel({ graph, active, name, onNetworkChange, onBuild }) {
  const { source, target } = terminals(graph);
  const options = useMemo(() => terminalOptions(graph.nodes), [graph.nodes]);
  const gap = networkGap(graph);
  const [tText, setTText] = useState("");
  const t = tText.trim() === "" ? null : Number(tText);
  const tOk = t == null || (Number.isFinite(t) && t >= 0);
  const sig = useMemo(
    () => JSON.stringify({ g: graphSignature(graph), n: graph.network, t: tOk ? t : null }),
    [graph, t, tOk]
  );
  const [state, setState] = useState({ sig: null, result: null, error: null, loading: false });
  const latest = useRef(null);

  useEffect(() => {
    if (!active || gap || !tOk || state.sig === sig) return undefined;
    const timer = window.setTimeout(() => {
      latest.current = sig;
      setState((s) => ({ ...s, loading: true }));
      rbdNetwork(graph, t)
        .then((result) => latest.current === sig && setState({ sig, result, error: null, loading: false }))
        .catch((e) => latest.current === sig && setState({ sig, result: null, error: e.message, loading: false }));
    }, 350);
    return () => window.clearTimeout(timer);
    // graph and t are read through sig.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, gap, tOk, sig]);

  const unit = graph.unit || "";
  const setTerminal = (key, value) => onNetworkChange?.({ ...terminals(graph), [key]: value });
  const controls = (
    <div className="calc-controls rbd-calc-inputs rbd-network-controls">
      <label className="calc-t">
        <span>From</span>
        <Select value={source} onChange={(v) => setTerminal("source", v)} title="The first terminal"
                options={options.map((o) => ({ ...o, disabled: o.value === target }))} />
      </label>
      <label className="calc-t">
        <span>To</span>
        <Select value={target} onChange={(v) => setTerminal("target", v)} title="The second terminal"
                options={options.map((o) => ({ ...o, disabled: o.value === source }))} />
      </label>
      <label className="calc-t" title="When to read the connection's reliability (blank: where it's about 90%)">
        <span>At t{unit ? ` (${unit})` : ""}</span>
        <input type="number" min="0" step="any" placeholder="auto" value={tText}
               onChange={(e) => setTText(e.target.value)} aria-invalid={!tOk} />
      </label>
    </div>
  );

  if (gap) {
    const labels = new Map(options.map((o) => [o.value, o.label]));
    return (
      <div className="rbd-calc">
        {gap === "not_connected" && controls}
        <TabEmptyState
          title={gap === "no_blocks" ? "Add blocks to build the network" : `Connect ${labels.get(source) || source} to ${labels.get(target) || target}`}
          need={gap === "no_blocks"
            ? "This diagram is a network: blocks are points that can fail, and connections work both ways. Right-click the canvas to add blocks, then connect them between the two terminals."
            : "No path of connections joins the two terminals yet. Connect them through the blocks (either way round), or choose other terminals."}
          action={onBuild ? { label: "Go to the Builder", onClick: onBuild } : null}
        />
      </div>
    );
  }

  const { result, error, loading } = state;
  const stale = state.sig !== sig;
  return (
    <div className="rbd-calc rbd-network" aria-busy={loading}>
      {controls}
      {!tOk && <p className="rbd-mission-error">The time must be a number of 0 or more.</p>}
      {error && !stale && <div className="card error">{error}</div>}
      {!result && !error && <p className="muted-line">Working out the network…</p>}
      {result && <NetworkAnswer result={result} unit={unit} name={name} dim={stale || loading} />}
    </div>
  );
}

function NetworkAnswer({ result, unit, name, dim }) {
  const u = unit ? ` ${unitInText(unit)}` : "";
  const simulated = result.method === "simulated";
  const top = topBlocks(result.importance);
  const sentence = (
    <>
      <b>{result.source.label}</b> and <b>{result.target.label}</b> stay connected
      for <b>{formatNumber(result.t)}{u}</b> with probability <b>{pct(result.reliability)}</b>
      {simulated ? `, simulated from ${result.simulation?.n_samples?.toLocaleString() || "many"} networks` : ", worked out exactly"}.
    </>
  );
  const stats = [
    { label: `Reliability at ${formatNumber(result.t)}${u}`, value: pct(result.reliability) },
    { label: "Mean time until they part", value: result.mttf == null ? "—" : `${formatNumber(result.mttf)}${u}` },
    top.length
      ? {
          label: top.length > 1 ? "Most important blocks" : "Most important block",
          value: top.length > 2 ? `${top.length} blocks tie` : top.map((r) => r.label).join(", "),
          hint: top.length > 2
            ? top.map((r) => r.label).join(", ")
            : "the biggest gain if made more reliable",
        }
      : null,
  ];
  const c = result.curve || {};
  return (
    <div className={"rbd-mission-body" + (dim ? " is-stale" : "")}>
      <ResultSummary tone="neutral" sentence={sentence} stats={stats} />
      {c.t?.length > 1 && (
        <Plot
          data={[
            fitLine({
              x: c.t, y: c.sf, name: "Connected",
              hovertemplate: `t = %{x:,.4~g}${u}<br>P(connected) = %{y:.4~%}<extra></extra>`,
            }),
            { ...pointMarker(), x: [result.t], y: [result.reliability], hoverinfo: "skip" },
          ]}
          layout={{
            height: 280,
            showlegend: false,
            xaxis: { title: { text: unit ? `Time (${unit})` : "Time" } },
            yaxis: { title: { text: "P(terminals connected)" }, range: [0, 1.02], tickformat: ".0%" },
          }}
          download={`${name || "Network"} — connection reliability`}
        />
      )}
      <ResultDetails summary="Importance and details">
        {(result.importance || []).length > 0 && (
          <div className="rbd-avail-imp-scroll">
            <table className="calc-table rbd-mission-table">
              <thead>
                <tr>
                  <th>Block</th>
                  <th title="Birnbaum importance: how much the connection's reliability rises if this block never fails, against if it has failed">Importance</th>
                  <th>Its own reliability</th>
                </tr>
              </thead>
              <tbody>
                {result.importance.map((r) => (
                  <tr key={r.id}>
                    <td className="calc-row-label">{r.label}</td>
                    <td>{formatNumber(r.birnbaum)}</td>
                    <td>{pct(r.reliability)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted-line">
          Read as an undirected network: each block is a point that can fail, and each connection is a link
          that works both ways and never fails ({result.n_blocks} block{result.n_blocks === 1 ? "" : "s"},{" "}
          {result.n_links} link{result.n_links === 1 ? "" : "s"}). Importance is at {formatNumber(result.t)}{u}.
          {" "}{[result.method_reason, ...(result.notes || [])].filter(Boolean).join(" ")}
        </p>
      </ResultDetails>
    </div>
  );
}

// What the block-diagram tabs (Fault tree, Design) show for a network: they
// don't apply, and the answer is on the Calculator tab.
export function NetworkOnlyNote({ what, onCalc }) {
  return (
    <div className="rbd-calc">
      <TabEmptyState
        title={`${what} is for block diagrams`}
        need="This diagram is a network: its result, the chance its two terminals stay connected, is on the Calculator tab."
        action={onCalc ? { label: "Go to the Calculator", onClick: onCalc } : null}
      />
    </div>
  );
}
