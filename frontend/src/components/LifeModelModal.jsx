import { useContext, useState } from "react";
import Modal from "./Modal.jsx";
import ModelPicker from "./ModelPicker.jsx";
import { openGuide } from "./HelpButton.jsx";
import { BlockCostSection } from "./RbdBlockCosts.jsx";
import { RbdUnitContext } from "./RbdNodes.jsx";

// Edit a node's life model — and, in a repairable RBD, its repair-time
// distribution (or instant repair) and its costs and maintenance too — in one
// place. Pre-filled with the node's current models.
export default function LifeModelModal({ initial, onClose, onSubmit, repairable = false }) {
  const [model, setModel] = useState(initial?.model ?? null);
  const [repair, setRepair] = useState(initial?.repair ?? null);
  const [instant, setInstant] = useState(!!initial?.instant_repair);
  const [extras, setExtras] = useState({ extras: null, valid: true });
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
          <>
            Set the life model and the repair-time (MTTR) distribution.{" "}
            <button type="button" className="link-btn" onClick={() => openGuide("repairable-availability")}>
              How do I model availability?
            </button>
          </>
        ) : (
          "Pick a saved model or enter parameters."
        )}
      </span>
      <div className="row" style={{ margin: 0 }}>
        <button className="secondary" onClick={onClose}>Cancel</button>
        <button onClick={submit} disabled={!valid}>
          {repairable ? "Set models" : "Set life model"}
        </button>
      </div>
    </>
  );

  return (
    <Modal title={repairable ? "Component models" : "Life model"} onClose={onClose} footer={footer}>
      <ModelPicker label="Life model (time to failure)" value={initial?.model} onChange={setModel} />
      {repairable && (
        <div style={{ marginTop: "1rem" }}>
          <label className="rbd-instant-repair" title="Parts swapped much faster than the timescale you're studying, or no repair-time data: the block still fails and costs, but is never down.">
            <input type="checkbox" checked={instant} onChange={(e) => setInstant(e.target.checked)} />
            Repaired instantly <span className="muted">— still fails and costs, never down</span>
          </label>
          {!instant && (
            <ModelPicker
              label="Repair-time distribution (time to repair)"
              value={initial?.repair}
              onChange={setRepair}
            />
          )}
          <BlockCostSection initial={initial} onChange={setExtras} unit={unit} />
        </div>
      )}
    </Modal>
  );
}
