import Select from "./Select.jsx";
import { useEffect, useMemo, useState } from "react";
import { getDistributions, listModels, getModel } from "../api.js";

// Inline life-model picker: choose a saved (plain-distribution) model or enter
// parameters. Emits the model object (same shape used on RBD nodes) via
// onChange, or null when the selection is incomplete.
export default function ModelPicker({ label, value, onChange }) {
  const [source, setSource] = useState(value?.source === "saved" ? "saved" : "params");
  const [dists, setDists] = useState([]);
  const [saved, setSaved] = useState([]);
  const [distId, setDistId] = useState(
    value?.source === "params" ? value.distribution_id : "weibull"
  );
  const [pvals, setPvals] = useState(() =>
    Object.fromEntries(
      (value?.source === "params" ? value.params || [] : []).map((p) => [p.name, p.value])
    )
  );
  const [savedId, setSavedId] = useState(
    value?.source === "saved" ? value.modelId : ""
  );

  useEffect(() => {
    getDistributions()
      // Manual-parameter entry only makes sense for plain parametric
      // distributions — not "best" (a selector) or non-parametric (no params).
      .then((d) => setDists(d.distributions.filter((x) => !x.covariates && !x.nonparametric && x.id !== "best")))
      .catch(() => {});
    // Include proportional-hazards (regression) models: they can't be entered
    // as plain parameters, but a node can reference a saved one and supply
    // covariate values on the calculator.
    listModels()
      .then((d) => setSaved(d.models))
      .catch(() => {});
  }, []);

  const dist = useMemo(() => dists.find((d) => d.id === distId), [dists, distId]);

  const emitParams = (id, values) => {
    const d = dists.find((x) => x.id === id);
    const names = d?.params || [];
    const ok =
      names.length &&
      names.every(
        (p) => values[p] !== "" && values[p] !== undefined && !Number.isNaN(Number(values[p]))
      );
    onChange(
      ok
        ? {
            source: "params",
            distribution: d.name,
            distribution_id: d.id,
            params: names.map((p) => ({ name: p, value: Number(values[p]) })),
          }
        : null
    );
  };

  const onPickSaved = async (id) => {
    setSavedId(id);
    if (!id) return onChange(null);
    try {
      const full = await getModel(id);
      const r = full.results || {};
      onChange({
        source: "saved",
        kind: full.kind,
        modelId: id,
        name: full.name,
        distribution: r.distribution,
        distribution_id: r.distribution_id,
        params: r.params || [],
        // Extra fitted quantities (offset/LFP/ZI) so calculators rebuild the
        // model exactly as it was fitted.
        extras: r.extras || null,
        // Covariate field definitions for proportional-hazards models; the RBD
        // calculator prompts for these values.
        covariates: (r.functions && r.functions.covariates) || [],
        unit: r.unit || "",
      });
    } catch {
      onChange(null);
    }
  };

  return (
    <div className="picker">
      {label && <div className="picker-label">{label}</div>}
      <div className="seg picker-seg">
        <button
          type="button"
          className={"seg-btn" + (source === "params" ? " active" : "")}
          onClick={() => {
            setSource("params");
            emitParams(distId, pvals);
          }}
        >
          Parameters
        </button>
        <button
          type="button"
          className={"seg-btn" + (source === "saved" ? " active" : "")}
          onClick={() => {
            setSource("saved");
            onPickSaved(savedId);
          }}
        >
          Saved model
        </button>
      </div>

      {source === "params" ? (
        <>
          <label className="dist-field" style={{ maxWidth: 280 }}>
            <span className="dist-label">Distribution</span>
            <Select
              value={distId}
              onChange={(id) => {
                setDistId(id);
                setPvals({});
                onChange(null);
              }}
              options={dists.map((d) => ({ value: d.id, label: d.name }))}
            />
          </label>
          <div className="param-fields">
            {(dist?.params || []).map((p) => (
              <label className="param-field" key={p}>
                <span>{p}</span>
                <input
                  type="number"
                  step="any"
                  value={pvals[p] ?? ""}
                  onChange={(e) => {
                    const next = { ...pvals, [p]: e.target.value };
                    setPvals(next);
                    emitParams(distId, next);
                  }}
                />
              </label>
            ))}
          </div>
        </>
      ) : saved.length === 0 ? (
        <p className="muted-line">No saved distribution models yet.</p>
      ) : (
        <label className="dist-field" style={{ maxWidth: 320 }}>
          <span className="dist-label">Model</span>
          <Select
            value={savedId}
            onChange={onPickSaved}
            placeholder="— choose —"
            options={[
              { value: "", label: "— choose —" },
              ...saved.map((m) => ({
                value: m.id,
                label: m.name,
                hint: m.distribution + (m.kind === "regression" ? ", covariates" : ""),
              })),
            ]}
          />
        </label>
      )}
    </div>
  );
}
