import { useEffect, useState } from "react";
import Select from "./Select.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { getModel, listModels } from "../api.js";
import { betaSource } from "../requirement.js";
import "./Requirement.css";

// "Use β from a saved model" in the demonstration test (#295): pick a saved
// Weibull model, see its β and 95% interval, and plan with the estimate or
// the conservative lower bound. ``source`` is { name, estimate, lower,
// upper, modelId? } or null; ``onSource(source, unit)`` sets it (null clears
// it); ``bound`` is "estimate" | "lower".

// β with three figures, keeping a decimal: 1.0, 2.08, 5.1.
export function fmtBeta(v) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  const s = Number(Number(v).toPrecision(3)).toString();
  return s.includes(".") || s.includes("e") ? s : `${s}.0`;
}

const isWeibull = (m) => m.kind === "distribution" && /^weibull$/i.test(String(m.distribution || "").trim());

export default function DemoShapeSource({ source, onSource, bound, onBound }) {
  const [picking, setPicking] = useState(false);
  const [models, setModels] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!picking || models) return;
    listModels()
      .then((d) => setModels((d.models || []).filter(isWeibull)))
      .catch((err) => setError(err.message));
  }, [picking, models]);

  const pick = async (id) => {
    setError(null);
    try {
      const full = await getModel(id);
      const src = betaSource(full.results, full.name, id);
      if (!src) throw new Error("That model has no Weibull shape β.");
      onSource(src, full.results?.unit || "");
      setPicking(false);
    } catch (err) {
      setError(err.message);
    }
  };

  if (source) {
    const hasCi = source.lower != null && source.upper != null;
    return (
      <div className="demo-beta">
        <p className="demo-beta-line">
          β from <b>{source.name}</b>: {fmtBeta(source.estimate)}
          {hasCi ? <>, 95% interval {fmtBeta(source.lower)}–{fmtBeta(source.upper)}</> : " (no interval)"}
          <button type="button" className="link demo-beta-clear" onClick={() => onSource(null)}>Don't use</button>
        </p>
        {hasCi && (
          <SegmentedControl
            label="Which β to plan with"
            size="sm"
            value={bound}
            onChange={onBound}
            options={[
              { value: "estimate", label: `Estimate ${fmtBeta(source.estimate)}` },
              { value: "lower", label: `Lower bound ${fmtBeta(source.lower)} (conservative)`,
                title: "The safe side when each unit runs longer than the mission" },
            ]}
          />
        )}
      </div>
    );
  }

  if (!picking) {
    return (
      <div className="demo-beta">
        <button type="button" className="link" onClick={() => setPicking(true)}>Use β from a saved model</button>
      </div>
    );
  }
  return (
    <div className="demo-beta">
      <div className="demo-beta-pick">
        <Select
          value=""
          onChange={pick}
          placeholder={models == null ? "Loading…" : models.length ? "Choose a Weibull model" : "No saved Weibull models"}
          disabled={!models?.length}
          options={(models || []).map((m) => ({ value: m.id, label: m.name }))}
        />
        <button type="button" className="link" onClick={() => setPicking(false)}>Cancel</button>
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
