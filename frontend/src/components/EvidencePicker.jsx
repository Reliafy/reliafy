import { useEffect, useId, useMemo, useState } from "react";
import { linkPositionModel, listEvidenceCandidates, listModels, listPositionModels, listReports, listStrategyAnalyses,
  listDegradationModels } from "../api.js";
import { attachedFor } from "../explorerModels.js";
import { evidenceBody, filterCandidates, groupByScope, kindOptions, windowFrom, windowWords } from "../evidenceCandidates.js";
import { EVIDENCE_KIND_LABEL, evidenceKinds, startKind } from "../rcmWorksheet.js";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import Field from "./ui/Field.jsx";
import { TextInput } from "./ui/Controls.jsx";
import Button from "./ui/Button.jsx";
import Select from "./Select.jsx";

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
  found: "What's on record for this failure mode, this position and its class. A model or a saved analysis is checked against the decision; a history, readings or a failure report is linked, not checked.",
};

// A life model offered beside the saved analyses an interval expects: linked, not checked.
const LIFE_MODEL_META = "Life model: linked, not checked";
const lifeModelOption = (m) => ({
  id: m.id, type: "model", label: m.name,
  meta: [LIFE_MODEL_META, m.distribution].filter(Boolean).join(" · "),
});

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
    const out = filtered.map((a) => ({ id: a.id, label: a.name, meta: a.headline }));
    // The fitted life models too (after the analyses): the evidence many have before an analysis.
    if (analysisKind !== "failure_finding") {
      const { models } = await listModels().catch(() => ({ models: [] }));
      out.push(...(models || []).map(lifeModelOption));
    }
    return out;
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
// `positionId` (and `modeId`): the life models attached to the failure mode's position
// (the Modelling tab) are offered first among the models, those for this mode at the top;
// `onCandidate(option)` hears one attached for this very mode, which the dialog picks when nothing is linked yet.
// With a position, the first kind is Found here (FoundEvidence below): what's on record there,
// searched and filtered, with a fit limited to the lives fitted between two dates. Nothing is
// chosen for the user: with nothing linked, nothing is selected until they pick.
export default function EvidencePicker({ expectedType, analysisKind, value, onChange, workings = [], positionId = null, modeId = null }) {
  const kinds = [...(positionId ? ["found"] : []), ...evidenceKinds(expectedType)];
  // Its own radio group: a combination's dialog shows a picker per task.
  const group = useId();
  const [kind, setKind] = useState(() => startKind(value, expectedType, !!positionId));
  const shown = kinds.includes(kind) ? kind : kinds[0];
  const [options, setOptions] = useState(null);
  const [attached, setAttached] = useState([]);
  useEffect(() => {
    const lifeToo = expectedType === "strategy_analysis" && analysisKind !== "failure_finding";
    if (!positionId || (expectedType !== "model" && expectedType !== "degradation_model" && !lifeToo)) return undefined;
    let live = true;
    listPositionModels([positionId]).then((d) => {
      if (!live) return;
      // An interval's: the life models on this position, offered after the analyses (never its candidate).
      const got = attachedFor(d.links || [], { modeId, expectedType: lifeToo ? "model" : expectedType })
        .map((o) => (lifeToo ? { ...o, meta: [LIFE_MODEL_META, o.meta].join(" · ") } : o));
      setAttached(got); // offered first, never picked for the user
    }, () => {});
    return () => { live = false; };
  }, [positionId, modeId, expectedType, analysisKind]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (shown === "working" || shown === "found") return undefined;
    let cancelled = false;
    setOptions(null);
    loadOptions(shown, expectedType, analysisKind)
      .then((o) => { if (!cancelled) setOptions(o); })
      .catch(() => { if (!cancelled) setOptions([]); });
    return () => { cancelled = true; };
  }, [shown, expectedType, analysisKind]);

  const list = useMemo(() => {
    if (shown === "model" && options && attached.length) {
      // The position's own models first, then the rest of the library without them again;
      // an interval's analyses stay first, then the position's life models, then the rest.
      const ids = new Set(attached.map((a) => a.id));
      const rest = options.filter((o) => !ids.has(o.id));
      if (expectedType === "strategy_analysis") {
        return [...rest.filter((o) => o.type !== "model"), ...attached, ...rest.filter((o) => o.type === "model")];
      }
      return [...attached, ...rest];
    }
    if (shown !== "working") return options;
    // The working linked now stays offered even when it's on another position.
    const linked = value?.type === "working" && !workings.some((w) => w.id === value.id)
      ? [{ id: value.id, label: "The function's notes linked now", meta: "" }] : [];
    return [...linked, ...workings];
  }, [shown, options, workings, value, attached]);

  const typeOf = (k) => (k === "model" ? expectedType : k);
  const optType = (o) => o.type || typeOf(shown);
  const isChosen = (o) => !!value && value.id === o.id && value.type === optType(o);
  const empty = {
    model: {
      model: "non-repairable models (fit one under Models)",
      strategy_analysis: analysisKind === "failure_finding"
        ? "saved failure-finding analyses (run the Strategy tool and save it)"
        : "saved replacement analyses or life models (run Optimal replacement and save it, or fit a model)",
      degradation_model: "degradation models (create one under Model → Degradation)",
    }[expectedType],
    report: "reports yet (make one under Reports)",
    working: "function notes on this position yet (write a function's notes and rationale first)",
  }[shown];

  return (
    <div className="evidence-kinds">
      <SegmentedControl size="sm" label="Kind of evidence" value={shown} onChange={setKind}
                        options={kinds.map((k) => ({ value: k, label: EVIDENCE_KIND_LABEL[k] }))} />
      <p className="option-hint">{shown === "model" && expectedType === "strategy_analysis" && analysisKind !== "failure_finding"
        ? "A saved analysis is checked: the evidence check says whether it supports the interval. A life model is linked, not checked: it shows how the item fails."
        : KIND_HINT[shown]}</p>
      {shown === "found" ? (
        <FoundEvidence positionId={positionId} modeId={modeId} value={value} onChange={onChange} group={group} />
      ) : list === null ? <p className="muted-line">Loading evidence options…</p>
        : list.length === 0 ? <p className="muted-line">No {empty}</p> : (
          <div className="evidence-picker" role="radiogroup" aria-label={EVIDENCE_KIND_LABEL[shown]}>
            {list.map((o) => (
              <label key={`${optType(o)}:${o.id}`} className={"evidence-option" + (isChosen(o) ? " selected" : "")}>
                <input
                  type="radio"
                  name={`evidence-${group}`}
                  checked={isChosen(o)}
                  onChange={() => onChange({ type: optType(o), id: o.id })}
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

// Found here: the candidates for this position and failure mode (rcm_evidence.py), searched as you
// type and filtered by kind, grouped by where each is from. A failure history can be limited to the
// lives fitted between two dates, and "Fit a life model on part of the history" fits one on them
// (saved to Models, attached to the position for this mode) and picks it, its window kept with it.
function FoundEvidence({ positionId, modeId, value, onChange, group }) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(null);
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [reload, setReload] = useState(0);
  const [fit, setFit] = useState({ open: false, data: "position", since: "", until: "", busy: false, error: null });
  useEffect(() => {
    let live = true;
    setFailed(null);
    listEvidenceCandidates(positionId, modeId).then((d) => { if (live) setData(d); },
      (e) => { if (live) { setData({ candidates: [], kinds: [] }); setFailed(e.message || "It didn't load."); } });
    return () => { live = false; };
  }, [positionId, modeId, reload]);
  const shown = useMemo(() => filterCandidates(data?.candidates, q, kind), [data, q, kind]);
  const groups = groupByScope(shown);
  const chosen = (c) => !!value && value.type === c.type && value.id === c.id;
  const pick = (c) => onChange(evidenceBody({ type: c.type, id: c.id, window: c.window || null }));
  const picked = (data?.candidates || []).find(chosen) || null;
  const windowed = picked && picked.type === "history";
  const setWindow = (since, until) => onChange(evidenceBody({ ...value, window: windowFrom(since, until) }));
  const runFit = async () => {
    setFit((f) => ({ ...f, busy: true, error: null }));
    try {
      const link = await linkPositionModel(positionId, {
        fit: true, scope: fit.data, distribution: "weibull", window: windowFrom(fit.since, fit.until),
        ...(modeId ? { failure_mode_ids: [modeId] } : {}),
      });
      onChange(evidenceBody({ type: "model", id: link.model_id, window: link.source?.window || null }));
      setFit((f) => ({ ...f, busy: false, open: false }));
      setReload((n) => n + 1);
    } catch (e) {
      setFit((f) => ({ ...f, busy: false, error: e.message || "The fit didn't work." }));
    }
  };
  return (
    <div className="evidence-found">
      <div className="evidence-found-bar">
        <Field label="Search the evidence" labelHidden>
          <TextInput type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name, date or mode" />
        </Field>
        <Select ariaLabel="Kind of evidence" value={kind} onChange={setKind} options={kindOptions(data?.kinds)} />
      </div>
      {data === null ? <p className="muted-line">Finding what's on record…</p>
        : failed ? <p className="field-error" role="alert">Couldn't list the evidence: {failed}</p>
        : !groups.length ? (
          <p className="muted-line">{(data.candidates || []).length
            ? "Nothing matches the search: clear it or choose every kind."
            : "Nothing on record here yet: fit a model, save an analysis, record failures or readings, or file a failure report."}</p>
        ) : (
          <div className="evidence-picker" role="radiogroup" aria-label="Evidence found here">
            {groups.map((g) => (
              <div key={g.scope} className="evidence-group" role="group" aria-label={g.words}>
                <p className="evidence-group-head">{g.words}</p>
                {g.items.map((c) => (
                  <label key={`${c.type}:${c.id}`} className={"evidence-option" + (chosen(c) ? " selected" : "")}>
                    <input type="radio" name={`evidence-${group}`} checked={chosen(c)} onChange={() => pick(c)} />
                    <span className="evidence-name">{c.label}</span>
                    <span className="evidence-meta">{c.meta}</span>
                  </label>
                ))}
              </div>
            ))}
          </div>
        )}
      {windowed && (
        <fieldset className="evidence-window">
          <legend className="field-label">Only the lives fitted (optional)</legend>
          <div className="evidence-window-row">
            <Field label="From">
              <TextInput type="date" value={value?.window?.since || ""} onChange={(e) => setWindow(e.target.value, value?.window?.until || "")} />
            </Field>
            <Field label="To">
              <TextInput type="date" value={value?.window?.until || ""} onChange={(e) => setWindow(value?.window?.since || "", e.target.value)} />
            </Field>
          </div>
          {value?.window && <p className="option-hint">The rationale will say it rests on {windowWords(value.window)}.</p>}
        </fieldset>
      )}
      {value?.type === "model" && value.window && !windowed && (
        <p className="option-hint">This model was fitted on {windowWords(value.window)}; the rationale says so.</p>
      )}
      <details className="evidence-fit" open={fit.open} onToggle={(e) => { const open = e.currentTarget.open; setFit((f) => (f.open === open ? f : { ...f, open })); }}>
        <summary>Fit a life model on part of the history…</summary>
        <div className="evidence-fit-body">
          <ChoiceChips label="History" value={fit.data} onChange={(v) => setFit((f) => ({ ...f, data: v || "position" }))}
                       options={[{ value: "position", label: "This position's" }, { value: "class", label: "Its class's, pooled" }]} />
          <div className="evidence-window-row">
            <Field label="Lives fitted from" optional>
              <TextInput type="date" value={fit.since} onChange={(e) => setFit((f) => ({ ...f, since: e.target.value }))} />
            </Field>
            <Field label="To" optional>
              <TextInput type="date" value={fit.until} onChange={(e) => setFit((f) => ({ ...f, until: e.target.value }))} />
            </Field>
          </div>
          <p className="option-hint">A Weibull fitted only on the items that went in between these dates, saved to Models,
            attached here{modeId ? " for this failure mode" : ""} and picked as the evidence.</p>
          {fit.error && <p className="field-error" role="alert">{fit.error}</p>}
          <Button variant="secondary" size="sm" onClick={runFit} disabled={fit.busy} aria-busy={fit.busy || undefined}>
            {fit.busy ? "Fitting…" : "Fit and pick it"}
          </Button>
        </div>
      </details>
    </div>
  );
}
