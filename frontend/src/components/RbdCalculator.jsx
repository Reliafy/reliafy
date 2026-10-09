import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Plot from "./Plot.jsx";
import { COLORWAY, DATA_INK, bandPair, fitLine, pointMarker, referenceShape } from "../plotTheme.js";
import { analyzeRbd, getActiveRbdJob, getRbdJob } from "../api.js";
import ValidationPanel from "./RbdValidation.jsx";
import RbdEmptyState from "./RbdEmptyState.jsx";
import { diagramGap } from "../rbdReadiness.js";
import CovariatesModal from "./CovariatesModal.jsx";
import { BandControls, BandInterval, BandNote, bandTraces, hasBand } from "./RbdBand.jsx";
import AvailabilityCompare from "./AvailabilityCompare.jsx";
import AvailabilityCosts, { DowntimeSplit } from "./AvailabilityCosts.jsx";
import AvailabilityPolicies from "./AvailabilityPolicies.jsx";
import { precisionNote } from "./availabilityPrecision.js";
import MethodTag from "./MethodTag.jsx";
import RbdNextFailure, { meanResidualLife } from "./RbdNextFailure.jsx";
import WhatToImprove from "./WhatToImprove.jsx";
import { unitInText } from "./unitText.js";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import Chip from "./ui/Chip.jsx";

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
// The system is the accent; its blocks take the next series colours.
const NODE_COLORS = COLORWAY.slice(1);


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
  const unit = result.unit ? ` ${unitInText(result.unit)}` : "";
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
  const unit = result.unit ? ` ${unitInText(result.unit)}` : "";
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
export function Results({ result, t, tMax, conditionalAge = 0, name = null }) {
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

  // System curve plus a faint dotted curve per node.
  const traces = [
    ...bandTraces(band, x, active),
    fitLine({ x, y: sysY, line: { width: 2.5 }, name: "System", connectgaps: false }),
  ];
  (result.nodes || []).forEach((n, i) => {
    const y = active === "sf" ? n.sf : n.sf.map((v) => (v == null ? null : 1 - v));
    traces.push({
      x,
      y,
      mode: "lines",
      // Past the series colours, blocks are plain ink (colours aren't reused).
      line: { color: NODE_COLORS[i] || DATA_INK, width: 1.25, dash: "dot" },
      name: n.label,
      type: "scatter",
      connectgaps: false,
      opacity: 0.8,
    });
  });
  if (sysAtT != null) {
    traces.push({ ...pointMarker(), x: [Number(t)], y: [sysAtT] });
  }

  const layout = {
    height: 440,
    showlegend: true,
    xaxis: {
      title: { text: tLabel },
      range: [0, tMax != null ? Number(tMax) : x[x.length - 1]],
    },
    yaxis: { title: { text: activeLabel }, range: [0, 1.02] },
    shapes: t == null ? [] : [referenceShape({ x: Number(t), line: { dash: "dot" } })],
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
            ({result.ccf.groups.map((g) => `${g.members.join(" & ")} β=${g.beta}`).join("; ")}, at t={fmt(result.ccf.time)}{unit ? ` ${unitInText(unit)}` : ""})
          </span>
        </div>
      )}
      {(result.warnings || []).map((w) => (
        <p className="muted-line" key={w}>⚠ {w}</p>
      ))}
      {now && <AsOfNote result={result} idToLabel={idToLabel} />}
      <DesignLife result={result} />
      <div className="params">
        <div className="stat">
          <div className="value">{fmt(result.mttf)}</div>
          <div className="name">
            {now ? "Mean remaining life" : cond ? "Mean residual life" : "MTTF"}
            {unit ? ` (${unit})` : ""}
            {now && result.mean_residual_life && <> <MethodTag method={result.mean_residual_life.method} /></>}
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
        <SegmentedControl
          label="Function"
          value={active}
          onChange={setActive}
          options={FUNCS.map((f) => ({ value: f.id, label: f.id === "sf" ? "R(t)" : "F(t)", title: f.label }))}
        />
      </div>

      <Plot data={traces} layout={layout} download={`${name || "System"} — ${activeLabel}`} />
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

