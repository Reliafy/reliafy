import { useEffect, useMemo, useState } from "react";
import Select from "./Select.jsx";
import { getDistributions } from "../api.js";
import { modelMean, unitAbbr } from "./rbdModelText.js";
import { formatNumber } from "../format.js";
import { PARAMS, paramLabel } from "../paramLabels.js";
import "./RbdBlockOptions.css";

// A life of two failure modes in one population (#318) — early failures and
// wear-out, say — built in the block dialog: one distribution for both modes,
// each mode's parameters, and the share of units that fail by the first. It
// is the shape a saved mixture fit has (distribution_id "mixture", params
// numbered by mode with their weights), so the analysis treats both alike.

const BASES = ["weibull", "lognormal", "exponential", "gamma", "normal"];
// Each parameter in plain words (the shared labels, #299): [short, with the
// diagram's unit].
function paramLabels(base, name, unit) {
  return [PARAMS[base]?.[name]?.[0] || name, paramLabel(base, name, unit)];
}

export const isMixture = (model) => model?.distribution_id === "mixture";

// The mode's parameters and weights read back from a stored mixture.
function readModes(model) {
  const out = { 1: {}, 2: {} };
  for (const p of model?.params || []) {
    const m = /^(.+?)(\d+)$/.exec(p.name || "");
    if (m && out[m[2]]) out[m[2]][m[1]] = p.value;
  }
  return out;
}

export function mixtureMean(model) {
  if (!isMixture(model)) return null;
  const modes = readModes(model);
  let total = 0;
  for (const j of [1, 2]) {
    const { weight, ...rest } = modes[j];
    const mean = modelMean({
      distribution_id: model.base_distribution_id,
      params: Object.entries(rest).map(([name, value]) => ({ name, value })),
    });
    if (mean == null || weight == null) return null;
    total += Number(weight) * mean;
  }
  return Number.isFinite(total) ? total : null;
}

// ``on`` shows the builder; the checkbox above it switches it. ``onChange``
// gets the mixture life (or null while it's incomplete).
export default function RbdMixtureBuilder({ on, onToggle, initial, onChange, unit }) {
  const start = isMixture(initial) && initial.source !== "saved" ? initial : null;
  const [dists, setDists] = useState([]);
  const [base, setBase] = useState(start?.base_distribution_id || "weibull");
  const [modes, setModes] = useState(() => {
    const m = readModes(start);
    return { 1: m[1], 2: m[2] };
  });
  const [share, setShare] = useState(() => {
    const w = Number(readModes(start)[1].weight);
    return Number.isFinite(w) && w > 0 ? Math.round(w * 1000) / 10 : 20;
  });

  useEffect(() => {
    if (!on || dists.length) return;
    getDistributions()
      .then((d) => setDists((d.distributions || []).filter((x) => BASES.includes(x.id))))
      .catch(() => {});
  }, [on, dists.length]);

  const dist = useMemo(() => dists.find((d) => d.id === base), [dists, base]);
  const names = dist?.params || [];
  const w1 = Number(share) / 100;
  const validShare = Number.isFinite(w1) && w1 > 0 && w1 < 1;

  const model = useMemo(() => {
    if (!dist || !validShare) return null;
    const params = [];
    for (const j of [1, 2]) {
      for (const n of names) {
        const v = modes[j][n];
        if (v === "" || v == null || !Number.isFinite(Number(v))) return null;
        params.push({ name: `${n}${j}`, value: Number(v) });
      }
      params.push({ name: `weight${j}`, value: j === 1 ? w1 : 1 - w1 });
    }
    return {
      source: "params",
      distribution: `${dist.name} mixture (2 components)`,
      distribution_id: "mixture",
      base_distribution_id: base,
      mixture: 2,
      params,
    };
  }, [dist, names, modes, base, w1, validShare]);

  useEffect(() => {
    if (on) onChange(model);
  }, [on, model]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (j, n, v) => setModes((m) => ({ ...m, [j]: { ...m[j], [n]: v } }));
  const mean = mixtureMean(model);
  const u = unitAbbr(unit);

  return (
    <div className="rbd-mix">
      <label className="rbd-instant-repair" title="Some units fail early (a weak batch, say) and the rest wear out: two failure modes, each with its own life.">
        <input type="checkbox" checked={on} onChange={(e) => onToggle(e.target.checked)} />
        Two failure modes <span className="muted">— a mixture, e.g. early failures and wear-out</span>
      </label>
      {on && (
        <>
          <label className="dist-field" style={{ maxWidth: 280 }}>
            <span className="dist-label">Distribution of each mode</span>
            <Select
              value={base}
              onChange={(id) => { setBase(id); setModes({ 1: {}, 2: {} }); }}
              options={dists.map((d) => ({ value: d.id, label: d.name }))}
            />
          </label>
          {[1, 2].map((j) => (
            <fieldset className="rbd-mix-mode" key={j}>
              <legend>Mode {j}</legend>
              <div className="param-fields">
                {names.map((n) => {
                  const [short, full] = paramLabels(base, n, unit);
                  return (
                    <label className="param-field" key={n}>
                      <span>{full}</span>
                      <input type="number" step="any" value={modes[j][n] ?? ""} aria-label={`Mode ${j} ${short}`}
                             onChange={(e) => set(j, n, e.target.value)} />
                    </label>
                  );
                })}
                {j === 1 ? (
                  <label className="param-field" title="The share of units that fail by this mode.">
                    <span>Share of units (%)</span>
                    <input type="number" step="any" min="0" max="100" value={share} aria-label="Mode 1 share of units"
                           onChange={(e) => setShare(e.target.value)} />
                  </label>
                ) : (
                  <div className="param-field rbd-mix-rest">
                    <span>Share of units (%)</span>
                    <output>{validShare ? formatNumber(100 - Number(share)) : "—"}</output>
                  </div>
                )}
              </div>
            </fieldset>
          ))}
          {!validShare && <p className="hint">The first mode's share must be between 0 and 100%.</p>}
          {mean != null && (
            <p className="rbd-dlg-echo">Mean life {formatNumber(mean)}{u ? ` ${u}` : ""}</p>
          )}
        </>
      )}
    </div>
  );
}
