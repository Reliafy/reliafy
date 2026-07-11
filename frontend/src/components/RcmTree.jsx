import { useState } from "react";
import { Link } from "react-router-dom";
import RcmStatusBadge from "./RcmStatusBadge.jsx";

const OUTCOME_LABEL = {
  on_condition: "On-condition",
  fixed_interval: "Fixed-interval",
  rtf: "Run-to-failure",
  failure_finding: "Failure-finding",
  redesign: "Redesign",
  accept: "Accept risk",
};
const CONSEQUENCE_LABEL = {
  safety: "Safety",
  environmental: "Environmental",
  operational: "Operational",
  non_operational: "Non-operational",
  hidden: "Hidden",
};

const newId = () =>
  (crypto.randomUUID ? crypto.randomUUID().replaceAll("-", "") : Math.random().toString(36).slice(2));

const PlusIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 5v14M5 12h14" />
  </svg>
);
const TrashIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13" />
  </svg>
);
const PencilIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
  </svg>
);
const Chevron = ({ open }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
    style={{ transform: open ? "rotate(90deg)" : "none", transition: "transform .12s" }}>
    <path d="m9 6 6 6-6 6" />
  </svg>
);

// Inline-editable node label: click the pencil (or the placeholder) to edit,
// Enter/blur to commit.
function NodeText({ text, placeholder, readOnly, onCommit }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(text || "");
  if (editing) {
    return (
      <input
        className="tree-edit"
        autoFocus
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => { setEditing(false); if (draft.trim()) onCommit(draft.trim()); }}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.target.blur();
          if (e.key === "Escape") { setDraft(text || ""); setEditing(false); }
        }}
      />
    );
  }
  return (
    <span className="tree-text">
      {text || <span className="tree-placeholder">{placeholder}</span>}
      {!readOnly && (
        <button className="act tree-pencil" title="Edit" onClick={() => { setDraft(text || ""); setEditing(true); }}>
          <PencilIcon />
        </button>
      )}
    </span>
  );
}

function DecisionChip({ mode, readOnly, onEdit }) {
  const d = mode.decision;
  if (!d) {
    return readOnly ? (
      <span className="decision-chip empty">No decision</span>
    ) : (
      <button className="decision-chip empty clickable" onClick={onEdit}>
        + Decision
      </button>
    );
  }
  let label = OUTCOME_LABEL[d.outcome] || d.outcome;
  if (d.interval != null) label += ` · ${d.interval} ${d.interval_unit || ""}`.trimEnd();
  return (
    <button
      className={"decision-chip" + (readOnly ? "" : " clickable")}
      onClick={readOnly ? undefined : onEdit}
      title={d.task || ""}
    >
      {label}
    </button>
  );
}

