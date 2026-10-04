import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Plot from "./Plot.jsx";
import { analyzeRbd } from "../api.js";
import ValidationPanel from "./RbdValidation.jsx";
import CovariatesModal from "./CovariatesModal.jsx";
import { BandControls, BandInterval, BandNote, bandTraces, hasBand } from "./RbdBand.jsx";
import AvailabilityCompare from "./AvailabilityCompare.jsx";
import AvailabilityCosts, { DowntimeSplit } from "./AvailabilityCosts.jsx";
import AvailabilityPolicies from "./AvailabilityPolicies.jsx";
import { precisionNote } from "./availabilityPrecision.js";
import MethodTag from "./MethodTag.jsx";

// Linear interpolation of y at xq on the (x, y) grid (null y = gap).
function interp(x, y, xq) {
  if (!x || !y || xq < x[0] || xq > x[x.length - 1]) return null;
  for (let i = 1; i < x.length; i++) {
    if (xq <= x[i]) {
      const y0 = y[i - 1];
      const y1 = y[i];
      if (y0 == null || y1 == null) return null;
      const x0 = x[i - 1];
      const x1 = x[i];
      const f = x1 === x0 ? 0 : (xq - x0) / (x1 - x0);
      return y0 + f * (y1 - y0);
    }
  }
  return null;
}

const fmt = (v) =>
  v == null
    ? "—"
    : Math.abs(v) >= 1e-4 || v === 0
    ? v.toPrecision(5)
    : v.toExponential(3);

const FUNCS = [
  { id: "sf", label: "Reliability, R(t)" },
  { id: "ff", label: "Unreliability, F(t)" },
];
const NODE_COLORS = ["#0284c7", "#16a34a", "#db2777", "#d97706", "#7c3aed", "#0891b2"];


// "4,200" — a life to four significant figures, with thousands separators.
const fmtLife = (v) =>
  v == null || !Number.isFinite(v)
    ? "—"
    : Math.abs(v) >= 1e-3 || v === 0
    ? Number(v.toPrecision(4)).toLocaleString()
    : v.toExponential(2);
const fmtPctLevel = (v) => `${Number((v * 100).toPrecision(4))}%`;

// The design life (#173): "R ≥ 90% until 4,200 h (95% CI 3,800–4,600)" —
// from new, for a further time past a survived age, or from now.
export function DesignLife({ result }) {
  const dl = result.design_life;
  if (!dl) return null;
  const unit = result.unit ? ` ${result.unit}` : "";
  const iv = result.band?.design_life;
  const level = result.band?.level;
  const lead = dl.from === "now" ? "for the next" : dl.from === "age" ? "for a further" : "until";
  return (
    <div className="rbd-design-life" role="status">
      <span className="rbd-design-life-name">Design life</span>
      {dl.time != null ? (
        <>
          <span>
            R ≥ {fmtPctLevel(dl.target)} {lead}{" "}
            <b className="rbd-design-life-value">{fmtLife(dl.time)}</b>
            {unit}
          </span>
          {iv && level && (iv.lower != null || iv.upper != null) && (
            <span className="muted" title="Confidence interval from the fitted blocks' parameter uncertainty">
              ({Math.round(level * 100)}% CI {fmtLife(iv.lower)}–{iv.upper == null ? "beyond" : fmtLife(iv.upper)})
            </span>
          )}
        </>
      ) : (
        <span>{dl.message}</span>
      )}
    </div>
  );
}

// What "as of now" assumed (#173): the failed and running blocks, and the
// system's reliability now.
function AsOfNote({ result, idToLabel }) {
  const unit = result.unit ? ` ${result.unit}` : "";
  const parts = Object.entries(result.current_state || {}).map(([id, st]) =>
    st.failed ? `${idToLabel[id] || id} failed` : `${idToLabel[id] || id} running ${fmtLife(st.age)}${unit}`
  );
  const failed = result.reliability_now === 0;
  return (
    <div className={"rbd-asof-note" + (failed ? " is-failed" : "")} role="status">
      <b>As of now:</b> {parts.join(" · ")}.{" "}
      {failed
        ? "The system has failed: the failed blocks leave no working path."
        : `Curves, lives and importance run from now (system reliability now ${fmtPctLevel(result.reliability_now ?? 1)}).`}
    </div>
  );
}

