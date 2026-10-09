import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Plot from "./Plot.jsx";
import { COLORWAY, DANGER, DATA_INK, bandPair, fitLine, pointMarker, referenceShape } from "../plotTheme.js";
import { analyzeRbd, getActiveRbdJob, getRbdJob } from "../api.js";
import ValidationPanel from "./RbdValidation.jsx";
import RbdEmptyState from "./RbdEmptyState.jsx";
import { diagramGap } from "../rbdReadiness.js";
import CovariatesModal from "./CovariatesModal.jsx";
import { BandControls, BandInterval, BandNote, bandTraces, hasBand } from "./RbdBand.jsx";
import AvailabilityCompare from "./AvailabilityCompare.jsx";
import AvailabilityCosts, { DowntimeSplit } from "./AvailabilityCosts.jsx";
import AvailabilityPolicies, { SafetyNotes } from "./AvailabilityPolicies.jsx";
import { pctAt, pctDigits, precisionNote } from "./availabilityPrecision.js";
import MethodTag from "./MethodTag.jsx";
import RbdNextFailure, { meanResidualLife } from "./RbdNextFailure.jsx";
import WhatToImprove from "./WhatToImprove.jsx";
import { unitInText } from "./unitText.js";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import Chip from "./ui/Chip.jsx";
import { ResultDetails } from "./ui/ResultSummary.jsx";
import { formatNumber, formatPercent } from "../format.js";
import { hoursPerUnit } from "./rbdModelText.js";

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

// "99.968%": an availability to three decimals, or more when `spread` (a
// difference to show) needs them.
const pctOf = (v, spread = null) =>
  v == null || !Number.isFinite(v) ? "—" : pctAt(v, spread == null ? 3 : Math.max(3, pctDigits(spread)));

// "2.8 h", "17 min": downtime in hours, small values in minutes.
function hoursText(h) {
  if (h == null || !Number.isFinite(h)) return null;
  if (h > 0 && h < 1) return `${formatNumber(h * 60, { sig: 2 })} min`;
  return `${formatNumber(h, { sig: 2 })} h`;
}

// The block with the largest share of system downtime (the failure-oriented
// criticality, exact at the long-run availabilities) — the one "weakest link"
// view kept (#313).
export function weakestLink(result) {
  let best = null;
  for (const [id, i] of Object.entries(result.importance || {})) {
    const share = i?.unavailability_criticality;
    if (share == null || !Number.isFinite(share) || share <= 0) continue;
    if (!best || share > best.share) best = { id, label: i.label || id, share };
  }
  return best;
}

// The answer card (#311): rows of label and value, toned by the verdict, with
// an optional note and action. Built on ResultSummary's classes.
function AnswerCard({ tone = "neutral", lead, rows = [], note, action, className = "" }) {
  const shown = rows.filter(Boolean);
  return (
    <section className={`result-summary rs-${tone} rbd-answer ${className}`} aria-label="Result">
      <div className="rs-answer">
        <div className="rbd-answer-body">
          {lead && <p className="rs-sentence">{lead}</p>}
          {shown.length > 0 && (
            <dl className="rbd-answer-rows">
              {shown.map((r) => (
                <div key={r.label}>
                  <dt>{r.label}</dt>
                  <dd>{r.value}</dd>
                </div>
              ))}
            </dl>
          )}
          {note && <div className="rs-note">{note}</div>}
          {action}
        </div>
      </div>
    </section>
  );
}

// The SIL band a PFDavg falls in (low demand, IEC 61508): SIL n is
// [10^-(n+1), 10^-n).
const silLimit = (n) => 10 ** -n;

