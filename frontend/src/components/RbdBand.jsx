import { useState } from "react";
import Select from "./Select.jsx";
import { ResultDetails } from "./ui/ResultSummary.jsx";
import { formatNumber } from "../format.js";
import { BAND_FILL } from "../plotTheme.js";

// Confidence band on a non-repairable RBD's reliability (#103): the spread of
// the system reliability, MTTF and B-lives over draws of the fitted blocks'
// parameters (RePyability 0.9's parameter uncertainty). The backend returns
// `result.band` = { level, n_draws, sf_lower, sf_upper, mttf, blife,
// uncertain, fixed } when asked with { band: { level } }.

const LEVELS = [0.8, 0.9, 0.95, 0.99];
const pct = (level) => `${Math.round(level * 100)}%`;

const fmtLife = (v) =>
  v == null ? "beyond the axis" : Math.abs(v) >= 1e-4 || v === 0 ? Number(v.toPrecision(4)).toString() : v.toExponential(2);

// Toggle + level, shown with the calculator's other inputs.
export function BandControls({ value, onChange }) {
  return (
    <div className="calc-t rbd-band-controls">
      <span>Confidence band</span>
      <div className="rbd-band-row">
        <label className="rbd-band-toggle" title="Carry the uncertainty in blocks' fitted models through to the system">
          <input
            type="checkbox"
            checked={value.on}
            onChange={(e) => onChange({ ...value, on: e.target.checked })}
          />
          <span>{value.on ? "On" : "Off"}</span>
        </label>
        <Select
          className="rbd-band-level"
          value={value.level}
          disabled={!value.on}
          onChange={(level) => onChange({ ...value, level: Number(level) })}
          options={LEVELS.map((l) => ({ value: l, label: pct(l) }))}
          title="Confidence level"
        />
      </div>
    </div>
  );
}

// Whether a result carries a drawable band.
export const hasBand = (band) => !!band && Array.isArray(band.sf_lower) && Array.isArray(band.sf_upper);

// Shaded band traces for the system curve; put them before the system trace.
export function bandTraces(band, x, active) {
  if (!hasBand(band)) return [];
  const flip = (a) => a.map((v) => (v == null ? null : 1 - v));
  const lower = active === "sf" ? band.sf_lower : flip(band.sf_upper);
  const upper = active === "sf" ? band.sf_upper : flip(band.sf_lower);
  return [
    { x, y: lower, mode: "lines", type: "scatter", line: { width: 0 }, hoverinfo: "skip", showlegend: false },
    {
      x, y: upper, mode: "lines", type: "scatter", line: { width: 0 },
      fill: "tonexty", fillcolor: BAND_FILL,
      name: `${pct(band.level)} confidence band`, hoverinfo: "skip",
    },
  ];
}

// "95%: 115 – 168" under a headline figure.
export function BandInterval({ band, interval }) {
  if (!band || !interval || (interval.lower == null && interval.upper == null)) return null;
  return (
    <div className="rbd-band-iv" title={`${pct(band.level)} confidence interval from the fitted models' uncertainty`}>
      {pct(band.level)}: {fmtLife(interval.lower)} – {fmtLife(interval.upper)}
    </div>
  );
}

// Which blocks carried uncertainty, and which were treated as fixed (and why).
export function BandNote({ band }) {
  if (!band) return null;
  const uncertain = band.uncertain || [];
  const fixed = band.fixed || [];
  // Group the uncertain blocks by the saved model(s) they draw from.
  const byModel = new Map();
  for (const b of uncertain) {
    const key = (b.models || []).join(" + ") || "saved model";
    byModel.set(key, [...(byModel.get(key) || []), b.label]);
  }
  return (
    <div className="rbd-band-note" role="status">
      {uncertain.length === 0 ? (
        <p>
          <b>No confidence band:</b> no block uses a saved model fitted by maximum likelihood,
          so there is no parameter uncertainty to carry through. Pick saved fitted models for
          the blocks to see one.
        </p>
      ) : (
        <p>
          <b>Shaded: {pct(band.level)} confidence band</b> from {band.n_draws?.toLocaleString()} draws of
          the fitted models' parameters (from each fit's covariance). Blocks using the same saved
          model share each draw. Carrying uncertainty:{" "}
          {[...byModel].map(([model, labels]) => `${labels.join(", ")} (${model})`).join(" · ")}.
        </p>
      )}
      {fixed.length > 0 && (
        <p>
          Treated as fixed: {fixed.map((b) => `${b.label} — ${b.reason}`).join(" · ")}.
        </p>
      )}
    </div>
  );
}

