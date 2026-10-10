import { useEffect, useState } from "react";
import Plot from "./Plot.jsx";
import { ACCENT, REFERENCE } from "../plotTheme.js";
import { rbdProduction } from "../api.js";
import { formatNumber } from "../format.js";
import { boldParts, hasCapacity, pctNear1, productionSentence } from "../rbdCapacity.js";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { graphSignature } from "./RbdValidation.jsx";
import { unitAbbr } from "./rbdModelText.js";
import "./RbdProduction.css";

// Production availability (#122), a section of the Calculator tab for a
// diagram whose blocks carry capacities: the share of the demand the system
// delivers — weighing a partial outage (one inverter of four down) by the
// output it costs — the output lost over a period, and the exact distribution
// of what the system can deliver. The figures are RePyability's; the demand,
// its unit and the period are saved with the diagram.
//
// ``t``: a non-repairable diagram's time to read the capacity at (else the
// diagram's period); a repairable diagram's window, used when it has no
// period of its own. ``onProduction(settings)`` updates the diagram's.

function Field({ label, value, onCommit, width = "7rem", type = "number", placeholder = "" }) {
  const [text, setText] = useState(value ?? "");
  useEffect(() => setText(value ?? ""), [value]);
  const commit = () => {
    if (String(text) !== String(value ?? "")) onCommit(text);
  };
  return (
    <label className="calc-t">
      <span>{label}</span>
      <input
        type={type} min="0" step="any" value={text} placeholder={placeholder} style={{ width }}
        onChange={(e) => setText(e.target.value)} onBlur={commit}
        onKeyDown={(e) => { if (e.key === "Enter") commit(); }}
      />
    </label>
  );
}

