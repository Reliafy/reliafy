import { useContext, useState } from "react";
import Modal from "./Modal.jsx";
import RbdCapacityFold from "./RbdCapacityFields.jsx";
import ModelPicker from "./ModelPicker.jsx";
import { BlockCostSection } from "./RbdBlockCosts.jsx";
import { RbdUnitContext } from "./RbdNodes.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { BlockNameField, MeanEcho } from "./LifeModelModal.jsx";
import RbdMeanCheck from "./RbdMeanCheck.jsx";

// In a repairable diagram (#156) the block is a standby group of identical
// units: the duty unit and its spares each fail by the life model and are
// repaired by the repair-time model, each failed unit a job for the
// diagram's repair crews — or, "repaired one unit at a time", for the
// group's own single repairer. It takes costs (per unit failure) and a crew
// priority, not scheduled maintenance.

// Configure a standby-redundancy block: the active unit's life model, the
// number of spares, and how the idle spares age — cold (not at all), warm (at a
// fraction of the running rate, the dormancy factor) or hot (like a running
// unit). Cold standby also takes the start-success probability and an optional
// separate life model for the spares.
const KINDS = [
  { id: "cold", label: "Cold", hint: "Idle spares don't age; each must start when switched in." },
  { id: "warm", label: "Warm", hint: "Idle spares age at a fraction of the running rate, and can fail before they're needed." },
  { id: "hot", label: "Hot", hint: "Every unit runs from the start — plain active redundancy." },
];

function initialKind(initial) {
  const d = initial?.dormancy ?? (initial?.cold ? 0 : 1);
  return d <= 0 ? "cold" : d >= 1 ? "hot" : "warm";
}
// A spare's chance of starting when switched in, as first offered on a cold
// standby: a perfect switch-over, with a hint at typical real values under
// the field. Anything set before is kept.
export const COLD_START_DEFAULT = 1;
export const COLD_START_HINT = "Spares don't always start: 0.95–0.99 is typical for generators and pumps.";

