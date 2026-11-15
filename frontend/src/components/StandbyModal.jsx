import { useContext, useState } from "react";
import Modal from "./Modal.jsx";
import RbdCapacityFold from "./RbdCapacityFields.jsx";
import ModelPicker from "./ModelPicker.jsx";
import { BlockCostSection } from "./RbdBlockCosts.jsx";
import { RbdUnitContext } from "./RbdNodes.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import StandbySettings from "./StandbySettings.jsx";
import { BlockNameField, MeanEcho } from "./LifeModelModal.jsx";
import RbdMeanCheck from "./RbdMeanCheck.jsx";

// In a repairable diagram (#156) the block is a standby group of identical
// units: the duty unit and its spares each fail by the non-repairable model and are
// repaired by the repair-time model, each failed unit a job for the
// diagram's repair crews — or, "repaired one unit at a time", for the
// group's own single repairer. It takes costs (per unit failure) and a crew
// priority, not scheduled maintenance.

// Configure a standby-redundancy block: the running units' non-repairable
// model, then its standby settings (StandbySettings: units running, spares,
// cold / warm / hot, the chance a spare starts, units that differ, and how the
// block is worked out), its repair (repairable diagrams) and capacity.
export { COLD_START_DEFAULT, COLD_START_HINT } from "./StandbySettings.jsx";

export default function StandbyModal({ initial, onClose, onSubmit, repairable = false, crews = false }) {
  const unit = useContext(RbdUnitContext) || "";
  // "Standby" is the new block's own name: the field starts empty.
  const [name, setName] = useState(initial?.label && initial.label !== "Standby" ? initial.label : "");
  const [model, setModel] = useState(initial?.model ?? null);
  const [repair, setRepair] = useState(initial?.repair ?? null);
  const [oneAtATime, setOneAtATime] = useState(!!initial?.repair_one_at_a_time);
  const [extras, setExtras] = useState({ extras: null, valid: true });
  const [standby, setStandby] = useState({ settings: null, valid: false });
  // The group's throughput while it works (#122): the block is up, and
  // delivers this, while its k running units are.
  const [cap, setCap] = useState({ value: initial?.capacity ?? null, valid: true });
  const s = standby.settings;
  const valid = !!s && standby.valid && (!repairable || (repair && extras.valid)) && cap.valid;

  const submit = () => {
    if (!valid) return;
    const config = { label: name.trim() || initial?.label || "Standby", model, ...s, capacity: cap.value };
    if (repairable) {
      Object.assign(config, { repair, repair_one_at_a_time: oneAtATime || null, ...(extras.extras || {}) });
    }
    onSubmit(config);
  };
  const runNum = s?.k || 1;
  const spares = s?.spares ?? initial?.spares ?? 1;

  const footer = (
    <>
      <span className="hint">
        {runNum > 1 ? `${runNum} running` : "One active unit"} with {spares} standby spare(s)
        {repairable ? ", each repaired after it fails" : ""}.
      </span>
      <div className="row" style={{ margin: 0 }}>
        <button className="secondary" onClick={onClose}>
          Cancel
        </button>
        <button onClick={submit} disabled={!valid}>
          Save block
        </button>
      </div>
    </>
  );

  return (
    <Modal title={initial?.label && initial.label !== "Standby" ? initial.label : "Standby redundancy"} onClose={onClose} footer={footer}>
      <BlockNameField value={name} onChange={setName} placeholder="e.g. Cooling pumps (duty/standby)" />
      <section className="rbd-dlg-sec">
        <h3>Failure</h3>
        <ModelPicker
          label="Each unit's non-repairable model (unless it has its own)"
          value={model}
          onChange={setModel}
          rbdBlock
          unit={unit}
          meanEntry="Mean life, MTBF"
        />
        <MeanEcho model={model} unit={unit} label="Mean life" />
      </section>

      <section className="rbd-dlg-sec">
        <h3>Standby</h3>
        <StandbySettings
          initial={initial}
          model={model}
          repairable={repairable}
          unit={unit}
          label={name.trim() || initial?.label || "Standby"}
          onChange={setStandby}
        />
        {!repairable && (
          <RbdMeanCheck unit={unit} node={valid && model && !s?.simulate ? {
            type: "standby", data: { label: initial?.label, model, ...s },
          } : null} />
        )}
      </section>

      {repairable && (
        <section className="rbd-dlg-sec">
          <h3>Repair</h3>
          <ModelPicker
            label="Repair-time distribution (each failed unit)"
            value={initial?.repair}
            onChange={setRepair}
            rbdBlock
            unit={unit}
            meanEntry="Mean repair time, MTTR"
          />
          <MeanEcho model={repair} unit={unit} label="MTTR" />
          {/* Who repairs is a choice that changes the answer, so it's asked as one, not a small tick-box. */}
          <div className="picker">
            <div className="picker-label">Who repairs a failed unit</div>
            <SegmentedControl
              label="Who repairs a failed unit"
              value={oneAtATime ? "own" : "crews"}
              onChange={(v) => setOneAtATime(v === "own")}
              options={[
                { value: "crews", label: "The diagram's crews", title: "Each failed unit is a job for the diagram's repair crews, waiting when they're busy." },
                { value: "own", label: "Its own repairer", title: "The group has its own repairer, who repairs one failed unit at a time." },
              ]}
            />
            <p className="hint" style={{ margin: "4px 0 0" }}>
              {oneAtATime
                ? "One failed unit at a time, by the group's own repairer; the diagram's crews aren't used."
                : crews ? "Each failed unit joins the queue for the diagram's repair crews."
                  : "Each failed unit is repaired at once (the diagram has no crew limit)."}
            </p>
          </div>
        </section>
      )}
      {repairable && (
        <BlockCostSection initial={initial} onChange={setExtras} unit={unit} crews={crews && !oneAtATime}
                          mode="standby" />
      )}
      <RbdCapacityFold initial={initial?.capacity} onChange={setCap} />
    </Modal>
  );
}
