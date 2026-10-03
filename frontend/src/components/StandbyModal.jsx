import { useContext, useState } from "react";
import Modal from "./Modal.jsx";
import ModelPicker from "./ModelPicker.jsx";
import { BlockCostSection } from "./RbdBlockCosts.jsx";
import { RbdUnitContext } from "./RbdNodes.jsx";

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
export default function StandbyModal({ initial, onClose, onSubmit, repairable = false, crews = false }) {
  const unit = useContext(RbdUnitContext) || "";
  const [model, setModel] = useState(initial?.model ?? null);
  const [repair, setRepair] = useState(initial?.repair ?? null);
  const [oneAtATime, setOneAtATime] = useState(!!initial?.repair_one_at_a_time);
  const [extras, setExtras] = useState({ extras: null, valid: true });
  const [spares, setSpares] = useState(initial?.spares ?? 1);
  const [kind, setKind] = useState(initialKind(initial));
  const [dormancy, setDormancy] = useState(
    initial?.dormancy > 0 && initial?.dormancy < 1 ? initial.dormancy : 0.2
  );
  const cold = kind === "cold";
  const [startProb, setStartProb] = useState(initial?.startProb ?? 1);
  const [standbyModel, setStandbyModel] = useState(initial?.standbyModel ?? null);

  const sparesNum = Number(spares);
  const probNum = Number(startProb);
  const validSpares = Number.isInteger(sparesNum) && sparesNum >= 1;
  const validProb = !cold || (probNum >= 0 && probNum <= 1);
  const dormNum = Number(dormancy);
  const validDorm = kind !== "warm" || (dormNum > 0 && dormNum < 1);
  const valid = validSpares && validProb && validDorm && (!repairable || (repair && extras.valid));

  const submit = () => {
    if (!valid) return;
    const config = {
      model,
      spares: sparesNum,
      cold,
      dormancy: cold ? 0 : kind === "hot" ? 1 : dormNum,
      startProb: cold ? probNum : 1,
      // A repairable group's units are identical: no separate spare model.
      standbyModel: cold && !repairable ? standbyModel : null,
    };
    if (repairable) {
      Object.assign(config, { repair, repair_one_at_a_time: oneAtATime || null, ...(extras.extras || {}) });
    }
    onSubmit(config);
  };

  const footer = (
    <>
      <span className="hint">
        One active unit with {spares} standby spare(s){repairable ? ", each repaired after it fails" : ""}.
      </span>
      <div className="row" style={{ margin: 0 }}>
        <button className="secondary" onClick={onClose}>
          Cancel
        </button>
        <button onClick={submit} disabled={!valid}>
          Set standby
        </button>
      </div>
    </>
  );

  return (
    <Modal title="Standby redundancy" onClose={onClose} footer={footer}>
      <ModelPicker
        label="Active unit life model"
        value={model}
        onChange={setModel}
      />

      <div className="param-fields" style={{ marginTop: "1.25rem" }}>
        <label className="param-field">
          <span>spares</span>
          <input
            type="number"
            min="1"
            value={spares}
            onChange={(e) => setSpares(e.target.value)}
          />
        </label>
      </div>

      <div className="standby-kind">
        <div className="seg" role="radiogroup" aria-label="Standby type">
          {KINDS.map((k) => (
            <button
              key={k.id}
              type="button"
              role="radio"
              aria-checked={kind === k.id}
              className={"seg-btn" + (kind === k.id ? " active" : "")}
              onClick={() => setKind(k.id)}
            >
              {k.label}
            </button>
          ))}
        </div>
        <p className="hint">{KINDS.find((k) => k.id === kind).hint}</p>
      </div>

      {kind === "warm" && (
        <div className="param-fields">
          <label className="param-field" title="How fast an idle spare ages relative to a running one: 0 is cold, 1 is hot.">
            <span>dormancy factor</span>
            <input
              type="number"
              step="any"
              min="0"
              max="1"
              value={dormancy}
              onChange={(e) => setDormancy(e.target.value)}
            />
          </label>
        </div>
      )}

      {cold && (
        <div className="standby-cold">
          <div className="param-fields">
            <label className="param-field">
              <span>start success p</span>
              <input
                type="number"
                step="any"
                min="0"
                max="1"
                value={startProb}
                onChange={(e) => setStartProb(e.target.value)}
              />
            </label>
          </div>
          {!repairable && (
            <ModelPicker
              label="Standby failure model (optional, dormant)"
              value={standbyModel}
              onChange={setStandbyModel}
            />
          )}
        </div>
      )}

      {repairable && (
        <div style={{ marginTop: "1rem" }}>
          <ModelPicker
            label="Repair-time distribution (each failed unit)"
            value={initial?.repair}
            onChange={setRepair}
          />
          <label className="rbd-instant-repair"
                 title="The group has its own repairer, who repairs one failed unit at a time; otherwise each failed unit is a job for the diagram's repair crews.">
            <input type="checkbox" checked={oneAtATime} onChange={(e) => setOneAtATime(e.target.checked)} />
            Repaired one unit at a time <span className="muted">— its own repairer, not the diagram's crews</span>
          </label>
          <BlockCostSection initial={initial} onChange={setExtras} unit={unit} crews={crews && !oneAtATime}
                            mode="standby" />
        </div>
      )}
    </Modal>
  );
}