export default function StandbyModal({ initial, onClose, onSubmit, repairable = false, crews = false }) {
  const unit = useContext(RbdUnitContext) || "";
  // "Standby" is the new block's own name: the field starts empty.
  const [name, setName] = useState(initial?.label && initial.label !== "Standby" ? initial.label : "");
  const [model, setModel] = useState(initial?.model ?? null);
  const [repair, setRepair] = useState(initial?.repair ?? null);
  const [oneAtATime, setOneAtATime] = useState(!!initial?.repair_one_at_a_time);
  const [extras, setExtras] = useState({ extras: null, valid: true });
  const [spares, setSpares] = useState(initial?.spares ?? 1);
  // k-of-n standby (#84): how many units run at once.
  const [running, setRunning] = useState(initial?.k ?? 1);
  const [kind, setKind] = useState(initialKind(initial));
  const [dormancy, setDormancy] = useState(
    initial?.dormancy > 0 && initial?.dormancy < 1 ? initial.dormancy : 0.2
  );
  const cold = kind === "cold";
  const wasCold = initialKind(initial) === "cold";
  const [startProb, setStartProb] = useState(wasCold ? initial?.startProb ?? 1 : COLD_START_DEFAULT);
  const [standbyModel, setStandbyModel] = useState(initial?.standbyModel ?? null);

  const sparesNum = Number(spares);
  const probNum = Number(startProb);
  const validSpares = Number.isInteger(sparesNum) && sparesNum >= 1;
  const validProb = !cold || (probNum >= 0 && probNum <= 1);
  const dormNum = Number(dormancy);
  const validDorm = kind !== "warm" || (dormNum > 0 && dormNum < 1);
  const runNum = Number(running);
  const validRunning = Number.isInteger(runNum) && runNum >= 1;
  // What the engine can't work out exactly for a non-repairable block (#84).
  const ownSpare = cold && !repairable && !!standbyModel;
  const limit = repairable || !validRunning || runNum < 2 ? null
    : kind === "warm" ? "Warm spares with 2 or more units running can't be worked out exactly yet — make them cold or hot, or run one unit."
    : ownSpare && runNum >= 3 ? "Cold spares with a model of their own work with at most 2 units running — give them the running units' model, or run fewer."
    : null;
  // The group's throughput while it works (#122): the block is up, and
  // delivers this, while its k running units are.
  const [cap, setCap] = useState({ value: initial?.capacity ?? null, valid: true });
  const valid = validSpares && validRunning && !limit && validProb && validDorm
    && (!repairable || (repair && extras.valid)) && cap.valid;

  const submit = () => {
    if (!valid) return;
    const config = {
      label: name.trim() || initial?.label || "Standby",
      model,
      spares: sparesNum,
      k: runNum > 1 ? runNum : null,
      cold,
      dormancy: cold ? 0 : kind === "hot" ? 1 : dormNum,
      startProb: cold ? probNum : 1,
      // A repairable group's units are identical: no separate spare model.
      standbyModel: cold && !repairable ? standbyModel : null,
      capacity: cap.value,
    };
    if (repairable) {
      Object.assign(config, { repair, repair_one_at_a_time: oneAtATime || null, ...(extras.extras || {}) });
    }
    onSubmit(config);
  };

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
          label="Each unit's life model"
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
        <div className="param-fields">
          <label className="param-field" title="How many units must run at once: 2 running and 1 spare is a 2-of-3 duty/standby train.">
            <span>Units running</span>
            <input type="number" min="1" step="1" value={running} onChange={(e) => setRunning(e.target.value)} />
          </label>
          <label className="param-field">
            <span>Spares</span>
            <input
              type="number"
              min="1"
              value={spares}
              onChange={(e) => setSpares(e.target.value)}
            />
          </label>
          {kind === "warm" && (
            <label className="param-field" title="How fast an idle spare ages relative to a running one: 0 is cold, 1 is hot.">
              <span>Dormancy factor</span>
              <input
                type="number"
                step="any"
                min="0"
                max="1"
                value={dormancy}
                onChange={(e) => setDormancy(e.target.value)}
              />
            </label>
          )}
          {cold && (
            <label className="param-field" title="The chance a spare starts when it's switched in: 1 is a perfect switch-over, 0.99 one failed start in 100 demands.">
              <span>Chance a spare starts</span>
              <input
                type="number"
                step="any"
                min="0"
                max="1"
                value={startProb}
                onChange={(e) => setStartProb(e.target.value)}
              />
            </label>
          )}
        </div>
        {cold && <p className="hint standby-start-hint">{COLD_START_HINT}</p>}
        <div className="standby-kind">
          <SegmentedControl
            label="Standby type"
            value={kind}
            onChange={setKind}
            options={KINDS.map((k) => ({ value: k.id, label: k.label }))}
          />
          <p className="hint">{KINDS.find((k) => k.id === kind).hint}</p>
        </div>
        {limit && <p className="hint rbd-limit" role="alert">{limit}</p>}
        {cold && !repairable && (
          <div className="standby-cold">
            <ModelPicker
              label="Standby failure model (optional, dormant)"
              value={standbyModel}
              onChange={setStandbyModel}
              rbdBlock
            />
          </div>
        )}
        {!repairable && (
          <RbdMeanCheck unit={unit} node={valid && model ? {
            type: "standby",
            data: {
              label: initial?.label, model, spares: sparesNum, k: runNum, dormancy: cold ? 0 : kind === "hot" ? 1 : dormNum,
              cold, startProb: cold ? probNum : 1, standbyModel: cold ? standbyModel : null,
            },
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
          <label className="rbd-instant-repair"
                 title="The group has its own repairer, who repairs one failed unit at a time; otherwise each failed unit is a job for the diagram's repair crews.">
            <input type="checkbox" checked={oneAtATime} onChange={(e) => setOneAtATime(e.target.checked)} />
            Repaired one unit at a time <span className="muted">— its own repairer, not the diagram's crews</span>
          </label>
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