// A y-range fitted to the availability curves themselves (#308): from zero
// they read as a flat line at the top. A simulation's confidence band is left
// to run off the bottom rather than set the scale.
function availabilityRange(...curves) {
  const v = curves.flat().filter((y) => y != null && Number.isFinite(y));
  if (!v.length) return undefined;
  const lo = Math.min(...v);
  const hi = Math.max(...v);
  const pad = Math.max((hi - lo) * 0.12, 1e-5);
  return [Math.max(0, lo - pad), Math.min(1, hi) + pad];
}

// The exact figures over time (#154), from new or from the current state
// (#155): the window's figures, each labelled with its method, and A(t).
function ExactSection({ exact, steady, unit, onCompute, computing, sim = null }) {
  const u = unit ? ` ${unitInText(unit)}` : "";
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
  // With a simulation over the same window, one chart carries both: the exact
  // A(t) is the answer (accent), the simulated one the check (ink, with its band).
  // (The simulation's band is left off here: next to the exact curve it is noise.)
  const traces = [
    ...(sim
      ? [{
          x: sim.curve.t, y: sim.curve.availability, mode: "lines", type: "scatter",
          line: { color: "rgba(20, 23, 28, 0.35)", width: 1 }, name: "Simulated",
          hovertemplate: `t = %{x:,.4~g}${u}<br>Simulated A(t) = %{y:.5f}<extra></extra>`,
        }]
      : []),
    fitLine({
      x: c.t, y: c.availability, name: sim ? "Exact" : "A(t)",
      hovertemplate: `t = %{x:,.4~g}${u}<br>A(t) = %{y:.5f}<extra></extra>`,
    }),
  ];
  const shapes = steady != null && c.t?.length ? [referenceShape({ y: steady })] : [];
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
            height: sim ? 320 : 280,
            xaxis: { title: { text: unit ? `Time ${fromNow ? "from now" : "from new"} (${unit})` : "Time" } },
            // Auto-scaled: availability moves in the third decimal place.
            yaxis: {
              title: { text: "Availability A(t)" }, tickformat: ".4~%",
              range: availabilityRange(c.availability, sim ? sim.curve.availability : [], steady != null ? [steady] : []),
            },
            shapes, showlegend: !!sim,
          }}
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
        simulation{steady != null ? "; the dashed line is the long-run availability" : ""}
        {sim ? ". The grey line is the simulation's estimate over the same window" : ""}.
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

// "Queued — 2 ahead of you…" / "Running…" while a simulation job is in flight.
function jobStatusText(job) {
  if (!job) return "";
  if (job.status === "running") return "Running the simulation…";
  const ahead = job.queue_position;
  if (ahead == null || ahead <= 0) return "Queued — you're next…";
  return `Queued — ${ahead} ahead of you…`;
}

// Poll intervals for a queued job: every 1.5 s, easing off to 6 s.
const POLL_FIRST_MS = 1500;
const POLL_MAX_MS = 6000;

// "~3 s" from a quick-run offer's seconds.
const quickSeconds = (offer) => (offer ? Number(Number(offer.seconds).toPrecision(2)) : 3);