// Intervals at several targets from the same draws (#325): B-lives (B1, B10,
// B50 by default) and the reliability at chosen times, each with its point
// value; editable when ``onChange`` is given ({b_lives, times}).
const listText = (xs) => (xs || []).map((v) => Number(v.toPrecision(6))).join(", ");
const parseList = (text) => text.split(/[\s,;]+/).filter(Boolean).map(Number);

export function BandTargets({ band, unit, onChange }) {
  const targets = band?.targets;
  const [bText, setBText] = useState(() => listText((targets?.b_lives || []).map((r) => r.fraction * 100)) || "1, 10, 50");
  const [tText, setTText] = useState(() => listText((targets?.reliability || []).map((r) => r.t)));
  if (!band || !(band.uncertain || []).length) return null;
  const b = parseList(bText);
  const ts = parseList(tText);
  const ok = b.length <= 8 && ts.length <= 8 && b.every((v) => v > 0 && v < 100) && ts.every((v) => v > 0);
  const u = unit ? ` ${unit.toLowerCase()}` : "";
  const rows = [
    ...(targets?.b_lives || []).map((r) => ({
      key: `b${r.fraction}`, label: `B${Number((r.fraction * 100).toPrecision(3))} life`,
      value: r.value == null ? "—" : `${formatNumber(r.value)}${u}`,
      iv: `${formatNumber(r.lower)} – ${r.upper == null ? "beyond" : formatNumber(r.upper)}`,
    })),
    ...(targets?.reliability || []).map((r) => ({
      key: `t${r.t}`, label: `R(${formatNumber(r.t)}${u})`,
      value: r.value == null ? "—" : `${(r.value * 100).toFixed(2)}%`,
      iv: r.lower == null ? "—" : `${(r.lower * 100).toFixed(2)}% – ${(r.upper * 100).toFixed(2)}%`,
    })),
  ];
  return (
    <ResultDetails summary="B-lives and reliability with intervals">
      {rows.length > 0 && (
        <div className="rbd-avail-imp-scroll">
          <table className="calc-table rbd-band-targets">
            <thead><tr><th>Target</th><th>Best estimate</th><th>{pct(band.level)} interval</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}><td className="calc-row-label">{r.label}</td><td>{r.value}</td><td>{r.iv}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {onChange && (
        <div className="param-fields rbd-band-target-inputs">
          <label className="param-field rbd-cost-field">
            <span>B-lives (% failed)</span>
            <input type="text" value={bText} onChange={(e) => setBText(e.target.value)} placeholder="1, 10, 50" />
          </label>
          <label className="param-field rbd-cost-field">
            <span>Reliability at times</span>
            <input type="text" value={tText} onChange={(e) => setTText(e.target.value)} placeholder="e.g. 500, 1000" />
            <small>{unit || "time"} · up to 8</small>
          </label>
          <button type="button" className="secondary" disabled={!ok} style={{ alignSelf: "flex-start", marginTop: 22 }}
                  onClick={() => onChange({ b_lives: b, times: ts })}>
            Update
          </button>
        </div>
      )}
      <p className="muted-line" style={{ margin: 0 }}>
        Every interval comes from the same {band.n_draws?.toLocaleString()} draws of the fitted models, in one run.
      </p>
    </ResultDetails>
  );
}