// Reliability results (non-repairable RBD): headline MTTF / B-lives, the
// system + per-node R(t)/F(t) curves, importance measures, and the structural
// path/cut sets. Also used by the public read-only view.
export function Results({ result, t, tMax, conditionalAge = 0 }) {
  const x = result.time;
  const [active, setActive] = useState("sf");
  const unit = result.unit;
  const cond = conditionalAge > 0;
  // As of now (#173): the curves, MTTF and B-lives run from now.
  const now = !!result.current_state;
  const sLabel = `${conditionalAge}${unit ? ` ${unit}` : ""}`;
  // When conditioning, the x-axis is additional time beyond the survived age s.
  const tLabel = now
    ? `time from now${unit ? ` (${unit})` : ""}`
    : cond
    ? `additional time${unit ? ` (${unit})` : ""}`
    : unit
    ? `t (${unit})`
    : "t";
  const baseLabel = FUNCS.find((f) => f.id === active)?.label || active;
  const activeLabel = cond
    ? baseLabel.replace("R(t)", `R(t | ${sLabel})`).replace("F(t)", `F(t | ${sLabel})`)
    : baseLabel;

  const idToLabel = useMemo(
    () => Object.fromEntries((result.nodes || []).map((n) => [n.id, n.label])),
    [result.nodes]
  );

  const sysY = active === "sf" ? result.system.sf : result.system.ff;
  const sysAtT = t == null ? null : interp(x, sysY, Number(t));
  // Confidence band (#103), when asked for: shaded under the system curve.
  const band = result.band || null;
  const bandAtT =
    hasBand(band) && t != null
      ? (active === "sf"
          ? { lower: interp(x, band.sf_lower, Number(t)), upper: interp(x, band.sf_upper, Number(t)) }
          : { lower: 1 - interp(x, band.sf_upper, Number(t)), upper: 1 - interp(x, band.sf_lower, Number(t)) })
      : null;

  // System curve (bold) plus a faint curve per node.
  const traces = [
    ...bandTraces(band, x, active),
    {
      x,
      y: sysY,
      mode: "lines",
      line: { color: "#0f172a", width: 3 },
      name: "System",
      type: "scatter",
      connectgaps: false,
    },
  ];
  (result.nodes || []).forEach((n, i) => {
    const y = active === "sf" ? n.sf : n.sf.map((v) => (v == null ? null : 1 - v));
    traces.push({
      x,
      y,
      mode: "lines",
      line: { color: NODE_COLORS[i % NODE_COLORS.length], width: 1.25, dash: "dot" },
      name: n.label,
      type: "scatter",
      connectgaps: false,
      opacity: 0.7,
    });
  });
  if (sysAtT != null) {
    traces.push({
      x: [Number(t)],
      y: [sysAtT],
      mode: "markers",
      marker: { color: "#0f172a", size: 9, line: { color: "#fff", width: 1 } },
      type: "scatter",
      showlegend: false,
      hoverinfo: "y",
    });
  }

  const layout = {
    autosize: true,
    height: 440,
    margin: { l: 64, r: 20, t: 20, b: 70 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "#ffffff",
    font: { color: "#334155", family: "Inter, system-ui, sans-serif" },
    showlegend: true,
    legend: { orientation: "h", y: -0.18 },
    xaxis: {
      title: { text: tLabel, standoff: 12 },
      automargin: true,
      gridcolor: "#e2e8f0",
      linecolor: "#cbd5e1",
      range: [0, tMax != null ? Number(tMax) : x[x.length - 1]],
      zeroline: false,
    },
    yaxis: {
      title: { text: activeLabel, standoff: 12 },
      automargin: true,
      gridcolor: "#e2e8f0",
      linecolor: "#cbd5e1",
      range: [0, 1.02],
      zeroline: false,
    },
    shapes:
      t == null
        ? []
        : [
            {
              type: "line",
              x0: Number(t),
              x1: Number(t),
              yref: "paper",
              y0: 0,
              y1: 1,
              line: { color: "#94a3b8", width: 1, dash: "dot" },
            },
          ],
  };

  const importance = result.importance || {};
  const impNodes = Object.keys(importance.birnbaum || {});

  return (
    <div className="calc">
      {result.ccf && result.ccf.groups?.length > 0 && (
        <div className="rbd-ccf-impact">
          <span>Common cause cuts system reliability at the design point from</span>
          <span className="drop">{(result.ccf.reliability_without * 100).toFixed(1)}%</span>
          <span>to</span>
          <span className="drop">{(result.ccf.reliability_with * 100).toFixed(1)}%</span>
          <span className="muted-line" style={{ margin: 0 }}>
            ({result.ccf.groups.map((g) => `${g.members.join(" & ")} β=${g.beta}`).join("; ")}, at t={fmt(result.ccf.time)}{unit ? ` ${unit}` : ""})
          </span>
        </div>
      )}
      {now && <AsOfNote result={result} idToLabel={idToLabel} />}
      <DesignLife result={result} />
      <div className="params">
        <div className="stat">
          <div className="value">{fmt(result.mttf)}</div>
          <div className="name">
            {now ? "Mean remaining life" : cond ? "Mean residual life" : "MTTF"}
            {unit ? ` (${unit})` : ""}
          </div>
          <BandInterval band={band} interval={band?.mttf} />
        </div>
        {result.blife && (
          <>
            <div className="stat">
              <div className="value">{fmt(result.blife.b10)}</div>
              <div className="name" title={`Time${now ? " from now" : ""} by which 10% of systems have failed`}>
                B10 life{now ? " from now" : ""}{unit ? ` (${unit})` : ""}
              </div>
              <BandInterval band={band} interval={band?.blife?.b10} />
            </div>
            <div className="stat">
              <div className="value">{fmt(result.blife.b50)}</div>
              <div className="name" title={`Median system life${now ? " from now" : ""} (50% failed)`}>
                B50 life{now ? " from now" : ""}{unit ? ` (${unit})` : ""}
              </div>
              <BandInterval band={band} interval={band?.blife?.b50} />
            </div>
          </>
        )}
        <div className="stat">
          <div className="value">{fmt(sysAtT)}</div>
          <div className="name">
            {active === "sf" ? "R" : "F"}(t={t ?? "—"}
            {cond ? ` | ${sLabel}` : ""})
          </div>
          <BandInterval band={band} interval={bandAtT} />
        </div>
        <div className="stat">
          <div className="value">{(result.nodes || []).length}</div>
          <div className="name">components</div>
        </div>
      </div>

      <div className="calc-controls">
        <div className="seg">
          {FUNCS.map((f) => (
            <button
              key={f.id}
              className={"seg-btn" + (active === f.id ? " active" : "")}
              onClick={() => setActive(f.id)}
              title={f.label}
            >
              {f.id === "sf" ? "R(t)" : "F(t)"}
            </button>
          ))}
        </div>
      </div>

      <Plot
        data={traces}
        layout={layout}
        config={{ displayModeBar: true, responsive: true }}
        style={{ width: "100%" }}
        useResizeHandler
      />
      <BandNote band={band} />

      {impNodes.length > 0 && (
        <div className="rbd-importance">
          <div className="rbd-section-head">
            Importance at t = {fmt(importance.time)}
            {unit ? ` ${unit}` : ""}
          </div>
          {/* Scrolls sideways on a phone rather than widening the page,
              as the availability table already does. */}
          <div className="rbd-avail-imp-scroll">
          <table className="calc-table">
            <thead>
              <tr>
                <th>Component</th>
                <th title="Birnbaum importance — sensitivity of system reliability to this component">Birnbaum</th>
                <th title={`Fussell-Vesely — fraction of system unreliability this component contributes to${importance.fussell_vesely_basis ? ` (from ${importance.fussell_vesely_basis}; this diagram has too many cut sets to derive them all)` : ""}`}>
                  F-V{importance.fussell_vesely_basis ? "*" : ""}
                </th>
                <th title="Risk Achievement Worth — how much worse the system gets if this component fails">RAW</th>
                <th title="Risk Reduction Worth — how much better the system gets if this component were perfect">RRW</th>
                <th title="Criticality importance (failure-oriented) — the share of system failures this component accounts for">Crit.</th>
                <th title="Improvement potential — gain available from perfecting this component">Improv.</th>
              </tr>
            </thead>
            <tbody>
              {impNodes.map((id) => (
                <tr key={id}>
                  <td className="calc-row-label">{idToLabel[id] || id}</td>
                  <td>{fmt(importance.birnbaum?.[id])}</td>
                  <td>{fmt(importance.fussell_vesely?.[id])}</td>
                  <td>{fmt(importance.risk_achievement_worth?.[id])}</td>
                  <td>{fmt(importance.risk_reduction_worth?.[id])}</td>
                  <td>{fmt(importance.criticality?.[id])}</td>
                  <td>{fmt(importance.improvement_potential?.[id])}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}

      <div className="rbd-sets">
        <div className="rbd-set">
          <div className="rbd-section-head">
            Minimal path sets
            {result.structure.n_min_path_sets > result.structure.min_path_sets.length &&
              ` — shortest ${result.structure.min_path_sets.length.toLocaleString()} of ${result.structure.n_min_path_sets.toLocaleString()}`}
          </div>
          <ul>
            {result.structure.min_path_sets.map((s, i) => (
              <li key={i}>{s.join(" · ")}</li>
            ))}
          </ul>
        </div>
        <div className="rbd-set">
          <div className="rbd-section-head">
            Minimal cut sets
            {result.structure.cut_sets_complete === false &&
              ` — up to ${result.structure.cut_sets_max_order} blocks (too many to derive them all)`}
          </div>
          <ul>
            {result.structure.min_cut_sets.map((s, i) => (
              <li key={i}>{s.join(" · ")}</li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

// RBD calculator tab. Validation is performed on the Builder tab; this tab
// consumes the shared result (``validation`` + ``stale``) and only offers the
// reliability calculation once the diagram is valid (non-analytic nodes such
// as standby are solved by simulation).
// Availability results for a repairable RBD: the headline uptime, up/down-time
// figures, and each component's share of downtime (what drags uptime down).
// Also used by the public read-only view.
const fmtPct = (v) => (v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(1)}%`);
const fmt3 = (v) =>
  v == null || !Number.isFinite(v) ? "—" : Math.abs(v) >= 1e-3 || v === 0 ? Number(v.toPrecision(3)).toString() : v.toExponential(2);

// Per-block importance columns for a repairable diagram. Birnbaum / share of
// downtime / RAW are exact, at the blocks' long-run availabilities; the two
// "drives" columns are observed in the availability simulation.
//
// "Share of downtime" is the failure-oriented criticality (Birnbaum × block
// unavailability ÷ system unavailability). RePyability's own
// criticality_importance is success-oriented (Birnbaum × availability ÷ system
// availability), which is exactly 1 for every series block, so it can't rank
// them — deliberately not shown here.
const IMP_COLS = [
  { key: "birnbaum", label: "Birnbaum", fmt: fmt3,
    help: "How much system availability changes per unit change in this block's availability." },
  { key: "crit", label: "Share of downtime", fmt: fmtPct,
    help: "Long-run share of system downtime caused by this block (failure-oriented criticality: Birnbaum × block unavailability ÷ system unavailability). Exact, at the long-run availabilities." },
  { key: "risk_achievement_worth", label: "RAW", fmt: fmt3,
    help: "Risk achievement worth: how many times worse system unavailability gets while this block is down." },
  { key: "failure_criticality", label: "Drives trips", fmt: fmtPct,
    help: "Share of simulated system failures this block's failure triggered." },
  { key: "restoration_criticality", label: "Drives restoration", fmt: fmtPct,
    help: "Share of simulated system restorations this block's repair completed." },
];

// The columns only the simulation fills.
const SIM_COLS = new Set(["failure_criticality", "restoration_criticality"]);

function importanceRows(result) {
  const imp = result.importance || {};
  const crit = result.criticality || {};
  const ids = Object.keys(imp);
  const rows = ids.map((id) => {
    const i = imp[id] || {};
    const c = crit[id] || {};
    return {
      id,
      label: i.label || c.label || id,
      pinned: i.pinned || null,
      birnbaum: i.birnbaum,
      // Never fall back to the library's success-oriented criticality: under
      // this column's name it would show 100% for every series block.
      crit: i.unavailability_criticality,
      risk_achievement_worth: i.risk_achievement_worth,
      // No simulation entry means the block never tripped/restored the system.
      failure_criticality: crit[id] ? c.failure_criticality : null,
      restoration_criticality: crit[id] ? c.restoration_criticality : null,
    };
  });
  rows.sort((a, b) => (b.crit ?? -1) - (a.crit ?? -1) || String(a.label).localeCompare(String(b.label)));
  return rows;
}

const fmtTime = (v) => (v == null || !Number.isFinite(v) ? "—" : Number(v.toPrecision(4)).toLocaleString());
const fmtCount = (v) =>
  v == null || !Number.isFinite(v) ? "—" : v >= 100 ? Math.round(v).toLocaleString() : Number(v.toPrecision(3)).toString();
const fmtMoney = (v) =>
  v == null || !Number.isFinite(v) ? "—" : v >= 100 ? Math.round(v).toLocaleString() : Number(v.toPrecision(3)).toLocaleString();

function DowntimeBars({ rows, title, note }) {
  if (!rows?.length) return null;
  return (
    <div className="rbd-avail-nodes">
      <div className="ds-section-h">{title}</div>
      {rows.map((n) => (
        <div className="rbd-avail-bar" key={n.id}>
          <span className="rbd-avail-bar-label" title={n.label}>{n.label}</span>
          <span className="rbd-avail-bar-track">
            <span className="rbd-avail-bar-fill" style={{ width: `${Math.round((n.share || 0) * 100)}%` }} />
          </span>
          <span className="rbd-avail-bar-pct">{((n.share || 0) * 100).toFixed(1)}%</span>
        </div>
      ))}
      {note && <p className="muted-line" style={{ margin: 0 }}>{note}</p>}
    </div>
  );
}

// The exact figures over time (#154), from new or from the current state
// (#155): the window's figures, each labelled with its method, and A(t).
function ExactSection({ exact, steady, unit, onCompute, computing }) {
  const u = unit ? ` ${unit}` : "";
  const pct = (v) => (v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(3)}%`);
  if (!exact) return null;
  if (exact.status === "on_request") {
    return (
      <div className="card note rbd-exact-note" role="status">
        <p style={{ margin: 0 }}>{exact.message}</p>
        {onCompute && (
          <div className="rbd-upgrade-actions">
            <button type="button" onClick={onCompute} disabled={computing}>
              {computing ? "Computing…" : "Compute exact figures"}
            </button>
          </div>
        )}
      </div>
    );
  }
  if (exact.status !== "ok") {
    return (
      <div className="card note rbd-exact-note" role="status">
        <p style={{ margin: 0 }}>{exact.message}</p>
      </div>
    );
  }
  const m = exact.method || {};
  const fromNow = exact.from === "now";
  const span = `${fmtTime(exact.window)}${u}`;
  const c = exact.curve || {};
  const traces = [
    {
      x: c.t, y: c.availability, mode: "lines", type: "scatter",
      line: { color: "#2f6df6", width: 2 }, name: "A(t)",
      hovertemplate: `t = %{x:.4g}${u}<br>A(t) = %{y:.5f}<extra></extra>`,
    },
  ];
  const shapes = steady != null && c.t?.length
    ? [{
        type: "line", xref: "x", yref: "y", x0: c.t[0], x1: c.t[c.t.length - 1], y0: steady, y1: steady,
        line: { color: "#94a3b8", width: 1, dash: "dash" },
      }]
    : [];
  const routes = Object.entries(exact.routes || {});
  return (
    <div className="rbd-exact">
      <div className="ds-section-h">
        {fromNow ? `Over the next ${span}, from now` : `Over the first ${span}, from new`}
        <MethodTag method={m.curve} />
      </div>
      <div className="rbd-avail-metrics rbd-exact-metrics">
        <div className="alt-metric accent">
          <span className="k">Mission availability <MethodTag method={m.mission_availability} /></span>
          <span className="v">{pct(exact.mission_availability)}</span>
        </div>
        {fromNow && (
          <div className="alt-metric" title={`Lowest point of A(t), at t = ${fmtTime(exact.availability_min_at)}${u}`}>
            <span className="k">Lowest A(t) <MethodTag method={m.curve} /></span>
            <span className="v">{pct(exact.availability_min)}</span>
          </div>
        )}
        <div className="alt-metric">
          <span className="k">Expected failures <MethodTag method={m.expected_failures} /></span>
          <span className="v">{fmtCount(exact.expected_failures)}</span>
        </div>
        <div className="alt-metric" title="System failures plus planned outages (maintenance and tests that take the system down)">
          <span className="k">Expected outages <MethodTag method={m.expected_outages} /></span>
          <span className="v">{fmtCount(exact.expected_outages)}</span>
        </div>
        <div className="alt-metric">
          <span className="k">Expected downtime <MethodTag method={m.downtime} /></span>
          <span className="v">{fmtTime(exact.downtime)}{u}</span>
        </div>
        {exact.cost && (
          <div className="alt-metric" title="Expected running cost over the window (repairs, maintenance, tests and downtime), excluding purchase">
            <span className="k">Expected cost <MethodTag method={m.cost} /></span>
            <span className="v">{fmtMoney(exact.cost.mean)}</span>
          </div>
        )}
      </div>
      {c.t?.length > 1 && (
        <Plot
          data={traces}
          layout={{
            autosize: true, height: 280, margin: { l: 56, r: 16, t: 12, b: 44 },
            paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "#ffffff",
            xaxis: { title: unit ? `Time ${fromNow ? "from now" : "from new"} (${unit})` : "Time", gridcolor: "#eef1f5", zeroline: false },
            yaxis: { title: "Availability A(t)", gridcolor: "#eef1f5", rangemode: fromNow ? "tozero" : "normal" },
            shapes, showlegend: false,
          }}
          useResizeHandler style={{ width: "100%" }} config={{ displayModeBar: false, responsive: true }}
        />
      )}
      <DowntimeBars
        rows={exact.per_node}
        title="Block downtime over the window"
        note={
          "Each block's share of the blocks' own expected downtime. A redundant block can be down " +
          "without taking the system down: its share of the system's downtime is under Block importance."
        }
      />
      <p className="muted-line" style={{ margin: 0 }}>
        Computed {fromNow ? "from the blocks' states now" : "with every block new at the start"}, with no
        simulation{steady != null ? "; the dashed line is the long-run availability" : ""}.
        {exact.cost_note ? ` No exact cost: ${exact.cost_note}` : ""}
      </p>
      {routes.length > 0 && (
        <details className="rbd-routes">
          <summary>How each figure is computed</summary>
          <ul>
            {routes.map(([k, r]) => (
              <li key={k}>
                <code>{k}</code> <MethodTag method={r.route} /> — {r.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

// Shown in place of the simulation's results when none has been run: what it
// adds over the exact figures, and the way to run it (Pro, or credits).
function SimulationOffer({ canSimulate, onSimulate, simulating, graph }) {
  const [upgrade, setUpgrade] = useState(false);
  if (!onSimulate) return null;
  return (
    <div className="card rbd-sim-offer">
      <div className="ds-section-h" style={{ marginTop: 0 }}>Simulation</div>
      <p style={{ margin: "4px 0 0" }}>
        The figures above are exact. A Monte-Carlo simulation adds the spread of outcomes: the chance of no
        outage, percentiles, criticality indices (which block trips the system, which restores it) and a
        confidence band.
      </p>
      <div className="rbd-upgrade-actions">
        <button
          type="button"
          className={canSimulate ? "" : "secondary"}
          disabled={simulating}
          onClick={() => (canSimulate ? onSimulate() : setUpgrade(true))}
        >
          {simulating ? "Simulating…" : canSimulate ? "Run simulation" : "Run simulation (Pro)"}
        </button>
      </div>
      {upgrade && !canSimulate && <AvailabilityUpgrade graph={graph} />}
    </div>
  );
}

export function AvailabilityView({ result, unit, graph = null, onSimulate = null, onCompute = null, busy = null }) {
  const u = unit ? ` ${unit}` : "";
  const pct = (v) => (v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(3)}%`);
  // A result saved before #154 is a simulation result (no has_simulation flag).
  const hasSim = result.has_simulation !== false;
  const exact = result.exact || null;
  const exactOk = exact?.status === "ok";
  // No exact long-run value (limited repair crews for wear-out lives, say):
  // the headline is the simulated availability over the window.
  const simulatedOnly = result.availability_basis === "simulation";
  const a = simulatedOnly ? result.precision?.window_availability : result.steady_state_availability;
  const curve = hasSim ? result.curve : null;
  const basis = result.figures_basis || {};
  const basisNote = (k) =>
    basis[k] === "exact"
      ? "Exact steady-state value"
      : `Simulation estimate over ${fmt(result.t_simulation)}${u}`;
  const hasBand = curve && curve.lower?.length === curve.t?.length && curve.upper?.length === curve.t?.length;
  // The exact A(t) over the simulated one, when both cover the same window from the same start.
  const sameWindow =
    exactOk && curve && Math.abs((exact.window || 0) - (result.t_simulation || 0)) <= 1e-9 * (exact.window || 1);
  const curveTraces = !curve
    ? []
    : [
        ...(hasBand
          ? [
              { x: curve.t, y: curve.lower, mode: "lines", type: "scatter", line: { width: 0 }, hoverinfo: "skip", showlegend: false },
              {
                x: curve.t, y: curve.upper, mode: "lines", type: "scatter", line: { width: 0 },
                fill: "tonexty", fillcolor: "rgba(47, 109, 246, 0.15)", hoverinfo: "skip", showlegend: false,
              },
            ]
          : []),
        { x: curve.t, y: curve.availability, mode: "lines", type: "scatter", line: { color: "#2f6df6", width: 2 }, name: "Simulated" },
        ...(sameWindow
          ? [{ x: exact.curve.t, y: exact.curve.availability, mode: "lines", type: "scatter", line: { color: "#0f172a", width: 1, dash: "dot" }, name: "Exact" }]
          : []),
      ];
  const blocks = importanceRows(result);
  // The simulation's columns only when it ran.
  const impCols = hasSim ? IMP_COLS : IMP_COLS.filter((c) => !SIM_COLS.has(c.key));
  const simPer = hasSim ? result.per_node || [] : [];

  return (
    <div className="rbd-avail">
      <div className="rbd-avail-hero">
        <div className="rbd-avail-big">{pct(a)}</div>
        <div className="rbd-avail-cap">
          {simulatedOnly
            ? `Availability over the ${Number(result.t_simulation.toPrecision(5)).toLocaleString()}${u} window (simulated — no exact long-run value with this maintenance)`
            : <>Steady-state availability (uptime) <MethodTag method={exact?.method?.steady_state || (basis.mean_up_time === "exact" ? "exact" : null)} /></>}
        </div>
      </div>
      <div className="rbd-avail-metrics">
        <div className="alt-metric"><span className="k">Unavailability</span><span className="v">{pct(simulatedOnly ? (a == null ? null : 1 - a) : result.unavailability)}</span></div>
        <div className="alt-metric" title={basisNote("mean_up_time")}><span className="k">Mean up time</span><span className="v">{fmt(result.mean_up_time)}{u}</span></div>
        <div className="alt-metric" title={basisNote("mean_down_time")}><span className="k">Mean down time</span><span className="v">{fmt(result.mean_down_time)}{u}</span></div>
        <div className="alt-metric" title={basisNote("failure_frequency")}><span className="k">Failure frequency</span><span className="v">{fmt(result.failure_frequency)}{u ? ` /${unit}` : ""}</span></div>
      </div>

      <ExactSection
        exact={exact}
        steady={simulatedOnly ? null : result.steady_state_availability}
        unit={unit}
        onCompute={onCompute}
        computing={busy === "exact"}
      />

      {!exactOk && <DowntimeBars rows={simPer} title="What drives downtime" />}

      <DowntimeSplit result={result} unit={unit} />
      <AvailabilityCosts result={result} unit={unit} />
      <AvailabilityPolicies result={result} />

      {blocks.length > 0 && (
        <div className="rbd-avail-imp">
          <div className="ds-section-h">Block importance</div>
          <div className="rbd-avail-imp-scroll">
            <table className="calc-table">
              <thead>
                <tr>
                  <th>Block</th>
                  {impCols.map((c) => (
                    <th key={c.key} title={c.help}>{c.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {blocks.map((b) => (
                  <tr key={b.id}>
                    <td className="calc-row-label">
                      {b.label}
                      {b.pinned && <span className="rbd-avail-pin">pinned {b.pinned}</span>}
                    </td>
                    {impCols.map((c) => (
                      <td key={c.key}>{c.fmt(b[c.key])}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="rbd-avail-legend">
            {impCols.map((c) => (
              <li key={c.key}><b>{c.label}</b> — {c.help}</li>
            ))}
          </ul>
        </div>
      )}

      {hasSim ? (
        <div className="rbd-sim">
          <div className="ds-section-h">
            Simulation{result.current_state ? " from now" : ""} <MethodTag method="simulated" />
          </div>
          {exactOk && <DowntimeBars rows={simPer} title="Simulated share of downtime" />}
          {curve && curve.t?.length > 1 && (
            <Plot
              data={curveTraces}
              layout={{
                autosize: true, height: 300, margin: { l: 56, r: 16, t: 16, b: 44 },
                paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "#ffffff",
                xaxis: { title: unit ? `Time (${unit})` : "Time", gridcolor: "#eef1f5", zeroline: false },
                yaxis: { title: "Availability", gridcolor: "#eef1f5", rangemode: "tozero" },
                showlegend: sameWindow, legend: { orientation: "h", y: -0.25 },
              }}
              useResizeHandler style={{ width: "100%" }} config={{ displayModeBar: false, responsive: true }}
            />
          )}
          <p className="muted-line" style={{ margin: 0 }}>
            Availability curve estimated by {result.n_simulations?.toLocaleString()} Monte-Carlo
            replications{result.precision?.antithetic ? " (in antithetic pairs)" : ""} over {fmt(result.t_simulation)}{u}
            {hasBand ? `, with a ${Math.round((curve.confidence || 0.95) * 100)}% confidence band` : ""}
            {sameWindow ? "; the dotted line is the exact A(t)" : ""}.
            {precisionNote(result)}
            {result.horizon_shortened && " The window was shortened to keep the simulation quick; the long-run figures don't depend on it."}
            {basis.mean_up_time === "exact" && " Mean up/down time and failure frequency are exact steady-state values."}
          </p>
        </div>
      ) : (
        <SimulationOffer
          canSimulate={!!result.can_simulate}
          onSimulate={onSimulate}
          simulating={busy === "simulate"}
          graph={graph}
        />
      )}
    </div>
  );
}


// "Saved result from 3 Oct 2026" for a cached availability result.
export function savedOn(iso) {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return "Saved result";
  return `Saved result from ${d.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  })}`;
}

// Shown instead of an error when a free user calculates a repairable diagram
// that has no saved result: availability simulation is a paid feature.
function AvailabilityUpgrade({ graph }) {
  const exportDiagram = () => {
    // RbdBuilder listens for this event and downloads the saved diagram as a
    // standalone SurPyval + RePyability script (free for every viewer).
    window.dispatchEvent(new CustomEvent("reliafy:rbd-export", { detail: { graph } }));
  };
  return (
    <div className="card note rbd-upgrade" role="status">
      <p>
        <b>The simulation runs thousands of histories — it's part of Pro.</b>{" "}
        Subscribe to Pro or buy AI credits to run it here.
      </p>
      <div className="rbd-upgrade-actions">
        <Link className="cta cta-solid" to="/billing">Upgrade to Pro</Link>
        <button type="button" className="linkish" onClick={exportDiagram}>
          Download and run it yourself
        </button>
      </div>
    </div>
  );
}

// "As of now": each block's state now. A repairable block can be down (with
// how long it has been in repair, #155); a non-repairable one has failed for
// good (#173). Either can have run some time since new.
function AsOfPanel({ blocks, states, onChange, unitLabel, repairable }) {
  const outMode = repairable ? "down" : "failed";
  return (
    <div className="rbd-asof-panel">
      <p className="hint" style={{ margin: 0 }}>
        {repairable
          ? "Mark blocks that are down now (with how long they've been in repair) or set how long " +
            "they've been running since new or their last renewal. Blocks left as New start new."
          : "Mark blocks that have failed, or set how long they've been running. Results then run " +
            "from now: the remaining life. Blocks left as New start new."}
      </p>
      <div className="rbd-avail-imp-scroll">
        <table className="calc-table rbd-asof-table">
          <thead>
            <tr>
              <th>Block</th>
              <th>State now</th>
              <th>{repairable ? "Time" : "Running for"}{unitLabel}</th>
            </tr>
          </thead>
          <tbody>
            {blocks.map((b) => {
              const st = states[b.id] || { mode: "new", value: "" };
              // A state set before the diagram changed kind reads as this kind's.
              const mode = st.mode === "down" || st.mode === "failed" ? outMode : st.mode;
              const timed = mode === "age" || (repairable && mode === "down");
              return (
                <tr key={b.id} className={mode === outMode ? "is-down" : ""}>
                  <td className="calc-row-label">{b.label}</td>
                  <td>
                    <select
                      value={mode}
                      aria-label={`${b.label} state now`}
                      onChange={(e) => onChange(b.id, { mode: e.target.value })}
                    >
                      <option value="new">New</option>
                      <option value="age">Running</option>
                      <option value={outMode}>{repairable ? "Down" : "Failed"}</option>
                    </select>
                  </td>
                  <td>
                    {!timed ? (
                      <span className="muted">—</span>
                    ) : (
                      <input
                        type="number"
                        min="0"
                        step="any"
                        value={st.value}
                        placeholder={mode === "down" ? "in repair for" : "age"}
                        aria-label={mode === "down" ? `${b.label}: time into its repair` : `${b.label}: age`}
                        onChange={(e) => onChange(b.id, { value: e.target.value })}
                      />
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function RbdCalculator({ graph, validation, stale, rbdId = null }) {
  const [result, setResult] = useState(null);
  const [phase, setPhase] = useState("idle"); // idle | calculating | error
  const [error, setError] = useState(null);
  const [needsPro, setNeedsPro] = useState(false); // 402 pro_required (availability)
  const [tMax, setTMax] = useState(""); // x-axis 'to' limit (blank = auto)
  const [evalT, setEvalT] = useState(""); // time at which R(t)/F(t) is read off
  // Whether "To" / "Evaluate at" hold the values a calculation filled in
  // (auto) rather than ones the user typed. An auto "To" isn't sent back, so
  // the next calculation sizes its own axis — as of now, to the remaining
  // life rather than the from-new range. A typed value always wins.
  const [tMaxAuto, setTMaxAuto] = useState(true);
  const [evalTAuto, setEvalTAuto] = useState(true);
  const [condAge, setCondAge] = useState(""); // conditional survival age s
  const [covValues, setCovValues] = useState({}); // {nodeId: {covName: value}}
  const [calcSig, setCalcSig] = useState(null); // inputs used for the last calc
  const [showCov, setShowCov] = useState(false);
  const [band, setBand] = useState({ on: false, level: 0.95 }); // confidence band (#103)
  // "As of now" — the blocks' current states: repairable (#155) and
  // non-repairable (#173, where a failed block stays failed).
  const [asOf, setAsOf] = useState(false);
  const [blockStates, setBlockStates] = useState({}); // {nodeId: {mode: "new"|"age"|"down"|"failed", value}}
  // Non-repairable (#173): the design life, the time R(t) falls to this (%).
  const [targetPct, setTargetPct] = useState("90");
  const [busy, setBusy] = useState(null); // null | "exact" | "simulate": what the running request adds

  const unitLabel = graph.unit ? ` (${graph.unit})` : "";
  const canCalculate = !!validation?.can_calculate && !stale;

  // Blocks whose life model is a guessed starting point (the assistant marks
  // them placeholder:true). The numbers run fine; the results just aren't real.
  const placeholderCount = useMemo(
    () => (graph.nodes || []).filter((n) => n.data?.model?.placeholder).length,
    [graph.nodes]
  );

  // Nodes backed by a proportional-hazards model need covariate values before
  // they can be evaluated.
  const covNodes = useMemo(
    () =>
      (graph.nodes || [])
        .filter(
          (n) =>
            n.data?.model?.kind === "regression" &&
            (n.data.model.covariates || []).length
        )
        .map((n) => ({
          id: n.id,
          label: n.data.label || n.id,
          covariates: n.data.model.covariates,
        })),
    [graph.nodes]
  );

  const covValue = (node, c) => covValues[node.id]?.[c.name] ?? c.default;

  // The covariate payload sent to the backend (filled with defaults).
  const covPayload = () => {
    const out = {};
    for (const node of covNodes) {
      out[node.id] = {};
      for (const c of node.covariates) out[node.id][c.name] = covValue(node, c);
    }
    return out;
  };

  // The blocks a current state can be given: components not pinned working/failed.
  const stateBlocks = useMemo(
    () =>
      (graph.nodes || [])
        .filter((n) => n.type === "component" && !["working", "failed"].includes(n.data?.state))
        .map((n) => ({ id: n.id, label: n.data?.label || n.id })),
    [graph.nodes]
  );

  // The current state sent to the backend: {id: {down: true, since} | {age}}
  // for a repairable diagram, {id: {failed: true} | {age}} for a non-repairable one.
  const statePayload = () => {
    if (!asOf) return null;
    const out = {};
    for (const b of stateBlocks) {
      const st = blockStates[b.id];
      if (!st || st.mode === "new") continue;
      const v = st.value === "" || st.value == null ? 0 : Number(st.value);
      const isOut = st.mode === "down" || st.mode === "failed"; // down (repairable) or failed
      if (isOut && graph.repairable) out[b.id] = { down: true, since: v };
      else if (isOut) out[b.id] = { failed: true };
      else if (st.mode === "age" && v > 0) out[b.id] = { age: v };
    }
    return Object.keys(out).length ? out : null;
  };

  // The design life's target reliability (0–1), or null when blank or invalid.
  const target = (() => {
    if (graph.repairable || targetPct === "") return null;
    const v = Number(targetPct);
    return v > 0 && v < 100 ? v / 100 : null;
  })();

  // Signature of the calculation inputs, so we can tell when the shown result
  // is out of date with the current "To" / covariate / conditional selections.
  const bandSig = band.on ? band.level : null;
  const tSent = tMax === "" || tMaxAuto ? null : Number(tMax); // null: the backend sizes the axis
  const inputSig = JSON.stringify({
    t: tSent, s: asOf && !graph.repairable ? "" : condAge, cov: covPayload(), band: bandSig,
    now: statePayload(), target,
  });
  const dirty = result != null && calcSig != null && inputSig !== calcSig;

  // ``simulate`` asks for the (paid) simulation; ``exact`` for the exact
  // figures of a diagram above the automatic size cap. A plain Calculate of a
  // repairable diagram gets the exact figures (free) and any saved simulation.
  const runCalculation = async (force = false, { simulate = false, exact = false } = {}) => {
    setPhase("calculating");
    setBusy(simulate || force ? "simulate" : exact ? "exact" : null);
    setError(null);
    setNeedsPro(false);
    try {
      const cov = covPayload();
      // As of now replaces the whole-system "given survived to" age.
      const sInput = asOf && !graph.repairable ? "" : condAge;
      const s = sInput === "" ? null : Number(sInput);
      const now = statePayload();
      const res = await analyzeRbd(
        graph,
        tSent,
        cov,
        s,
        // Saved repairable diagrams can be served a saved availability result.
        {
          rbdId: graph.repairable ? rbdId : null,
          force,
          band: band.on && !graph.repairable ? { level: band.level } : null,
          ...(graph.repairable
            ? {
                simulate: simulate || force,
                currentState: now,
                // Keep large diagrams' exact figures once asked for.
                exact: exact || result?.exact?.status === "ok",
              }
            : { currentState: now, targetReliability: target }),
        }
      );
      setResult(res);
      // Repairable diagrams return an availability payload (no reliability grid).
      if (res.kind !== "repairable") {
        // Prefill the prompts with the range actually used so the user can see
        // and adjust them (refreshed while they're still the auto values).
        const limit = res.time[res.time.length - 1];
        if (tSent == null) {
          setTMax(Number(limit.toPrecision(4)));
          setTMaxAuto(true);
        }
        if (evalT === "" || evalTAuto) {
          setEvalT(Number((limit / 2).toPrecision(4)));
          setEvalTAuto(true);
        }
      }
      setCalcSig(JSON.stringify({ t: tSent, s: sInput, cov, band: bandSig, now, target }));
      setPhase("idle");
      setBusy(null);
    } catch (err) {
      setBusy(null);
      if (err.status === 402 && err.code === "pro_required") {
        // A simulation-only diagram (no exact figures): the paywall.
        setResult(null);
        setNeedsPro(true);
        setPhase("idle");
        return;
      }
      setError(err.message);
      setPhase("error");
    }
  };

  const setBlockState = (id, patch) =>
    setBlockStates((prev) => ({ ...prev, [id]: { mode: "new", value: "", ...prev[id], ...patch } }));

  return (
    <div className="rbd-calc">
      <div className="rbd-calc-actions">
        <button
          onClick={() => runCalculation(false)}
          disabled={!canCalculate || phase === "calculating"}
          title={
            canCalculate
              ? "Run the reliability calculation"
              : "Validate the RBD on the Builder tab first"
          }
        >
          {phase === "calculating"
            ? "Calculating…"
            : result && !stale
            ? "Recalculate"
            : "Calculate"}
        </button>
        {dirty && (
          <span className="hint">Recalculate to apply your changes.</span>
        )}
      </div>

      {placeholderCount > 0 && (
        <div className="rbd-placeholder-note" role="status">
          {placeholderCount === 1
            ? "1 block uses placeholder parameters"
            : `${placeholderCount} blocks use placeholder parameters`}
          {" — results are illustrative until you set real values."}
        </div>
      )}

      {canCalculate && covNodes.length > 0 && (
        <div className="rbd-cov-bar">
          <button className="secondary" onClick={() => setShowCov(true)}>
            Set covariates
          </button>
          <span className="hint">
            {covNodes.length} proportional-hazards node
            {covNodes.length === 1 ? "" : "s"} —{" "}
            {covNodes
              .map(
                (node) =>
                  `${node.label}: ` +
                  node.covariates
                    .map((c) => `${c.name}=${covValue(node, c)}`)
                    .join(", ")
              )
              .join(" · ")}
          </span>
        </div>
      )}

      {canCalculate && !graph.repairable && (
        <div className="calc-controls rbd-calc-inputs">
          <label className="calc-t">
            <span>To{unitLabel} — x-axis limit</span>
            <input
              type="number"
              min="0"
              step="any"
              placeholder="auto"
              value={tMax}
              onChange={(e) => {
                setTMax(e.target.value);
                setTMaxAuto(e.target.value === "");
              }}
            />
          </label>
          <label className="calc-t">
            <span>Evaluate at t{unitLabel}</span>
            <input
              type="number"
              min="0"
              max={tMax || undefined}
              step="any"
              value={evalT}
              onChange={(e) => {
                setEvalT(e.target.value);
                setEvalTAuto(e.target.value === "");
              }}
            />
          </label>
          {!asOf && (
            <label className="calc-t">
              <span>Given survived to{unitLabel}</span>
              <input
                type="number"
                min="0"
                step="any"
                placeholder="0"
                value={condAge}
                onChange={(e) => setCondAge(e.target.value)}
              />
            </label>
          )}
          <label className="calc-t" title="The design life: how long system reliability stays at or above this">
            <span>Design life at R (%)</span>
            <input
              type="number"
              min="1"
              max="99.9"
              step="any"
              placeholder="90"
              value={targetPct}
              onChange={(e) => setTargetPct(e.target.value)}
            />
          </label>
          <BandControls value={band} onChange={setBand} />
          <label className="rbd-asof-toggle">
            <input type="checkbox" checked={asOf} onChange={(e) => setAsOf(e.target.checked)} />
            <span>As of now</span>
          </label>
        </div>
      )}

      {canCalculate && !graph.repairable && asOf && (
        <div className="rbd-asof">
          <AsOfPanel
            blocks={stateBlocks}
            states={blockStates}
            onChange={setBlockState}
            unitLabel={unitLabel}
            repairable={false}
          />
        </div>
      )}

      {canCalculate && graph.repairable && (
        <div className="rbd-asof">
          <div className="calc-controls rbd-calc-inputs">
            <label className="calc-t">
              <span>{asOf ? `Next${unitLabel} — window from now` : `Window${unitLabel}`}</span>
              <input
                type="number"
                min="0"
                step="any"
                placeholder="auto"
                value={tMax}
                onChange={(e) => {
                  setTMax(e.target.value);
                  setTMaxAuto(e.target.value === "");
                }}
              />
            </label>
            <label className="rbd-asof-toggle">
              <input type="checkbox" checked={asOf} onChange={(e) => setAsOf(e.target.checked)} />
              <span>As of now</span>
            </label>
          </div>
          {asOf && (
            <AsOfPanel
              blocks={stateBlocks}
              states={blockStates}
              onChange={setBlockState}
              unitLabel={unitLabel}
              repairable
            />
          )}
        </div>
      )}

      {!validation && (
        <p className="muted-line">
          Validate the RBD on the Builder tab before calculating.
        </p>
      )}

      {validation && <ValidationPanel validation={validation} stale={stale} />}

      {validation && !canCalculate && (
        <p className="hint">
          Calculation is disabled until the diagram validates — check it on
          the Builder tab.
        </p>
      )}

      {error && <div className="card error">{error}</div>}

      {needsPro && !stale && <AvailabilityUpgrade graph={graph} />}

      {result && !stale && result.kind === "repairable" && result.has_simulation !== false && result.cached && (
        <div className="rbd-saved-note" role="status">
          <span>{savedOn(result.computed_at)} (simulation)</span>
          {result.can_recompute && (
            <button
              type="button"
              className="secondary"
              disabled={phase === "calculating"}
              onClick={() => runCalculation(true)}
              title="Run the availability simulation again"
            >
              Re-run
            </button>
          )}
        </div>
      )}

      {result && !stale && result.kind === "repairable" && (
        <AvailabilityView
          result={result}
          unit={graph.unit}
          graph={graph}
          busy={phase === "calculating" ? busy : null}
          onSimulate={() => runCalculation(false, { simulate: true })}
          onCompute={() => runCalculation(false, { exact: true })}
        />
      )}
      {result && !stale && result.kind === "repairable" && (
        <AvailabilityCompare graph={graph} rbdId={rbdId} result={result} />
      )}

      {result && !stale && result.kind !== "repairable" && (
        <Results
          result={result}
          t={evalT === "" ? null : Number(evalT)}
          tMax={tSent}
          conditionalAge={result.conditional_age || 0}
        />
      )}

      {showCov && (
        <CovariatesModal
          covNodes={covNodes}
          values={covValues}
          onApply={(v) => {
            setCovValues(v);
            setShowCov(false);
          }}
          onClose={() => setShowCov(false)}
        />
      )}
    </div>
  );
}
