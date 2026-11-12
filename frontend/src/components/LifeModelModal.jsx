import BoundBlockFields from "./BoundBlockFields.jsx";
import { useContext, useState } from "react";
import Modal from "./Modal.jsx";
import ModelPicker from "./ModelPicker.jsx";
import { openGuide } from "./HelpButton.jsx";
import { CostFields, ExtrasErrors, PriorityField, costsSummary, useBlockExtras } from "./RbdBlockCosts.jsx";
import { dutyWords, hasDuty, taskOf, taskSummary } from "../rbdMaintenancePlan.js";
import { RbdUnitContext } from "./RbdNodes.jsx";
import { unitAbbr } from "./rbdModelText.js";
import useModelSummary from "./useModelSummary.js";
import { formatNumber } from "../format.js";
import RbdMixtureBuilder, { isMixture } from "./RbdMixtureBuilder.jsx";
import RbdRepairQuality from "./RbdRepairQuality.jsx";
import RbdCapacityFold from "./RbdCapacityFields.jsx";

// "Mean 13.6 h · median 12 h" under a model's inputs, so what the parameters
// mean is visible as they're typed (#299): SurPyval's mean and median.
export function MeanEcho({ model, unit, label = "Mean" }) {
  const summary = useModelSummary(model);
  if (summary?.mean == null) return null;
  const u = unitAbbr(unit) ? ` ${unitAbbr(unit)}` : "";
  return (
    <p className="rbd-dlg-echo">
      {label} {formatNumber(summary.mean)}{u}
      {summary.median != null && <> · median {formatNumber(summary.median)}{u}</>}
    </p>
  );
}

// The block's name, at the top of each block dialog (#289): what every result
// calls it. Blank keeps the name it had.
export function BlockNameField({ value, onChange, placeholder = "e.g. Feed pump A" }) {
  return (
    <label className="rbd-dlg-name">
      <span>Name</span>
      <input
        value={value}
        placeholder={placeholder}
        maxLength={80}
        onChange={(e) => onChange(e.target.value)}
        aria-label="Block name"
      />
    </label>
  );
}

// A section of the block dialog that folds: open when something is set.
function Fold({ title, summary, open: initialOpen, children }) {
  const [open, setOpen] = useState(initialOpen);
  return (
    <details className="rbd-dlg-fold" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>
        {title} <span className="muted"> · {summary}</span>
      </summary>
      <div className="rbd-dlg-fold-body">{children}</div>
    </details>
  );
}