// A safety function's answer (#298, #311): PFDavg with its SIL, the target,
// the margin to the band limit and the risk reduction factor. Amber when the
// PFDavg leaves something out (#305); red when the target isn't met.
function SifAnswer({ safety }) {
  const met = safety.meets_target;
  const noTests = safety.proof_tests === "none";
  const ccfLeftOut = safety.common_cause_included === false || (safety.common_cause && !safety.common_cause.included);
  const optimistic = !!safety.sil_optimistic || noTests || ccfLeftOut;
  const chipTone = !safety.sil ? "danger" : optimistic || safety.sil === 1 ? "warning" : "success";
  const pfd = safety.pfd_avg;
  const hasTarget = safety.target_sil != null;
  const tone = hasTarget && !met ? "bad" : optimistic ? "caveat" : hasTarget && met ? "good" : "neutral";
  // Margin to the target's limit, or (no target) to the achieved band's.
  const ref = hasTarget ? safety.target_sil : safety.sil;
  const ratio = ref && pfd != null ? pfd / silLimit(ref) : null;
  const margin = ratio == null
    ? null
    : ratio <= 1
    ? `${formatPercent(ratio)} of the SIL ${ref} limit (${formatNumber(silLimit(ref))})`
    : `${formatNumber(ratio, { sig: 2 })}× the SIL ${ref} limit (${formatNumber(silLimit(ref))})`;
  const rows = [
    {
      label: "PFDavg",
      value: (
        <span className="rbd-answer-big">
          <b>{formatNumber(pfd)}</b>
          <Chip tone={chipTone} title={safety.sil_optimistic ? safety.sil_note : undefined}>
            {safety.sil ? `SIL ${safety.sil}` : "No SIL"}{safety.sil && optimistic ? " (optimistic)" : ""}
          </Chip>
        </span>
      ),
    },
    hasTarget && {
      label: "Target",
      value: <>SIL {safety.target_sil}: <b>{!met ? "not met" : optimistic ? "met, but optimistic" : "met"}</b></>,
    },
    margin && { label: "Margin", value: margin },
    pfd > 0 && { label: "Risk reduction", value: <>RRF <b>{formatNumber(1 / pfd)}</b></> },
  ];
  const note = (noTests || ccfLeftOut) && (
    <>
      {noTests && (
        <p>
          No block is proof-tested, so this PFDavg treats every failure as revealed and repaired at once. Give
          the blocks with hidden failures proof tests (double-click a block → Proof test).
        </p>
      )}
      {ccfLeftOut && (
        <p>
          Common cause is not included in this PFDavg, so it is optimistic by the groups&rsquo; contribution.
          {safety.common_cause?.note ? ` ${safety.common_cause.note}` : ""}
        </p>
      )}
    </>
  );
  return <AnswerCard tone={tone} rows={rows} note={note} className="rbd-sif-answer" />;
}

// One chart (#311, #313): the exact A(t) with any simulation over the same
// window drawn on it — or, for a safety function, PFD(t) = 1 − A(t) with the
// PFDavg and the target SIL's limit.
function AvailabilityChart({ exact, steady, unit, sim = null, safety = null }) {
  const u = unit ? ` ${unitInText(unit)}` : "";
  const c = exact?.curve || {};
  if (!(c.t?.length > 1)) return null;
  const fromNow = exact.from === "now";
  const xTitle = unit ? `Time ${fromNow ? "from now" : "from new"} (${unit})` : "Time";
  if (safety) {
    const pfd = c.availability.map((a) => (a == null ? null : 1 - a));
    const limit = safety.target_sil ?? safety.sil;
    const shapes = [
      ...(safety.pfd_avg != null ? [referenceShape({ y: safety.pfd_avg })] : []),
      ...(limit ? [referenceShape({ y: silLimit(limit), line: { color: DANGER, dash: "dot", width: 1 } })] : []),
    ];
    return (
      <Plot
        data={[fitLine({ x: c.t, y: pfd, name: "PFD(t)", hovertemplate: `t = %{x:,.4~g}${u}<br>PFD(t) = %{y:.3~g}<extra></extra>` })]}
        layout={{
          height: 300,
          xaxis: { title: { text: xTitle } },
          yaxis: { title: { text: "PFD(t)" }, rangemode: "tozero", exponentformat: "e" },
          shapes,
          showlegend: false,
          annotations: limit
            ? [{ x: 1, xref: "paper", y: silLimit(limit), yanchor: "bottom", xanchor: "right", showarrow: false,
                 text: `SIL ${limit} limit`, font: { size: 12, color: DANGER } }]
            : [],
        }}
      />
    );
  }
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
  const shapes = steady != null ? [referenceShape({ y: steady })] : [];
  return (
    <Plot
      data={traces}
      layout={{
        height: sim ? 320 : 280,
        xaxis: { title: { text: xTitle } },
        // Auto-scaled: availability moves in the third decimal place.
        yaxis: {
          title: { text: "Availability A(t)" }, tickformat: ".4~%",
          range: availabilityRange(c.availability, sim ? sim.curve.availability : [], steady != null ? [steady] : []),
        },
        shapes, showlegend: !!sim,
      }}
    />
  );
}