// Shown in place of the simulation's results when none has been run: what it
// adds over the exact figures, and the way to run it (Pro, or credits) — for a
// user without Pro, a free quick run (#147) a few times a day. While a
// simulation is queued or running on the calculation service (#146), its
// place in the queue.
function SimulationOffer({ canSimulate, onSimulate, simulating, graph, quick = null, capMessage = null,
                           onQuick = null, job = null, fromNow = false }) {
  const [upgrade, setUpgrade] = useState(false);
  if (!onSimulate) return null;
  const canQuick = !canSimulate && !!onQuick && quick && quick.remaining_today > 0 && !capMessage;
  const seconds = quickSeconds(quick);
  return (
    <div className="card rbd-sim-offer">
      <div className="ds-section-h" style={{ marginTop: 0 }}>Simulation</div>
      <p style={{ margin: "4px 0 0" }}>
        The figures above are exact. A Monte-Carlo simulation adds the spread of outcomes: the chance of no
        outage, percentiles, criticality indices (which block trips the system, which restores it) and a
        confidence band.{fromNow && " From now, it also gives the time to the next system failure, its mean residual life and its likely cause."}
        {canQuick && (
          <>
            {" "}A quick estimate is free: it simulates for about {seconds} s and says how many replications it
            ran and how precise it is.{" "}
            <span className="muted">{quick.remaining_today} of {quick.per_day} free runs left today.</span>
          </>
        )}
      </p>
      {capMessage && !canSimulate && <p className="rbd-quick-cap">{capMessage}</p>}
      {!capMessage && !canSimulate && onQuick && quick && quick.remaining_today <= 0 && (
        <p className="rbd-quick-cap">
          You've used today's {quick.per_day} free quick simulations. They reset at 00:00 UTC.
        </p>
      )}
      {job ? (
        <p className="rbd-job-status" role="status" aria-live="polite">{jobStatusText(job)}</p>
      ) : (
        <div className="rbd-upgrade-actions">
          {canQuick && (
            <button type="button" onClick={onQuick} disabled={simulating}>
              {simulating ? "Simulating…" : `Run quick simulation (free, ~${seconds} s)`}
            </button>
          )}
          <button
            type="button"
            className={canSimulate ? "" : "secondary"}
            disabled={simulating}
            onClick={() => (canSimulate ? onSimulate() : setUpgrade(true))}
          >
            {simulating && canSimulate ? "Simulating…" : canSimulate ? "Run simulation" : "Run full simulation (Pro)"}
          </button>
        </div>
      )}
      {upgrade && !canSimulate && <AvailabilityUpgrade graph={graph} />}
    </div>
  );
}

// "Quick estimate": a free, time-capped simulation's result (#147).
function QuickTag() {
  return (
    <Chip tone="warning" style={{ marginLeft: 8 }} title="A free, time-capped simulation: fewer replications than a full run">
      Quick estimate
    </Chip>
  );
}