export default function RbdProduction({ graph, t = null, onProduction = null }) {
  const show = hasCapacity(graph);
  const sig = show ? graphSignature(graph) + JSON.stringify(graph.production || {}) + String(t) : "";
  const [state, setState] = useState({ sig: null, result: null, error: null });

  useEffect(() => {
    if (!show) return undefined;
    let live = true;
    const timer = window.setTimeout(() => {
      rbdProduction(graph, t)
        .then((r) => live && setState({ sig, result: r.production, error: null }))
        .catch((e) => live && setState({ sig, result: null, error: e.message }));
    }, 250);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [sig]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!show) return null;
  const settings = graph.production || {};
  const repairable = !!graph.repairable;
  const update = (key, raw) => {
    const value = key === "unit" ? String(raw).trim() : raw === "" ? null : Number(raw);
    const next = { ...settings, [key]: value };
    for (const k of Object.keys(next)) if (next[k] == null || next[k] === "" || next[k] === 0) delete next[k];
    onProduction?.(Object.keys(next).length ? next : null);
  };
  const p = state.result;
  const loading = state.sig !== sig;
  const cu = p?.capacity_unit || settings.unit || "";
  const tu = unitAbbr(graph.unit) || (graph.unit || "").toLowerCase();
  const energy = (v) => `${formatNumber(v)}${cu ? ` ${cu}` : ""}${tu ? `·${tu}` : ""}`;
  const amount = (v) => (v == null ? "—" : `${formatNumber(v)}${cu ? ` ${cu}` : ""}`);
  const span = p?.period ? `${formatNumber(p.period.length)}${tu ? ` ${tu}` : ""}` : "";

  const stats = !p ? [] : repairable ? [
    p.period?.lost != null && { label: `Output lost over ${span}`, value: energy(p.period.lost), hint: "from new" },
    p.meets_demand != null && { label: "Demand fully met", value: pctNear1(p.meets_demand), hint: "share of time" },
    { label: "Average output", value: amount(p.mean_capacity) },
    p.shortfall_rate != null && { label: "Average shortfall", value: amount(p.shortfall_rate) },
  ] : [
    p.meets_demand != null && { label: "Demand fully met", value: pctNear1(p.meets_demand), hint: "probability" },
    { label: "Average output", value: amount(p.mean_capacity) },
    { label: "System working", value: pctNear1(p.availability) },
  ];

  const levels = (p?.levels || []).filter((l) => l.capacity != null);
  return (
    <section className="rbd-production" aria-label="Production">
      <div className="rbd-production-head">
        <h3>Production</h3>
        <div className="rbd-production-fields">
          <Field label="Demand" value={settings.demand} onCommit={(v) => update("demand", v)} placeholder="none" />
          <Field label="Unit" type="text" width="5rem" value={settings.unit} placeholder="kW"
                 onCommit={(v) => update("unit", v)} />
          <Field
            label={repairable ? `Period${tu ? ` (${tu})` : ""}` : `At time${tu ? ` (${tu})` : ""}`}
            value={settings.period} placeholder={t != null ? formatNumber(t) : ""}
            onCommit={(v) => update("period", v)}
          />
        </div>
      </div>
      {state.error && !loading && <p className="error" role="alert">{state.error}</p>}
      {p && (
        <div className={loading ? "rbd-production-body stale" : "rbd-production-body"}>
          <ResultSummary
            sentence={boldParts(productionSentence(p, graph.unit)).map(([s, b], i) => (b ? <b key={i}>{s}</b> : s))}
            stats={stats}
          />
          <ResultDetails summary="Capacity distribution and details">
            {levels.length > 1 && (
              <Plot
                download="Capacity distribution"
                data={[{
                  type: "bar",
                  x: levels.map((l) => l.capacity),
                  y: levels.map((l) => l.probability),
                  marker: { color: ACCENT },
                  hovertemplate: `%{x:,.4~g}${cu ? ` ${cu}` : ""}: %{y:.4~%}<extra></extra>`,
                }]}
                layout={{
                  height: 240,
                  bargap: 0.35,
                  xaxis: { title: { text: `What the system can deliver${cu ? ` (${cu})` : ""}` } },
                  yaxis: { title: { text: repairable ? "Share of time" : "Probability" }, tickformat: ".0%", rangemode: "tozero" },
                  shapes: p.demand != null ? [{
                    type: "line", xref: "x", yref: "paper", x0: p.demand, x1: p.demand, y0: 0, y1: 1,
                    line: { color: REFERENCE, width: 1.5, dash: "dash" },
                  }] : [],
                  annotations: p.demand != null ? [{
                    x: p.demand, xref: "x", y: 1, yref: "paper", text: "Demand", showarrow: false,
                    xanchor: "right", yanchor: "top", font: { size: 12 },
                  }] : [],
                  showlegend: false,
                }}
              />
            )}
            <ProductionDetails p={p} cu={cu} />
          </ResultDetails>
        </div>
      )}
    </section>
  );
}

function ProductionDetails({ p, cu }) {
  const rows = [
    p.production_availability != null && ["Production availability", pctNear1(p.production_availability)],
    ["Plain availability (any output)", pctNear1(p.availability)],
    p.period?.production_availability != null && ["Production availability over the period", pctNear1(p.period.production_availability)],
    p.period?.delivered != null && ["Delivered over the period", formatNumber(p.period.delivered)],
  ].filter(Boolean);
  return (
    <>
      <dl className="rs-dl">
        {rows.map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
      <div className="rbd-design-scroll">
        <table className="calc-table rbd-production-levels">
          <thead>
            <tr><th>Delivers{cu ? ` (${cu})` : ""}</th><th>{p.kind === "repairable" ? "Share of time" : "Probability"}</th></tr>
          </thead>
          <tbody>
            {[...p.levels].reverse().map((l, i) => (
              <tr key={i}>
                <td>{l.capacity == null ? "No limit" : formatNumber(l.capacity)}</td>
                <td>{l.probability < 1e-4 ? l.probability.toExponential(2) : `${formatNumber(l.probability * 100, { sig: 4 })}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="rbd-details-p">
        Exact, from each block's capacity and availability: blocks in series pass the least of their capacities,
        blocks in parallel add up. The production availability is the expected share of the demand delivered;
        the plain availability counts any output as up.
      </p>
      {p.uncapped?.length > 0 && (
        <p className="rbd-details-p">Blocks with no capacity, which limit nothing: {p.uncapped.join(", ")}.</p>
      )}
      {(p.notes || []).length > 0 && (
        <ul className="rbd-details-notes">{p.notes.map((n) => <li key={n}>{n}</li>)}</ul>
      )}
    </>
  );
}