// The simulated A(t) (with its band) when there's no exact curve to draw it on.
function SimulatedChart({ curve, unit }) {
  if (!(curve?.t?.length > 1)) return null;
  const hasBand = curve.lower?.length === curve.t.length && curve.upper?.length === curve.t.length;
  return (
    <Plot
      data={[
        ...(hasBand ? bandPair(curve.t, curve.lower, curve.upper) : []),
        fitLine({ x: curve.t, y: curve.availability, name: "Simulated" }),
      ]}
      layout={{
        height: 300,
        xaxis: { title: { text: unit ? `Time (${unit})` : "Time" } },
        // Auto-scaled, not from zero: availability moves in the third decimal place.
        yaxis: { title: { text: "Availability" }, tickformat: ".4~%", range: availabilityRange(curve.availability) },
        showlegend: false,
      }}
    />
  );
}

// The method, said once (#313): how the figures on the page were found.
function methodLine(result, exactOk, hasSim) {
  const exact = result.exact || {};
  const m = exact.method || {};
  const word = (r) => (r === "simulated" || r === "simulation" || r === "refused" ? "simulated" : r || null);
  const parts = [];
  const longRun = result.availability_basis === "simulation" ? "simulated" : word(result.long_run_method?.route) || "exact";
  parts.push(`long-run figures ${longRun === "numerical" ? "numerical" : longRun}`);
  if (exactOk) {
    const overTime = [m.curve, m.mission_availability, m.expected_failures, m.downtime].map(word).filter(Boolean);
    const same = overTime.every((r) => r === overTime[0]);
    if (overTime.length) {
      parts.push(same
        ? `A(t), expected failures and downtime ${overTime[0]}`
        : `A(t) ${word(m.curve) || "—"}, expected failures ${word(m.expected_failures) || "—"}, downtime ${word(m.downtime) || "—"}`);
    }
  }
  let tail = "";
  if (hasSim) {
    tail = ` The spread comes from ${result.n_simulations?.toLocaleString() || "the"} Monte-Carlo replications` +
      `${result.quick ? " (a quick estimate)" : ""}.`;
  } else if (!parts.some((p) => p.includes("simulated"))) {
    tail = " No simulation.";
  }
  const s = parts.join("; ");
  return `Method: ${s}.${tail}`;
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

// The way to run the simulation (Pro, or credits) — for a user without Pro, a
// free quick run (#147) a few times a day. While a simulation is queued or
// running on the calculation service (#146), its place in the queue.
// ``primary``: the simulation is this view's next step (no exact figures).
function SimulationActions({ canSimulate, onSimulate, simulating, graph, quick = null, capMessage = null,
                             onQuick = null, job = null, primary = false }) {
  const [upgrade, setUpgrade] = useState(false);
  if (!onSimulate) return null;
  const canQuick = !canSimulate && !!onQuick && quick && quick.remaining_today > 0 && !capMessage;
  const seconds = quickSeconds(quick);
  return (
    <div className="rbd-sim-actions">
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
            <button type="button" className={primary ? "" : "secondary"} onClick={onQuick} disabled={simulating}>
              {simulating ? "Simulating…" : `Run quick simulation (free, ~${seconds} s)`}
            </button>
          )}
          <button
            type="button"
            className={canSimulate && primary ? "" : "secondary"}
            disabled={simulating}
            onClick={() => (canSimulate ? onSimulate() : setUpgrade(true))}
          >
            {simulating && canSimulate ? "Simulating…" : canSimulate ? "Run simulation" : "Run full simulation (Pro)"}
          </button>
          {canQuick && (
            <span className="muted">{quick.remaining_today} of {quick.per_day} free runs left today</span>
          )}
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

// "1 year", "5 years", "730 hours": the window, in words.
function windowWords(window, unit, label = null) {
  if (label) return label.replace(/^1 /, "");
  const hpu = hoursPerUnit(unit);
  if (hpu) {
    const years = (window * hpu) / 8760;
    if (years >= 1) return `${formatNumber(years, { sig: 2 })} year${years === 1 ? "" : "s"}`;
  }
  return `${formatNumber(window)}${unit ? ` ${unitInText(unit)}` : ""}`;
}

// Availability results for a repairable diagram, answer first (#311): the
// answer card (availability, weakest link, best improvement — or, for a safety
// function, PFDavg and its SIL), one chart, What to improve, then everything
// else folded under Details, and the method said once at the foot.
// ``windowLabel``: the window the user chose ("1 year"), null for the long
// run; ``top``: What to improve's top lever ({lever, of}, {pending} while it
// works, null for none);
// ``improve`` and ``more`` are rendered after the chart and inside Details.
// Also used by the public read-only view.
export function AvailabilityView({ result, unit, graph = null, onSimulate = null, onCompute = null, busy = null,
                                  onQuick = null, capMessage = null, job = null, windowLabel = null, top = null,
                                  improve = null, more = null }) {
  const u = unit ? ` ${unitInText(unit)}` : "";
  const hpu = hoursPerUnit(unit);
  // A result saved before #154 is a simulation result (no has_simulation flag).
  const hasSim = result.has_simulation !== false;
  const exact = result.exact || null;
  const exactOk = exact?.status === "ok";
  // No exact long-run value (a standby group with non-exponential repairs,
  // say): the headline is the simulated availability over the window.
  const simulatedOnly = result.availability_basis === "simulation";
  const steady = simulatedOnly ? null : result.steady_state_availability;
  const curve = hasSim ? result.curve : null;
  const basis = result.figures_basis || {};
  const basisNote = (k) =>
    basis[k] === "exact"
      ? "Exact steady-state value"
      : `Simulation estimate over ${fmt(result.t_simulation)}${u}`;
  // The exact A(t) over the simulated one, when both cover the same window from the same start.
  const sameWindow =
    exactOk && curve && Math.abs((exact.window || 0) - (result.t_simulation || 0)) <= 1e-9 * (exact.window || 1);
  const blocks = importanceRows(result);
  // The simulation's columns only when it ran; a column nothing fills is left out.
  const impCols = (hasSim ? IMP_COLS : IMP_COLS.filter((c) => !SIM_COLS.has(c.key)))
    .filter((c) => blocks.some((b) => b[c.key] != null));
  const simPer = hasSim ? result.per_node || [] : [];
  const fromNow = exact?.from === "now" || !!result.current_state;
  const needsSim = simulatedOnly && !hasSim;
  const safety = result.safety || null;
  const simulateProps = {
    canSimulate: !!result.can_simulate,
    onSimulate,
    simulating: busy === "simulate",
    graph,
    quick: result.simulation_status?.quick || null,
    capMessage,
    onQuick,
    job,
  };

  // The headline availability and what it's over.
  let a = null;
  let over = "";
  if (simulatedOnly) {
    a = hasSim ? result.precision?.window_availability ?? null : null;
    over = `over the simulated ${windowWords(result.t_simulation, unit)}`;
  } else if (windowLabel && exactOk && exact.mission_availability != null) {
    a = exact.mission_availability;
    over = `${fromNow ? "over the next" : "over the first"} ${windowWords(exact.window, unit, windowLabel)}`;
  } else {
    a = steady;
    over = "in the long run";
  }
  const downYear = a != null && hpu ? hoursText((1 - a) * 8760) : null;

  const weakest = weakestLink(result);
  let best = null;
  if (top && top.lever) {
    const d = top.lever.effect?.availability;
    const base = top.of === "window" ? exact?.mission_availability : steady;
    if (d != null && Number.isFinite(d)) {
      const yearGain = hpu ? hoursText(Math.abs(d) * 8760) : null;
      best = (
        <>
          <b>{top.lever.block}</b>: {top.lever.change || top.lever.name}{" "}
          <span className="rbd-answer-gain">
            {d >= 0 ? "+" : "−"}{formatNumber(Math.abs(d) * 100, { sig: 2 })} pp
            {base != null && ` (${pctOf(base, d)} → ${pctOf(base + d, d)}${windowLabel && top.of !== "window" ? " in the long run" : ""})`}
            {yearGain && d > 0 && ` · −${yearGain} downtime/yr`}
          </span>
        </>
      );
    }
  }

  const caveats = [
    result.common_cause && !result.common_cause.included && result.common_cause.note
      && !(result.warnings || []).includes(result.common_cause.note) ? result.common_cause.note : null,
  ].filter(Boolean);

  const answer = safety ? (
    <SifAnswer safety={safety} />
  ) : needsSim ? (
    <AnswerCard
      lead={
        <>
          This diagram needs a simulation: there&rsquo;s no exact route for{" "}
          <b>{(result.long_run_method?.blocks || []).join(", ") || "its availability"}</b>.
        </>
      }
      note={result.long_run_method?.reason}
      action={<SimulationActions {...simulateProps} primary />}
    />
  ) : (
    <AnswerCard
      tone={caveats.length || result.quick ? "caveat" : "neutral"}
      rows={[
        {
          label: "Availability",
          value: (
            <span className="rbd-answer-big">
              <b>{pctOf(a)}</b>
              <span className="rbd-answer-sub">
                {over}{downYear && <> · ≈ {downYear} down per year</>}
              </span>
              {result.quick && <QuickTag />}
            </span>
          ),
        },
        weakest && {
          label: "Weakest link",
          value: <><b>{weakest.label}</b> — {formatPercent(weakest.share)} of the system&rsquo;s downtime</>,
        },
        top?.pending
          ? { label: "Best improvement", value: <span className="muted">Working it out…</span> }
          : best && { label: "Best improvement", value: best },
      ]}
      note={caveats.length ? caveats.map((c) => <p key={c}>{c}</p>) : null}
    />
  );

  // The chart: exact (with any simulation over the same window), else the simulated curve.
  const chartOk = exactOk && exact.curve?.t?.length > 1;
  const pfdChart = safety && chartOk
    && (exact.common_cause_included !== false || safety.common_cause_included === false);
  let chart = null;
  if (chartOk) {
    chart = (
      <AvailabilityChart exact={exact} steady={steady} unit={unit} sim={sameWindow && !pfdChart ? { curve } : null}
                         safety={pfdChart ? safety : null} />
    );
  } else if (curve) chart = <SimulatedChart curve={curve} unit={unit} />;

  const pct3 = (v) => pctOf(v);
  const kpis = [
    !safety && !simulatedOnly && steady != null && windowLabel && { label: "Long-run availability", value: pctOf(steady) },
    safety && { label: simulatedOnly ? "Availability (window)" : "Long-run availability", value: pctOf(simulatedOnly ? a : steady) },
    { label: "Unavailability", value: pct3(simulatedOnly ? (a == null ? null : 1 - a) : result.unavailability), raw: simulatedOnly ? a : result.unavailability },
    { label: "Mean up time", value: `${formatNumber(result.mean_up_time)}${u}`, raw: result.mean_up_time, title: basisNote("mean_up_time") },
    { label: "Mean down time", value: `${formatNumber(result.mean_down_time)}${u}`, raw: result.mean_down_time, title: basisNote("mean_down_time") },
    { label: "Failure frequency", value: `${formatNumber(result.failure_frequency)}${unit ? ` /${unitInText(unit).replace(/s$/, "")}` : ""}`, raw: result.failure_frequency },
    hasSim && result.next_failure && { label: "Mean residual life", value: `${meanResidualLife(result.next_failure)}${u}` },
  ].filter((r) => r && (r.raw === undefined || r.raw != null));
  const span = exactOk ? `${formatNumber(exact.window)}${u}` : "";
  const windowKpis = exactOk ? [
    { label: `Mission availability (${fromNow ? "next" : "first"} ${span})`, value: pctOf(exact.mission_availability) },
    fromNow && { label: "Lowest A(t)", value: pctOf(exact.availability_min) },
    { label: "Expected failures", value: formatNumber(exact.expected_failures) },
    { label: "Expected outages", value: formatNumber(exact.expected_outages) },
    { label: "Expected downtime", value: `${formatNumber(exact.downtime)}${u}` },
    exact.cost && { label: "Expected cost", value: formatNumber(exact.cost.mean) },
  ].filter(Boolean) : [];
  const routes = Object.entries(exact?.routes || {});

  return (
    <div className="rbd-avail">
      {answer}
      {/* No exact figures over time: said once, by the answer card or the
          simulated chart, unless the exact ones are there to be asked for. */}
      {exact && (exact.status === "on_request" || (exact.status !== "ok" && exact.status !== "simulation_only" && !needsSim && exact.message)) && (
        <div className="card note rbd-exact-note" role="status">
          <p style={{ margin: 0 }}>{exact.message}</p>
          {exact.status === "on_request" && onCompute && (
            <div className="rbd-upgrade-actions">
              <button type="button" onClick={onCompute} disabled={busy === "exact"}>
                {busy === "exact" ? "Computing…" : "Compute exact figures"}
              </button>
            </div>
          )}
        </div>
      )}
      {chart}
      {!needsSim && improve}

      <ResultDetails>
        {(kpis.length > 0 || windowKpis.length > 0) && <ResultDetailsRows rows={[...kpis, ...windowKpis]} />}
        {(result.warnings || []).length > 0 && (
          <ul className="rbd-details-notes">
            {result.warnings.map((w) => <li key={w}>{w}</li>)}
          </ul>
        )}
        {/* Common-cause groups (#226): in every figure here, or left out of them all and why. */}
        {result.common_cause?.included && (
          <p className="rbd-details-p">
            Includes the diagram's {result.common_cause.groups} common-cause
            group{result.common_cause.groups === 1 ? "" : "s"} in every figure
            {result.common_cause.availability_without_common_cause != null && (
              <> — without {result.common_cause.groups === 1 ? "it" : "them"} the long-run availability would
                be {pctOf(result.common_cause.availability_without_common_cause)}</>
            )}.
          </p>
        )}
        {safety && !result.common_cause?.included && result.common_cause?.availability_with_common_cause != null && (
          <p className="rbd-details-p">
            {pctOf(result.common_cause.availability_with_common_cause)} with the common-cause groups (1 − PFDavg).
            The availability figures here leave them out.
          </p>
        )}
        {safety && <SafetyNotes safety={safety} />}

        {blocks.length > 0 && impCols.length > 0 && (
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

        {exactOk && (
          <DowntimeBars
            rows={exact.per_node}
            title="Each block's own downtime over the window"
            note={
              "Each block's share of the blocks' own expected downtime. A redundant block can be down " +
              "without taking the system down: its share of the system's downtime is under Block importance."
            }
          />
        )}
        {!exactOk && <DowntimeBars rows={simPer} title="Simulated share of downtime" />}
        {exactOk && (
          <p className="rbd-details-p">
            Figures over time are computed {fromNow ? "from the blocks' states now" : "with every block new at the start"}
            {steady != null && chartOk && !pfdChart ? "; the dashed line on the chart is the long-run availability" : ""}
            {pfdChart ? "; the dashed line on the chart is the PFDavg, the dotted one the SIL limit" : ""}
            {sameWindow && !pfdChart ? "; the grey line is the simulation's estimate over the same window" : ""}.
            {exact.cost_note ? ` No exact cost: ${exact.cost_note}` : ""}
          </p>
        )}
        {(exactOk && result.proof_test_note) && <p className="rbd-details-p">{result.proof_test_note}</p>}
        {pfdChart && sameWindow && <SimulatedChart curve={curve} unit={unit} />}

        <DowntimeSplit result={result} unit={unit} />
        <AvailabilityCosts result={result} unit={unit} />
        <AvailabilityPolicies result={result} />

        {hasSim ? (
          <div className="rbd-sim">
            <div className="ds-section-h">
              Simulation{result.current_state ? " from now" : ""}
            </div>
            <RbdNextFailure result={result} unit={unit} />
            {exactOk && <DowntimeBars rows={simPer} title="Simulated share of downtime" />}
            {/* With no exact curve the simulated one is the chart above. */}
            {chartOk && !sameWindow && <SimulatedChart curve={curve} unit={unit} />}
            <p className="rbd-details-p">
              {result.quick ? "Quick estimate: availability" : "Availability"} curve estimated by{" "}
              {result.n_simulations?.toLocaleString()} Monte-Carlo
              replications{result.precision?.antithetic ? " (in antithetic pairs)" : ""}
              {result.quick && result.time_budget_s ? `, a quick run of at most ${fmt3(result.time_budget_s)} s,` : ""}{" "}
              over {fmt(result.t_simulation)}{u}
              {curve?.lower?.length && !sameWindow ? `, with a ${Math.round((curve.confidence || 0.95) * 100)}% confidence band` : ""}.
              {precisionNote(result)}
              {result.horizon_shortened && " The window was shortened to keep the simulation quick; the long-run figures don't depend on it."}
            </p>
          </div>
        ) : !needsSim && onSimulate ? (
          <div className="rbd-sim">
            <div className="ds-section-h">Simulation</div>
            <p className="rbd-details-p">
              A Monte-Carlo simulation adds the spread of outcomes: the chance of no outage, percentiles,
              criticality indices (which block trips the system, which restores it) and a confidence band.
              {fromNow && " From now, it also gives the time to the next system failure, its mean residual life and its likely cause."}
            </p>
            <SimulationActions {...simulateProps} />
          </div>
        ) : null}

        {routes.length > 0 && (
          <details className="rbd-routes">
            <summary>How each figure is computed</summary>
            <ul>
              {routes.map(([k, r]) => (
                <li key={k}>
                  <code>{k}</code> {r.route === "refused" ? "not available" : r.route} — {r.reason}
                </li>
              ))}
            </ul>
          </details>
        )}
        {more}
      </ResultDetails>
      {!needsSim && <p className="rbd-method-line">{methodLine(result, exactOk, hasSim)}</p>}
    </div>
  );
}

// Details' two-column list of figures, with a hover note where there is one.
function ResultDetailsRows({ rows }) {
  return (
    <dl className="rs-dl">
      {rows.map((r) => (
        <div key={r.label} title={r.title}>
          <dt>{r.label}</dt>
          <dd>{r.value}</dd>
        </div>
      ))}
    </dl>
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

// Window presets for a repairable diagram (#311), in hours.
const WINDOW_PRESETS = [
  { id: "month", label: "1 month", hours: 730 },
  { id: "year", label: "1 year", hours: 8760 },
  { id: "5y", label: "5 years", hours: 43800 },
];

export default function RbdCalculator({ graph, validation, stale, onValidate = null, rbdId = null, name = null, onBuild }) {
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
  const [checking, setChecking] = useState(false); // validating before a calculation
  const [top, setTop] = useState({ pending: true }); // What to improve's top lever, for the answer card

  const unitLabel = graph.unit ? ` (${graph.unit})` : "";
  // Calculate validates first when the diagram hasn't been checked (#300), so
  // it's only held back by a check that failed.
  const blocked = !!validation && !stale && !validation.can_calculate;
  const hpu = hoursPerUnit(graph.unit);

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

  // The window preset the "Window" control shows, and the automatic window
  // in years (#300: "auto" chose 35,521 h when a year was wanted).
  const windowPreset = tMax === "" || tMaxAuto
    ? "long"
    : (hpu && WINDOW_PRESETS.find((w) => Math.abs(Number(tMax) * hpu - w.hours) < 1e-6 * w.hours)?.id) || null;
  const autoWindow = (() => {
    const w = result?.kind === "repairable" ? result.exact?.window ?? result.t_simulation : null;
    if (!w || !hpu || !(tMax === "" || tMaxAuto)) return null;
    const years = (w * hpu) / 8760;
    return `≈ ${formatNumber(years, { sig: 2 })} year${years === 1 ? "" : "s"}`;
  })();
  // The window the shown result was calculated over, in words; null for the long run.
  const sentWindowLabel = (() => {
    let t = null;
    try {
      t = calcSig ? JSON.parse(calcSig).t : null;
    } catch {
      t = null;
    }
    if (t == null) return null;
    const p = hpu && WINDOW_PRESETS.find((w) => Math.abs(t * hpu - w.hours) < 1e-6 * w.hours);
    return p ? p.label : `${formatNumber(t)}${graph.unit ? ` ${unitInText(graph.unit)}` : ""}`;
  })();

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

  // Validate first when the diagram hasn't been checked since it changed
  // (#300: the check is lost on save, and the Builder tab was the only way).
  const calculate = async (force = false, opts = {}) => {
    let v = validation;
    if ((!v || stale) && onValidate) {
      setChecking(true);
      try {
        v = await onValidate();
      } finally {
        setChecking(false);
      }
    }
    if (!v?.can_calculate) return;
    setTop({ pending: true });
    runCalculation(force, opts);
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
          // The next step until there's a current result; then the results'
          // own action (a simulation, say) is the primary one.
          className={result && !stale && !dirty ? "secondary" : ""}
          onClick={() => calculate(false)}
          disabled={blocked || checking || phase === "calculating"}
          title={blocked ? "Fix the diagram's problems first (below)" : "Check the diagram and calculate"}
        >
          {checking
            ? "Checking…"
            : phase === "calculating"
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

      {covNodes.length > 0 && (
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

      {!graph.repairable && (
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

      {!graph.repairable && asOf && (
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

      {graph.repairable && (
        <div className="rbd-asof">
          <div className="calc-controls rbd-calc-inputs rbd-window">
            {hpu && (
              <SegmentedControl
                label={asOf ? "Window from now" : "Window"}
                showLabel
                value={windowPreset}
                onChange={(v) => {
                  const p = WINDOW_PRESETS.find((w) => w.id === v);
                  setTMax(p ? String(Number((p.hours / hpu).toPrecision(6))) : "");
                  setTMaxAuto(!p);
                }}
                options={[
                  ...WINDOW_PRESETS.map((w) => ({ value: w.id, label: w.label })),
                  { value: "long", label: "Long run", title: "The long-run (steady-state) availability; figures over time use an automatic window" },
                ]}
              />
            )}
            <label className="calc-t">
              <span>{hpu ? `Or a window${unitLabel}` : asOf ? `Next${unitLabel} — window from now` : `Window${unitLabel}`}</span>
              <input
                type="number"
                min="0"
                step="any"
                placeholder={autoWindow ? `auto (${autoWindow})` : "auto"}
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

      {/* The check shows here only when it has something to say (#313):
          problems, or warnings. */}
      {validation && !stale && (!validation.can_calculate || validation.warnings?.length > 0) && (
        <ValidationPanel validation={validation} stale={false} />
      )}

      {result && stale && phase !== "calculating" && !checking && (
        <p className="hint">The diagram has changed since these results: recalculate to update them.</p>
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
          windowLabel={sentWindowLabel}
          top={top}
          improve={<WhatToImprove graph={graph} rbdId={rbdId} result={result} onTop={setTop} />}
          more={<AvailabilityCompare graph={graph} rbdId={rbdId} result={result} />}
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
