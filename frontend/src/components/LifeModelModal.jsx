import { useContext, useState } from "react";
import Modal from "./Modal.jsx";
import ModelPicker from "./ModelPicker.jsx";
import { openGuide } from "./HelpButton.jsx";
import {
  CostFields, ExtrasErrors, MaintenanceFields, PriorityField, costsSummary, maintenanceSummary, useBlockExtras,
} from "./RbdBlockCosts.jsx";
import { RbdUnitContext } from "./RbdNodes.jsx";
import { modelMean, modelMedian, unitAbbr } from "./rbdModelText.js";
import { formatNumber } from "../format.js";

// "Mean 13.6 h · median 12 h" under a model's inputs, so what the parameters
// mean is visible as they're typed (#299).
export function MeanEcho({ model, unit, label = "Mean" }) {
  const mean = modelMean(model);
  if (mean == null) return null;
  const u = unitAbbr(unit) ? ` ${unitAbbr(unit)}` : "";
  const median = modelMedian(model);
  return (
    <p className="rbd-dlg-echo">
      {label} {formatNumber(mean)}{u}
      {median != null && <> · median {formatNumber(median)}{u}</>}
    </p>
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
// Proof test) · Costs. A non-repairable block has only its life model. In a
// safety function the proof test comes straight after Failure, open, and the
// costs stay folded. Pre-filled with the node's current models.
export default function LifeModelModal({ initial, onClose, onSubmit, repairable = false, crews = false, groups = [],
                                         safety = false }) {
  const [model, setModel] = useState(initial?.model ?? null);
  const [repair, setRepair] = useState(initial?.repair ?? null);
  const [instant, setInstant] = useState(!!initial?.instant_repair);
  const [extras, setExtras] = useState({ extras: null, valid: true });
  const ctl = useBlockExtras(initial, setExtras);
  const unit = useContext(RbdUnitContext) || "";
  const valid = model && (!repairable || repair || instant) && extras.valid;

  const submit = () => {
    if (!valid) return;
    if (!repairable) return onSubmit({ model, repair: undefined });
    onSubmit({
      model,
      repair: instant ? repair ?? undefined : repair,
      extras: { ...(extras.extras || {}), instant_repair: instant || null },
    });
  };

  const footer = (
    <>
      <span className="hint">
        {repairable ? (
          <button type="button" className="link" onClick={() => openGuide("repairable-availability")}>
            How do I model availability?
          </button>
        ) : (
          "Pick a saved model or enter parameters."
        )}
      </span>
      <div className="row" style={{ margin: 0 }}>
        <button className="secondary" onClick={onClose}>Cancel</button>
        <button onClick={submit} disabled={!valid}>Save block</button>
      </div>
    </>
  );

  const hasSchedule = !!(initial?.preventive || initial?.inspection || initial?.maintenance_group);
  const hasCosts = !!Object.keys(initial?.costs || {}).length;
  const maintenance = safety ? (
    <section className="rbd-dlg-sec">
      <h3>Proof test</h3>
      <MaintenanceFields ctl={ctl} unit={unit} groups={groups} />
    </section>
  ) : (
    <Fold title="Maintenance" summary={maintenanceSummary(ctl, unit)} open={hasSchedule}>
      <MaintenanceFields ctl={ctl} unit={unit} groups={groups} />
    </Fold>
  );

  return (
    <Modal title={initial?.label || "Block"} onClose={onClose} footer={footer}>
      <section className="rbd-dlg-sec">
        <h3>Failure</h3>
        <ModelPicker label={safety ? "Life model (dangerous undetected failures, λDU)" : "Life model (time to failure)"}
                     value={initial?.model} onChange={setModel} rbdBlock />
        <MeanEcho model={model} unit={unit} label="Mean life" />
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
              />
              <MeanEcho model={repair} unit={unit} label="MTTR" />
            </>
          )}
          {crews && <PriorityField ctl={ctl} />}
        </section>
      )}
      {repairable && !safety && maintenance}
      {repairable && (
        <Fold title="Costs" summary={costsSummary(ctl)} open={hasCosts && !safety}>
          <CostFields ctl={ctl} unit={unit} />
        </Fold>
      )}
      {repairable && <ExtrasErrors ctl={ctl} />}
    </Modal>
  );
}