// Edit a block (#314): its sections are Failure · Repair · Maintenance (or
// Proof test) · Costs. A non-repairable block has only its non-repairable model. In a
// safety function the proof test comes straight after Failure, open, and the
// costs stay folded. Pre-filled with the node's current models.
export default function LifeModelModal({ initial, onClose, onSubmit, repairable = false, crews = false,
                                         safety = false, capacity = false, jointBlock = false, conditions = [],
                                         nodeId = null, onEditPlan = null }) {
  // A block whose model's covariates were left open at its position (covariate_binding.py): its
  // covariates are set here (or from the diagram's values) unless another model is chosen.
  const wasBound = initial?.model?.kind === "bound";
  const [keepBound, setKeepBound] = useState(wasBound);
  const [covExtras, setCovExtras] = useState(null);
  const [name, setName] = useState(initial?.label ?? "");
  const [model, setModel] = useState(initial?.model ?? null);
  const [repair, setRepair] = useState(initial?.repair ?? null);
  const [instant, setInstant] = useState(!!initial?.instant_repair);
  const [extras, setExtras] = useState({ extras: null, valid: true });
  // Planned work (schedule, group, duty) is edited in the Maintenance plan (D5): here only the
  // costs and the crew priority, so saving the dialog leaves the plan as it is.
  const ctl = useBlockExtras(initial, setExtras, "costs");
  const unit = useContext(RbdUnitContext) || "";
  // Two failure modes built here (#318); a saved mixture comes from the picker.
  const [mixture, setMixture] = useState(isMixture(initial?.model) && initial?.model?.source !== "saved");
  // Imperfect repair / replacement at the N-th failure (#68).
  const [quality, setQuality] = useState({ value: initial?.repair_quality ?? null, valid: true });
  // Throughput while it works (#122): its own section, for component blocks.
  const [cap, setCap] = useState({ value: initial?.capacity ?? null, valid: true });
  const valid = model && (!repairable || repair || instant) && extras.valid && quality.valid && cap.valid;
  const capExtras = { ...(capacity ? { capacity: cap.value } : {}), ...(keepBound && covExtras ? covExtras : {}),
    ...(wasBound && !keepBound ? { covariate_values: null, covariate_map: null } : {}) };

  const payload = () => {
    const label = name.trim() || initial?.label;
    if (!repairable) return { model, repair: undefined, label, extras: Object.keys(capExtras).length ? capExtras : undefined };
    return {
      label,
      model,
      repair: instant ? repair ?? undefined : repair,
      extras: { ...(extras.extras || {}), instant_repair: instant || null, repair_quality: quality.value,
                ...capExtras },
    };
  };
  const submit = () => {
    if (!valid) return;
    onSubmit(payload());
  };
  // Save the block, then open the Maintenance plan on it.
  const editPlan = () => {
    if (valid) onEditPlan(payload());
  };

  const footer = (
    <>
      <span className="hint">
        {repairable ? (
          <button type="button" className="link" onClick={() => openGuide("repairable-availability")}>
            How do I model availability?
          </button>
        ) : (
          "Enter a mean or parameters, or pick a saved model."
        )}
      </span>
      <div className="row" style={{ margin: 0 }}>
        <button className="secondary" onClick={onClose}>Cancel</button>
        <button onClick={submit} disabled={!valid}>Save block</button>
      </div>
    </>
  );

  const hasCosts = !!Object.keys(initial?.costs || {}).length;
  // The block's planned work, in words; edited in the Maintenance plan (D5).
  const planLines = [
    taskSummary(initial || {}, unit),
    hasDuty(initial || {}) && initial.duty < 1 ? dutyWords(initial.duty, unit) : null,
    initial?.maintenance_group ? `Maintenance group “${initial.maintenance_group}”` : null,
  ].filter(Boolean);
  const maintenance = (
    <section className="rbd-dlg-sec rbd-dlg-plan">
      <h3>{safety ? "Proof test" : "Maintenance"}</h3>
      <p className="rbd-dlg-plan-sum">
        {safety && taskOf(initial || {}) === "none" ? "No proof test yet. " : ""}
        {planLines.join(" · ")}
      </p>
      {onEditPlan ? (
        <button type="button" className="secondary sm" onClick={editPlan} disabled={!valid}
                title={valid ? "Save this block and edit its planned work and duty in the Maintenance plan, under the diagram"
                  : "Finish the block first (it needs a failure model and a repair time)"}>
          Edit in the plan
        </button>
      ) : (
        <p className="muted">Set in the diagram’s Maintenance plan.</p>
      )}
    </section>
  );

  return (
    <Modal title={initial?.label || "Block"} onClose={onClose} footer={footer}>
      {/* A block on the canvas has a name; a design alternative's model doesn't. */}
      {initial?.label != null && <BlockNameField value={name} onChange={setName} />}
      <section className="rbd-dlg-sec">
        <h3>Failure</h3>
        {keepBound && (
          <div className="rbd-bound">
            <p>{initial.model.name || "A covariate model"}: some covariates are fixed at its position; set the rest here, or
              take them from the diagram’s Use and Environment values.{" "}
              <button type="button" className="link" onClick={() => { setKeepBound(false); setModel(null); }}>Use another model instead</button></p>
            <BoundBlockFields node={{ id: nodeId || "block", type: "component", data: initial }} conditions={conditions}
                              onChange={setCovExtras} />
          </div>
        )}
        {!mixture && !keepBound && (
          <>
            <ModelPicker label={safety ? "Non-repairable model (dangerous undetected failures, λDU)" : "Non-repairable model (time to failure)"}
                         value={initial?.model} onChange={setModel} rbdBlock unit={unit}
                         joint={jointBlock && !safety ? { repairable } : null}
                         meanEntry={safety ? "Mean time to a dangerous failure" : "Mean life, MTBF"} />
            <MeanEcho model={model} unit={unit} label="Mean life" />
          </>
        )}
        {!keepBound && <RbdMixtureBuilder on={mixture} initial={initial?.model} unit={unit} onChange={setModel}
                           onToggle={(on) => {
                             setMixture(on);
                             if (!on) setModel(isMixture(initial?.model) ? null : initial?.model ?? null);
                           }} />}
      </section>
      {repairable && safety && maintenance}
      {repairable && (
        <section className="rbd-dlg-sec">
          <h3>Repair</h3>
          <label className="rbd-instant-repair" title="Parts swapped much faster than the timescale you're studying, or no repair-time data: the block still fails and costs, but is never down.">
            <input type="checkbox" checked={instant} onChange={(e) => setInstant(e.target.checked)} />
            Repaired instantly <span className="muted">— still fails and costs, never down</span>
          </label>
          {!instant && (
            <>
              <ModelPicker
                label="Repair-time distribution (time to repair)"
                value={initial?.repair}
                onChange={setRepair}
                rbdBlock
                unit={unit}
                meanEntry="Mean repair time, MTTR"
              />
              <MeanEcho model={repair} unit={unit} label="MTTR" />
            </>
          )}
          {crews && <PriorityField ctl={ctl} />}
        </section>
      )}
      {repairable && <RbdRepairQuality initial={initial?.repair_quality} onChange={setQuality} />}
      {repairable && !safety && maintenance}
      {repairable && (
        <Fold title="Costs" summary={costsSummary(ctl)} open={hasCosts && !safety}>
          <CostFields ctl={ctl} unit={unit} />
        </Fold>
      )}
      {capacity && !safety && <RbdCapacityFold initial={initial?.capacity} onChange={setCap} />}
      {repairable && <ExtrasErrors ctl={ctl} />}
    </Modal>
  );
}
