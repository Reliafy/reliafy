import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Select from "./Select.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { getJointModel, listJointModels } from "../api.js";
import { formatNumber } from "../format.js";
import { jointBlockModel, parseReadings, readingsText } from "../joint.js";

// An RBD block that is one unit of a condition-based risk (joint) model: a
// running unit of the fit, or one entered (its age now, readings, covariates).
// Its reliability runs from the unit's age now. ``repairable`` diagrams can't
// take it (a replacement unit has none of its readings): a note says so.
export default function JointBlockSource({ value, onChange, repairable = false }) {
  const init = value?.kind === "joint" ? value : null;
  const [models, setModels] = useState(null);
  const [modelId, setModelId] = useState(init?.modelId || "");
  const [detail, setDetail] = useState(null);
  const [mode, setMode] = useState(init?.joint_unit && init.joint_unit.id == null ? "entered" : "fitted");
  const [unitId, setUnitId] = useState(init?.joint_unit?.id || "");
  const [age, setAge] = useState(init?.joint_unit?.age != null ? String(init.joint_unit.age) : "");
  const [readings, setReadings] = useState(readingsText(init?.joint_unit?.markers));
  const [covs, setCovs] = useState(init?.joint_unit?.covariates || {});
  const [error, setError] = useState(null);

  useEffect(() => {
    if (repairable) return;
    listJointModels().then((d) => setModels(d.models || [])).catch(() => setModels([]));
  }, [repairable]);

  useEffect(() => {
    if (!modelId) { setDetail(null); return; }
    let live = true;
    getJointModel(modelId).then((d) => live && setDetail(d)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [modelId]);

  // Emit the block's model whenever the choice is complete, else null.
  useEffect(() => {
    if (repairable || !detail) { onChange(null); return; }
    const m = { id: detail.id, name: detail.name, unit: detail.results?.unit || detail.unit || "" };
    if (mode === "fitted") {
      onChange(unitId ? jointBlockModel(m, { id: unitId }) : null);
      setError(null);
      return;
    }
    const parsed = parseReadings(readings);
    const names = detail.results?.covariates || [];
    const missing = names.some((c) => covs[c] === "" || covs[c] == null || Number.isNaN(Number(covs[c])));
    if (age === "" || Number.isNaN(Number(age)) || parsed.error || missing) {
      setError(parsed.error || null);
      onChange(null);
      return;
    }
    setError(null);
    onChange(jointBlockModel(m, {
      age: Number(age), markers: parsed.readings,
      covariates: Object.fromEntries(names.map((c) => [c, Number(covs[c])])),
    }));
    // onChange is the parent's setter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repairable, detail, mode, unitId, age, readings, JSON.stringify(covs)]);

  if (repairable) {
    return (
      <p className="muted-line" role="status">
        A condition-based block is one unit in service now, given its readings. A repairable diagram replaces a
        failed unit with a new one that has none of those readings, so it can't take one: use it in a
        non-repairable diagram, or give this block a life distribution.
      </p>
    );
  }
  if (models && !models.length) {
    return (
      <p className="muted-line">
        No condition-based risk models yet. <Link to="/modelling/joint/new">Fit one</Link> from your units' readings.
      </p>
    );
  }
  const unit = detail?.results?.unit || "";
  const running = detail?.running_units || [];
  return (
    <div className="joint-block-src">
      <label className="dist-field" style={{ maxWidth: 320 }}>
        <span className="dist-label">Model</span>
        <Select
          value={modelId}
          onChange={(id) => { setModelId(id); setUnitId(""); }}
          placeholder="— choose —"
          ariaLabel="Condition-based model"
          options={[{ value: "", label: "— choose —" }, ...(models || []).map((m) => ({ value: m.id, label: m.name, hint: m.marker }))]}
        />
      </label>
      {detail && (
        <>
          <SegmentedControl
            label="Which unit" size="sm" value={mode} onChange={setMode}
            options={[{ value: "fitted", label: "A running unit" }, { value: "entered", label: "Enter a unit" }]}
          />
          {mode === "fitted" ? (
            running.length ? (
              <label className="dist-field" style={{ maxWidth: 320 }}>
                <span className="dist-label">Unit</span>
                <Select
                  value={unitId}
                  onChange={setUnitId}
                  placeholder="— choose —"
                  ariaLabel="Running unit"
                  options={[{ value: "", label: "— choose —" }, ...running.map((u) => ({
                    value: u.id, label: u.id,
                    hint: `age ${formatNumber(u.age)}${unit ? ` ${unit.toLowerCase()}` : ""}`,
                  }))]}
                />
              </label>
            ) : <p className="muted-line">This model has no running units: enter one.</p>
          ) : (
            <div className="param-fields">
              <label className="param-field">
                <span>Age now{unit ? ` (${unit.toLowerCase()}, since new)` : " (since new)"}</span>
                <input type="number" inputMode="decimal" min="0" step="any" value={age} onChange={(e) => setAge(e.target.value)} />
              </label>
              {(detail.results?.covariates || []).map((c) => (
                <label className="param-field" key={c}>
                  <span>{c}</span>
                  <input type="number" inputMode="decimal" step="any" value={covs[c] ?? ""}
                         onChange={(e) => setCovs({ ...covs, [c]: e.target.value })} />
                </label>
              ))}
              <label className="param-field joint-readings">
                <span>Readings: age and value, one per line</span>
                <textarea rows={3} value={readings} placeholder={"0 2.1\n20 2.6"} onChange={(e) => setReadings(e.target.value)} />
              </label>
            </div>
          )}
          <p className="hint" style={{ marginBottom: 0 }}>
            This block runs from the unit's age now: at time t in the diagram, its reliability is its chance of
            surviving from its age to age + t, given its readings.
          </p>
        </>
      )}
      {error && <p className="rbd-dlg-echo is-error" role="alert">{error}</p>}
    </div>
  );
}
