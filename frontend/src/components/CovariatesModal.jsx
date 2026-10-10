import Select from "./Select.jsx";
import { useEffect, useMemo, useState } from "react";
import Modal from "./Modal.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import RbdCovariateSchedule, { RbdSchedulePreview } from "./RbdCovariateSchedule.jsx";
import { withUnit } from "./stressName.js";
import { previewRbdSchedule } from "../api.js";
import { blockSchedules, draftFromSpec, initialTable, presetExpression } from "../rbdTvc.js";

const MODES = [
  { value: "constant", label: "Constant" },
  { value: "schedule", label: "Schedule" },
];

// Edit the covariates of every block backed by a covariate (regression)
// model. Each covariate is a constant value, or (#52) follows a schedule over
// the diagram's time, previewed live. Edits go into a draft and are only
// committed on Apply: constants feed the calculation, schedules are stored on
// their blocks (so they're saved with the diagram).
export default function CovariatesModal({
  covNodes, values, onApply, onClose, unit = "", tMax = null, repairable = false,
}) {
  const [draft, setDraft] = useState(values || {});
  const [modes, setModes] = useState(() => initial(covNodes, (spec) => (spec ? "schedule" : "constant")));
  const [drafts, setDrafts] = useState(() => initial(covNodes, (spec) => draftFromSpec(spec)));
  const [errors, setErrors] = useState({}); // {nodeId: message} from the previews
  // What the last preview said of each block: covariate ranges and its window.
  const [seen, setSeen] = useState({}); // {nodeId: {ranges: {name: [lo, hi]}, xMax}}

  // Each block's window and fitted ranges up front, for the presets' templates.
  useEffect(() => {
    let live = true;
    for (const node of covNodes) {
      if (!node.modelId || repairable) continue;
      previewRbdSchedule({ modelId: node.modelId, schedules: {}, constants: {}, tMax })
        .then((data) => live && remember(node.id, data))
        .catch(() => {});
    }
    return () => {
      live = false;
    };
    // Once, when the modal opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const remember = (nodeId, data) =>
    setSeen((prev) => ({
      ...prev,
      [nodeId]: {
        xMax: data.x[data.x.length - 1],
        ranges: Object.fromEntries(data.covariates.filter((c) => c.range).map((c) => [c.name, c.range])),
      },
    }));

  const get = (node, c) => draft[node.id]?.[c.name] ?? c.default;
  const set = (nodeId, name, value) =>
    setDraft((prev) => ({
      ...prev,
      [nodeId]: { ...(prev[nodeId] || {}), [name]: value },
    }));
  const setIn = (setter) => (nodeId, name, value) =>
    setter((prev) => ({ ...prev, [nodeId]: { ...(prev[nodeId] || {}), [name]: value } }));
  const setMode = setIn(setModes);
  const setSchedDraft = setIn(setDrafts);

  const chooseMode = (node, c, mode) => {
    setMode(node.id, c.name, mode);
    if (mode === "schedule" && !drafts[node.id]?.[c.name]) {
      setSchedDraft(
        node.id,
        c.name,
        c.type === "number"
          ? { expression: presetExpression("constant", c, { value: get(node, c) }) }
          : { table: initialTable(c, get(node, c)), period: "" }
      );
    }
  };

  const schedulesOf = (node) => blockSchedules(modes[node.id], drafts[node.id]);
  const blocked = covNodes.some((n) => schedulesOf(n) && errors[n.id]);

  const apply = () => {
    const schedules = {};
    for (const node of covNodes) schedules[node.id] = schedulesOf(node);
    onApply(draft, schedules);
  };

  const footer = (
    <>
      <span className="hint">
        {blocked ? "Fix the schedule above to apply." : "Constants feed the calculation; schedules are saved with the diagram."}
      </span>
      <div className="row" style={{ margin: 0 }}>
        <button className="secondary" onClick={onClose}>
          Cancel
        </button>
        <button onClick={apply} disabled={blocked}>
          Apply
        </button>
      </div>
    </>
  );

  return (
    <Modal title="Covariates" onClose={onClose} footer={footer} className="rbd-cov-modal">
      <p className="hint" style={{ marginTop: 0 }}>
        These blocks use covariate models. Set each covariate to a constant value, or a schedule over time.
      </p>
      {covNodes.map((node) => (
        <div className="rbd-cov-node" key={node.id}>
          <span className="rbd-cov-node-label">{node.label}</span>
          {node.covariates.map((c) => {
            const mode = modes[node.id]?.[c.name] || "constant";
            return (
              <div className="rbd-cov-row" key={c.name}>
                <div className="rbd-cov-row-head">
                  <span className="rbd-cov-name">{withUnit(c.name, c.unit)}</span>
                  <SegmentedControl
                    size="sm"
                    label={`${c.name}: constant or schedule`}
                    options={MODES.map((m) =>
                      m.value === "schedule" && (repairable || !node.modelId)
                        ? {
                            ...m,
                            disabled: true,
                            title: repairable
                              ? "Schedules apply to non-repairable diagrams: a repaired item would restart its covariates from its own time zero."
                              : "Pick a saved covariate model for this block first.",
                          }
                        : m
                    )}
                    value={mode}
                    onChange={(m) => chooseMode(node, c, m)}
                  />
                </div>
                {mode === "constant" ? (
                  <label className="calc-cov rbd-cov-constant">
                    <span className="sr-only">{withUnit(c.name, c.unit)}</span>
                    {c.type === "category" ? (
                      <Select value={get(node, c)} onChange={(v) => set(node.id, c.name, v)} options={c.options || []} />
                    ) : (
                      <input
                        type="number"
                        step="any"
                        value={get(node, c)}
                        onChange={(e) => set(node.id, c.name, e.target.value)}
                      />
                    )}
                  </label>
                ) : (
                  <RbdCovariateSchedule
                    field={withRange(c, seen[node.id]?.ranges?.[c.name])}
                    unit={unit}
                    tMax={tMax ?? seen[node.id]?.xMax}
                    value={get(node, c)}
                    draft={drafts[node.id]?.[c.name]}
                    onDraft={(d) => setSchedDraft(node.id, c.name, d)}
                  />
                )}
              </div>
            );
          })}
          {schedulesOf(node) && (
            <NodePreview
              node={node}
              schedules={schedulesOf(node)}
              constants={constantsOf(node, get)}
              tMax={tMax}
              unit={unit}
              onError={(msg) => setErrors((prev) => (prev[node.id] === msg ? prev : { ...prev, [node.id]: msg }))}
              onData={(data) => remember(node.id, data)}
            />
          )}
        </div>
      ))}
    </Modal>
  );
}

// A covariate input with its fitted range (from the preview) when its own
// snapshot doesn't carry one: the presets are built from it.
function withRange(field, range) {
  if (!range || (field.min != null && field.max != null)) return field;
  return { ...field, min: range[0], max: range[1] };
}

function initial(covNodes, pick) {
  const out = {};
  for (const node of covNodes) {
    out[node.id] = {};
    for (const c of node.covariates) {
      const v = pick(node.schedules?.[c.name] || null);
      if (v != null) out[node.id][c.name] = v;
    }
  }
  return out;
}

function constantsOf(node, get) {
  const out = {};
  for (const c of node.covariates) out[c.name] = get(node, c);
  return out;
}

// The block's live preview, re-asked (debounced) as its schedules change.
function NodePreview({ node, schedules, constants, tMax, unit, onError, onData }) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const key = useMemo(() => JSON.stringify({ schedules, constants, tMax }), [schedules, constants, tMax]);
  useEffect(() => {
    let live = true;
    setState((s) => ({ ...s, loading: true }));
    const timer = setTimeout(() => {
      previewRbdSchedule({ modelId: node.modelId, schedules, constants, tMax })
        .then((data) => {
          if (!live) return;
          setState({ data, error: null, loading: false });
          onError(null);
          onData(data);
        })
        .catch((e) => {
          if (!live) return;
          const msg = e?.message || "Couldn't preview this schedule.";
          setState((s) => ({ data: s.data, error: msg, loading: false }));
          onError(msg);
        });
    }, 350);
    return () => {
      live = false;
      clearTimeout(timer);
    };
    // `key` stands for schedules, constants and tMax.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, node.modelId]);
  return <RbdSchedulePreview preview={state.error ? null : state.data} error={state.error} loading={state.loading} unit={unit} />;
}
