import { useState } from "react";
import Modal from "./Modal.jsx";
import ModelPicker from "./ModelPicker.jsx";
import { openGuide } from "./HelpButton.jsx";

// Edit a node's life model — and, in a repairable RBD, its repair-time
// distribution too — in one place. Pre-filled with the node's current models.
export default function LifeModelModal({ initial, onClose, onSubmit, repairable = false }) {
  const [model, setModel] = useState(initial?.model ?? null);
  const [repair, setRepair] = useState(initial?.repair ?? null);
  const valid = model && (!repairable || repair);

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
        <button
          onClick={() => valid && onSubmit({ model, repair: repairable ? repair : undefined })}
          disabled={!valid}
        >
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
          <ModelPicker
            label="Repair-time distribution (time to repair)"
            value={initial?.repair}
            onChange={setRepair}
          />
        </div>
      )}
    </Modal>
  );
}