export function AvailabilityView({ result, unit, graph = null, onSimulate = null, onCompute = null, busy = null,
                                  onQuick = null, capMessage = null, job = null }) {
  const u = unit ? ` ${unitInText(unit)}` : "";
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
        ...(hasBand ? bandPair(curve.t, curve.lower, curve.upper) : []),
        fitLine({ x: curve.t, y: curve.availability, name: "Simulated" }),
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
          {simulatedOnly && result.quick && <QuickTag />}
        </div>
      </div>
      {/* Common-cause groups (#226): in every figure here, or left out of them all and why. */}
      {result.common_cause?.included && (
        <p className="rbd-avail-ccf">
          Includes the diagram's {result.common_cause.groups} common-cause
          group{result.common_cause.groups === 1 ? "" : "s"} in every figure
          {result.common_cause.availability_without_common_cause != null && (
            <> — without {result.common_cause.groups === 1 ? "it" : "them"} the long-run availability would
              be <b>{pct(result.common_cause.availability_without_common_cause)}</b></>
          )}.
        </p>
      )}
      {/* A safety function whose PFDavg includes its common-cause groups (#265): the figure with them. */}
      {result.safety && !result.common_cause?.included && result.common_cause?.availability_with_common_cause != null && (
        <p className="rbd-avail-ccf">
          <b>{pct(result.common_cause.availability_with_common_cause)}</b> with the common-cause groups (1 − PFDavg,
          as the safety function below). The figures here leave them out.
        </p>
      )}
      {result.common_cause && !result.common_cause.included && result.common_cause.note
        && !(result.warnings || []).includes(result.common_cause.note) && (
        <p className="muted-line">⚠ {result.common_cause.note}</p>
      )}
      {(result.warnings || []).map((w) => (
        <p className="muted-line" key={w}>⚠ {w}</p>
      ))}
      <div className="rbd-avail-metrics">
        <div className="alt-metric"><span className="k">Unavailability</span><span className="v">{pct(simulatedOnly ? (a == null ? null : 1 - a) : result.unavailability)}</span></div>
        <div className="alt-metric" title={basisNote("mean_up_time")}><span className="k">Mean up time</span><span className="v">{fmt(result.mean_up_time)}{u}</span></div>
        <div className="alt-metric" title={basisNote("mean_down_time")}><span className="k">Mean down time</span><span className="v">{fmt(result.mean_down_time)}{u}</span></div>
        <div className="alt-metric" title={basisNote("failure_frequency")}><span className="k">Failure frequency</span><span className="v">{fmt(result.failure_frequency)}{u ? ` /${unit}` : ""}</span></div>
        {hasSim && result.next_failure && (
          <div className="alt-metric" title="Simulated mean time from now to the next system failure (see Next system failure from now)"><span className="k">Mean residual life</span><span className="v">{meanResidualLife(result.next_failure)}{u}</span></div>
        )}
      </div>

      <ExactSection
        exact={exact}
        steady={simulatedOnly ? null : result.steady_state_availability}
        unit={unit}
        onCompute={onCompute}
        computing={busy === "exact"}
        sim={sameWindow ? { curve } : null}
      />
      {exactOk && result.proof_test_note && <p className="muted-line">{result.proof_test_note}</p>}

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
            {result.quick && <QuickTag />}
          </div>
          <RbdNextFailure result={result} unit={unit} />
          {exactOk && <DowntimeBars rows={simPer} title="Simulated share of downtime" />}
          {/* Over the exact window the simulated curve is drawn on the exact chart above. */}
          {curve && curve.t?.length > 1 && !sameWindow && (
            <Plot
              data={curveTraces}
              layout={{
                height: 300,
                xaxis: { title: { text: unit ? `Time (${unit})` : "Time" } },
                // Auto-scaled, not from zero: availability moves in the third decimal place.
                yaxis: { title: { text: "Availability" }, tickformat: ".4~%", range: availabilityRange(curve.availability) },
                showlegend: false,
              }}
            />
          )}
          <p className="muted-line" style={{ margin: 0 }}>
            {result.quick ? "Quick estimate: availability" : "Availability"} curve estimated by{" "}
            {result.n_simulations?.toLocaleString()} Monte-Carlo
            replications{result.precision?.antithetic ? " (in antithetic pairs)" : ""}
            {result.quick && result.time_budget_s ? `, a quick run of at most ${fmt3(result.time_budget_s)} s,` : ""}{" "}
            over {fmt(result.t_simulation)}{u}
            {hasBand && !sameWindow ? `, with a ${Math.round((curve.confidence || 0.95) * 100)}% confidence band` : ""}
            {sameWindow ? "; it is drawn with the exact A(t) above" : ""}.
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
          quick={result.simulation_status?.quick || null}
          capMessage={capMessage}
          onQuick={onQuick}
          job={job}
          fromNow={!!result.current_state}
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

// The Pro offer: shown when a free user asks for the simulation, and instead
// of an error for a diagram whose figures need it (no exact ones). The full
// simulation is a paid feature; a quick, time-capped one is free a few times
// a day (#147) — offered here when ``offer`` (the 402's) says so.
function AvailabilityUpgrade({ graph, offer = null, capMessage = null, onQuick = null, running = false }) {
  const exportDiagram = () => {
    // RbdBuilder listens for this event and downloads the saved diagram as a
    // standalone SurPyval + RePyability script (free for every viewer).
    window.dispatchEvent(new CustomEvent("reliafy:rbd-export", { detail: { graph } }));
  };
  const canQuick = !!onQuick && offer && offer.remaining_today > 0 && !capMessage;
  const seconds = quickSeconds(offer);
  return (
    <div className="card note rbd-upgrade" role="status">
      {canQuick ? (
        <p>
          <b>Run a quick availability estimate — free.</b> This diagram's figures need the simulation. A quick
          one runs for about {seconds} s and reports how many replications it ran and how precise the estimate
          is.{" "}
          <span className="muted">
            {offer.remaining_today} of {offer.per_day} free runs left today.
          </span>{" "}
          Pro runs the full simulation for a tighter estimate.
        </p>
      ) : capMessage ? (
        <p>{capMessage}</p>
      ) : (
        <p>
          <b>The simulation runs thousands of histories — it's part of Pro.</b>{" "}
          Subscribe to Pro or buy AI credits to run it here.
        </p>
      )}
      <div className="rbd-upgrade-actions">
        {canQuick && (
          <button type="button" className="cta cta-solid" onClick={onQuick} disabled={running}>
            {running ? "Simulating…" : `Run quick simulation (free, ~${seconds} s)`}
          </button>
        )}
        <Link className={canQuick ? "linkish" : "cta cta-solid"} to="/billing">
          {canQuick ? "Upgrade to Pro for full runs" : "Upgrade to Pro"}
        </Link>
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

export default function RbdCalculator({ graph, validation, stale, rbdId = null, name = null, onBuild }) {
  const [result, setResult] = useState(null);
  const [phase, setPhase] = useState("idle"); // idle | calculating | error
  const [error, setError] = useState(null);
  const [needsPro, setNeedsPro] = useState(false); // 402 pro_required (availability)
  const [quickOffer, setQuickOffer] = useState(null); // free quick runs: {seconds, per_day, remaining_today}
  const [capMessage, setCapMessage] = useState(null); // 429: today's free runs used
  const [retryable, setRetryable] = useState(null); // 503: the calculation service couldn't take it
  const [job, setJob] = useState(null); // {job_id, status, queue_position} while queued/running
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
  // ``quick`` asks for a free, time-capped simulation (users without Pro, #147).
  const runCalculation = async (force = false, { simulate = false, exact = false, quick = false } = {}) => {
    setPhase("calculating");
    setBusy(simulate || force || quick ? "simulate" : exact ? "exact" : null);
    setError(null);
    setRetryable(null);
    setNeedsPro(false);
    setCapMessage(null);
    setJob(null);
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
                simulate: simulate || force || quick,
                quick,
                currentState: now,
                // Keep large diagrams' exact figures once asked for.
                exact: exact || result?.exact?.status === "ok",
              }
            : { currentState: now, targetReliability: target }),
        }
      );
      setResult(res);
      if (res.free_sims) setQuickOffer(res.free_sims);
      if (res.job) {
        // The exact figures now; the simulation is queued on the calculation
        // service (#146): poll until it's done.
        setJob(res.job);
      }
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
      if (!res.job) {
        setPhase("idle");
        setBusy(null);
      }
    } catch (err) {
      setBusy(null);
      if (err.status === 402 && err.code === "pro_required") {
        // A simulation-only diagram (no exact figures): the paywall — with
        // the free quick run where it's offered.
        setResult(null);
        setQuickOffer(err.data?.quick || null);
        setNeedsPro(true);
        setPhase("idle");
        return;
      }
      if (err.status === 429 && err.code === "free_sim_cap") {
        // Today's free quick runs are used: say so where the offer was.
        setQuickOffer(err.data?.quick || null);
        setCapMessage(err.message);
        if (!result) setNeedsPro(true);
        setPhase("idle");
        return;
      }
      if (err.status === 503) setRetryable({ force, simulate, exact, quick });
      setError(err.message);
      setPhase("error");
    }
  };

  // Poll the in-flight job until it finishes. Survives transient network
  // errors (keeps trying, more slowly); gives up after a run of failures.
  const jobId = job?.job_id;
  useEffect(() => {
    if (!jobId) return undefined;
    let cancelled = false;
    let timer = null;
    let delay = POLL_FIRST_MS;
    let failures = 0;
    setPhase("calculating");
    setBusy("simulate");
    const finish = () => {
      setJob(null);
      setBusy(null);
    };
    const poll = async () => {
      try {
        const view = await getRbdJob(jobId);
        if (cancelled) return;
        failures = 0;
        if (view.status === "done") {
          finish();
          // The whole payload: the simulation with the exact figures beside it.
          setResult(view.result);
          setPhase("idle");
          return;
        }
        if (view.status === "failed") {
          finish();
          setError(view.error || "The calculation failed.");
          setPhase("error");
          return;
        }
        setJob((prev) => (prev && prev.job_id === jobId ? { ...prev, ...view } : prev));
      } catch (err) {
        if (cancelled) return;
        if (err.status === 404 || ++failures >= 6) {
          finish();
          setError(err.status === 404 ? "The calculation was lost — run it again." : err.message);
          setPhase("error");
          return;
        }
      }
      delay = Math.min(delay * 1.3, POLL_MAX_MS);
      timer = setTimeout(poll, delay);
    };
    timer = setTimeout(poll, POLL_FIRST_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId]);

  // After a reload, pick up this diagram's simulation if one is still in flight.
  const resumed = useRef(null);
  useEffect(() => {
    if (!rbdId || !graph.repairable || resumed.current === rbdId) return;
    resumed.current = rbdId;
    getActiveRbdJob(rbdId)
      .then(({ job: active }) => {
        if (active && (active.status === "queued" || active.status === "running")) setJob(active);
      })
      .catch(() => {}); // nothing to resume
  }, [rbdId, graph.repairable]);

  const setBlockState = (id, patch) =>
    setBlockStates((prev) => ({ ...prev, [id]: { mode: "new", value: "", ...prev[id], ...patch } }));

  // Nothing to calculate yet (#271): a next step in place of the controls
  // (and of any result from before the blocks went).
  const gap = diagramGap(graph);
  if (gap) {
    return (
      <div className="rbd-calc">
        <RbdEmptyState
          gap={gap}
          goal={graph.repairable ? "calculate the system's availability" : "calculate the system's reliability"}
          onBuild={onBuild}
        />
      </div>
    );
  }

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
        {job && (
          <span className="rbd-job-status" role="status" aria-live="polite">
            {jobStatusText(job)}
          </span>
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

      {error && (
        <div className="card error">
          {error}
          {retryable && (
            <div className="rbd-upgrade-actions">
              <button
                type="button"
                className="secondary"
                disabled={phase === "calculating"}
                onClick={() => runCalculation(retryable.force, retryable)}
              >
                Try again
              </button>
            </div>
          )}
        </div>
      )}

      {needsPro && !stale && (
        <AvailabilityUpgrade
          graph={graph}
          offer={quickOffer}
          capMessage={capMessage}
          running={phase === "calculating"}
          onQuick={() => runCalculation(false, { quick: true })}
        />
      )}

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
          onQuick={() => runCalculation(false, { quick: true })}
          capMessage={capMessage}
          job={job}
        />
      )}
      {result && !stale && result.kind === "repairable" && result.quick && !result.can_recompute && (
        <div className="rbd-saved-note rbd-quick-note" role="status">
          <span>
            A quick estimate
            {quickOffer ? ` · ${quickOffer.remaining_today} of ${quickOffer.per_day} free runs left today` : ""}.
          </span>
          <Link to="/billing">Pro runs the full simulation for a tighter estimate</Link>
        </div>
      )}
      {result && !stale && result.kind === "repairable" && (
        <WhatToImprove graph={graph} rbdId={rbdId} result={result} />
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
          name={name}
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