// Nested Function → Functional failure → Failure mode worksheet. Edits mutate
// the tree immutably and bubble up through onChange; the server only sees the
// tree when the study page saves it.
export default function RcmTree({ functions, readOnly, onChange, onEditDecision }) {
  const [collapsed, setCollapsed] = useState({});
  const toggle = (id) => setCollapsed((c) => ({ ...c, [id]: !c[id] }));

  const updateFn = (fnId, patch) =>
    onChange(functions.map((f) => (f.id === fnId ? { ...f, ...patch } : f)));
  const updateFailure = (fnId, failId, patch) =>
    onChange(functions.map((f) =>
      f.id !== fnId ? f : { ...f, failures: f.failures.map((x) => (x.id === failId ? { ...x, ...patch } : x)) }
    ));
  const updateMode = (fnId, failId, modeId, patch) =>
    onChange(functions.map((f) =>
      f.id !== fnId ? f : {
        ...f,
        failures: f.failures.map((x) =>
          x.id !== failId ? x : { ...x, modes: x.modes.map((m) => (m.id === modeId ? { ...m, ...patch } : m)) }
        ),
      }
    ));

  const addFunction = () =>
    onChange([...functions, { id: newId(), text: "", failures: [] }]);
  const addFailure = (fnId) =>
    updateFn(fnId, { failures: [...functions.find((f) => f.id === fnId).failures, { id: newId(), text: "", modes: [] }] });
  const addMode = (fnId, failId) => {
    const fail = functions.find((f) => f.id === fnId).failures.find((x) => x.id === failId);
    updateFailure(fnId, failId, {
      modes: [...fail.modes, { id: newId(), text: "", consequence: null, decision: null }],
    });
  };

  const removeFn = (fnId) => onChange(functions.filter((f) => f.id !== fnId));
  const removeFailure = (fnId, failId) =>
    updateFn(fnId, { failures: functions.find((f) => f.id === fnId).failures.filter((x) => x.id !== failId) });
  const removeMode = (fnId, failId, modeId) => {
    const fail = functions.find((f) => f.id === fnId).failures.find((x) => x.id === failId);
    updateFailure(fnId, failId, { modes: fail.modes.filter((m) => m.id !== modeId) });
  };

  return (
    <div className="rcm-tree">
      {functions.length === 0 && (
        <p className="muted-line">
          Start with a function — what the system must do, ideally with a performance standard.
        </p>
      )}

      {functions.map((fn) => (
        <div key={fn.id} className="tree-fn">
          <div className="tree-row fn-row">
            <button className="tree-chevron" onClick={() => toggle(fn.id)} aria-label="Toggle">
              <Chevron open={!collapsed[fn.id]} />
            </button>
            <span className="tree-tag fn-tag">Function</span>
            <NodeText
              text={fn.text}
              placeholder="e.g. Stop the vehicle within 30 m from 60 km/h"
              readOnly={readOnly}
              onCommit={(text) => updateFn(fn.id, { text })}
            />
            {!readOnly && (
              <div className="lib-acts">
                <button className="act del" title="Delete function" onClick={() => removeFn(fn.id)}>
                  <TrashIcon />
                </button>
              </div>
            )}
          </div>

          {!collapsed[fn.id] && (
            <div className="tree-children">
              {fn.failures.map((fail) => (
                <div key={fail.id} className="tree-fail">
                  <div className="tree-row fail-row">
                    <button className="tree-chevron" onClick={() => toggle(fail.id)} aria-label="Toggle">
                      <Chevron open={!collapsed[fail.id]} />
                    </button>
                    <span className="tree-tag fail-tag">Functional failure</span>
                    <NodeText
                      text={fail.text}
                      placeholder="e.g. Unable to stop within 30 m"
                      readOnly={readOnly}
                      onCommit={(text) => updateFailure(fn.id, fail.id, { text })}
                    />
                    {!readOnly && (
                      <div className="lib-acts">
                        <button className="act del" title="Delete failure" onClick={() => removeFailure(fn.id, fail.id)}>
                          <TrashIcon />
                        </button>
                      </div>
                    )}
                  </div>

                  {!collapsed[fail.id] && (
                    <div className="tree-children">
                      {fail.modes.map((mode) => {
                        const d = mode.decision;
                        return (
                          <div key={mode.id} className="tree-mode">
                            <div className="tree-row mode-row">
                              <span className="tree-tag mode-tag">Mode</span>
                              <NodeText
                                text={mode.text}
                                placeholder="e.g. Brake pads worn below minimum"
                                readOnly={readOnly}
                                onCommit={(text) => updateMode(fn.id, fail.id, mode.id, { text })}
                              />
                              {mode.consequence && (
                                <span className="consequence-chip">{CONSEQUENCE_LABEL[mode.consequence]}</span>
                              )}
                              <DecisionChip
                                mode={mode}
                                readOnly={readOnly}
                                onEdit={() => onEditDecision(fn.id, fail.id, mode)}
                              />
                              {d?.status !== undefined && <RcmStatusBadge status={d?.status} />}
                              {!readOnly && (
                                <div className="lib-acts">
                                  <button className="act del" title="Delete mode" onClick={() => removeMode(fn.id, fail.id, mode.id)}>
                                    <TrashIcon />
                                  </button>
                                </div>
                              )}
                            </div>
                            {(d?.summary || d?.reason || d?.artifact_name) && (
                              <div className="mode-evidence">
                                {d.artifact_name && d.artifact_link_path && (
                                  <Link to={d.artifact_link_path} className="evidence-link">
                                    {d.artifact_name}
                                  </Link>
                                )}
                                <span className="evidence-reason">{d.summary || d.reason}</span>
                              </div>
                            )}
                          </div>
                        );
                      })}
                      {!readOnly && (
                        <button className="tree-add" onClick={() => addMode(fn.id, fail.id)}>
                          <PlusIcon /> Failure mode
                        </button>
                      )}
                    </div>
                  )}
                </div>
              ))}
              {!readOnly && (
                <button className="tree-add" onClick={() => addFailure(fn.id)}>
                  <PlusIcon /> Functional failure
                </button>
              )}
            </div>
          )}
        </div>
      ))}

      {!readOnly && (
        <button className="tree-add tree-add-fn" onClick={addFunction}>
          <PlusIcon /> Function
        </button>
      )}
    </div>
  );
}
