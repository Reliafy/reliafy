import { useEffect, useId, useMemo, useState } from "react";
import { listModels, listReports, listStrategyAnalyses, listDegradationModels } from "../api.js";
import { EVIDENCE_KIND_LABEL, evidenceKinds, startKind } from "../rcmWorksheet.js";
import SegmentedControl from "./ui/SegmentedControl.jsx";

const VERDICT_LABEL = {
  random: "random ✓",
  wear_out: "wear-out",
  infant_mortality: "infant mortality",
  inconclusive: "no CI",
};

const KIND_HINT = {
  model: "Checked: the evidence check says whether it supports the decision.",
  report: "Linked, not checked: the evidence check shows “Report linked” with a link to open it.",
  working: "The notes and rationale of a function on this tree, where the working behind its performance standard is written. Linked, not checked: the evidence check shows “Notes linked” with a link to open them.",
};

async function loadOptions(kind, expectedType, analysisKind) {
  if (kind === "report") {
    const { reports } = await listReports();
    return (reports || []).map((r) => ({
      id: r.id, label: r.title || "Untitled report",
      meta: `${r.sections?.length ?? 0} item${r.sections?.length === 1 ? "" : "s"}`,
    }));
  }
  if (expectedType === "model") {
    const { models } = await listModels();
    return models.map((m) => ({
      id: m.id,
      label: m.name,
      meta: m.distribution + (m.randomness?.verdict ? ` · β: ${VERDICT_LABEL[m.randomness.verdict] || m.randomness.verdict}` : ""),
    }));
  }
  if (expectedType === "strategy_analysis") {
    const { analyses } = await listStrategyAnalyses();
    // A failure-finding task takes the Strategy tool's analysis or the task card's test interval.
    const kinds = analysisKind === "failure_finding" ? ["failure_finding", "failure_finding_interval"] : [analysisKind];
    const filtered = analysisKind ? analyses.filter((a) => kinds.includes(a.kind)) : analyses;
    return filtered.map((a) => ({ id: a.id, label: a.name, meta: a.headline }));
  }
  if (expectedType === "degradation_model") {
    const { models } = await listDegradationModels();
    return models.map((m) => ({
      id: m.id,
      label: m.name,
      meta: `${m.path_model || ""} · threshold ${m.threshold}${m.measurement_unit ? " " + m.measurement_unit : ""}`,
    }));
  }
  return [];
}

// Picker for the evidence behind an RCM decision ({type, id} or null), in
// three kinds: Models (the model or analysis the outcome expects, checked;
// offered only when the decision expects one), Reports (the user's reports)
// and Function notes (the notes and rationale of the functions on this
// position: `workings`, [{id: the function's, label, meta}]). A report or notes are
// linked, not checked. Non-repairable models surface their randomness
// verdicts so users can pick a defensible one for RTF decisions.
export default function EvidencePicker({ expectedType, analysisKind, value, onChange, workings = [] }) {
  const kinds = evidenceKinds(expectedType);
  // Its own radio group: a combination's dialog shows a picker per task.
  const group = useId();
  const [kind, setKind] = useState(() => startKind(value, expectedType));
  const shown = kinds.includes(kind) ? kind : kinds[0];
  const [options, setOptions] = useState(null);

  useEffect(() => {
    if (shown === "working") return undefined;
    let cancelled = false;
    setOptions(null);
    loadOptions(shown, expectedType, analysisKind)
      .then((o) => { if (!cancelled) setOptions(o); })
      .catch(() => { if (!cancelled) setOptions([]); });
    return () => { cancelled = true; };
  }, [shown, expectedType, analysisKind]);

  const list = useMemo(() => {
    if (shown !== "working") return options;
    // The working linked now stays offered even when it's on another position.
    const linked = value?.type === "working" && !workings.some((w) => w.id === value.id)
      ? [{ id: value.id, label: "The function's notes linked now", meta: "" }] : [];
    return [...linked, ...workings];
  }, [shown, options, workings, value]);

  const typeOf = (k) => (k === "model" ? expectedType : k);
  const chosen = value && value.type === typeOf(shown) ? value.id : null;
  const empty = {
    model: {
      model: "non-repairable models (fit one under Models)",
      strategy_analysis: analysisKind === "failure_finding"
        ? "saved failure-finding analyses (run the Strategy tool and save it)"
        : "saved replacement analyses (run Optimal replacement and save it)",
      degradation_model: "degradation models (create one under Model → Degradation)",
    }[expectedType],
    report: "reports yet (make one under Reports)",
    working: "function notes on this position yet (write a function's notes and rationale first)",
  }[shown];

  return (
    <div className="evidence-kinds">
      <SegmentedControl size="sm" label="Kind of evidence" value={shown} onChange={setKind}
                        options={kinds.map((k) => ({ value: k, label: EVIDENCE_KIND_LABEL[k] }))} />
      <p className="option-hint">{KIND_HINT[shown]}</p>
      {list === null ? <p className="muted-line">Loading evidence options…</p>
        : list.length === 0 ? <p className="muted-line">No {empty}</p> : (
          <div className="evidence-picker" role="radiogroup" aria-label={EVIDENCE_KIND_LABEL[shown]}>
            {list.map((o) => (
              <label key={o.id} className={"evidence-option" + (chosen === o.id ? " selected" : "")}>
                <input
                  type="radio"
                  name={`evidence-${group}`}
                  checked={chosen === o.id}
                  onChange={() => onChange({ type: typeOf(shown), id: o.id })}
                />
                <span className="evidence-name">{o.label}</span>
                <span className="evidence-meta">{o.meta}</span>
              </label>
            ))}
          </div>
        )}
      {value && (
        <button type="button" className="link sm" onClick={() => onChange(null)}>Unlink the evidence</button>
      )}
    </div>
  );
}
