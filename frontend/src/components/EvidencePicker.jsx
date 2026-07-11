import { useEffect, useState } from "react";
import { listModels, listStrategyAnalyses, listDegradationModels } from "../api.js";

const VERDICT_LABEL = {
  random: "random ✓",
  wear_out: "wear-out",
  infant_mortality: "infant mortality",
  inconclusive: "no CI",
};

// Picker for the analysis backing an RCM decision, filtered to the evidence
// type the chosen outcome expects. Life models surface their randomness
// verdicts so users can pick a defensible one for RTF decisions.
export default function EvidencePicker({ expectedType, analysisKind, value, onChange }) {
  const [options, setOptions] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        if (expectedType === "model") {
          const { models } = await listModels();
          if (!cancelled) {
            setOptions(models.map((m) => ({
              id: m.id,
              label: m.name,
              meta: m.distribution + (m.randomness?.verdict ? ` · β: ${VERDICT_LABEL[m.randomness.verdict] || m.randomness.verdict}` : ""),
            })));
          }
        } else if (expectedType === "strategy_analysis") {
          const { analyses } = await listStrategyAnalyses();
          const filtered = analysisKind ? analyses.filter((a) => a.kind === analysisKind) : analyses;
          if (!cancelled) {
            setOptions(filtered.map((a) => ({ id: a.id, label: a.name, meta: a.headline })));
          }
        } else if (expectedType === "degradation_model") {
          const { models } = await listDegradationModels();
          if (!cancelled) {
            setOptions(models.map((m) => ({
              id: m.id,
              label: m.name,
              meta: `${m.path_model || ""} · threshold ${m.threshold}${m.measurement_unit ? " " + m.measurement_unit : ""}`,
            })));
          }
        } else {
          setOptions([]);
        }
      } catch {
        if (!cancelled) setOptions([]);
      }
    };
    setOptions(null);
    load();
    return () => { cancelled = true; };
  }, [expectedType, analysisKind]);

  if (!expectedType) return null;
  if (options === null) return <p className="muted-line">Loading evidence options…</p>;
  if (options.length === 0) {
    const what = {
      model: "life models (fit one under Modelling)",
      strategy_analysis: analysisKind === "failure_finding"
        ? "saved failure-finding analyses (run the Strategy tool and save it)"
        : "saved replacement analyses (run Optimal replacement and save it)",
      degradation_model: "degradation models (create one under Modelling → Degradation)",
    }[expectedType];
    return <p className="muted-line">No {what} available yet.</p>;
  }

  return (
    <div className="evidence-picker">
      {options.map((o) => (
        <label key={o.id} className={"evidence-option" + (value === o.id ? " selected" : "")}>
          <input
            type="radio"
            name="evidence"
            checked={value === o.id}
            onChange={() => onChange(o.id)}
          />
          <span className="evidence-name">{o.label}</span>
          <span className="evidence-meta">{o.meta}</span>
        </label>
      ))}
    </div>
  );
}
