import Select from "./Select.jsx";

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
      fill: "tonexty", fillcolor: "rgba(15, 23, 42, 0.13)",
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
