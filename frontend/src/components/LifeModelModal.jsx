import { useState } from "react";
import Modal from "./Modal.jsx";
import ModelPicker from "./ModelPicker.jsx";

// Edit a node's life model: choose a saved model or enter parameters, in one
// place. Pre-filled with the node's current model.
export default function LifeModelModal({ initial, onClose, onSubmit }) {
  const [model, setModel] = useState(initial?.model ?? null);

  const footer = (
    <>
      <span className="hint">Pick a saved model or enter parameters.</span>
      <div className="row" style={{ margin: 0 }}>
        <button className="secondary" onClick={onClose}>
          Cancel
        </button>
        <button onClick={() => model && onSubmit(model)} disabled={!model}>
          Set life model
        </button>
      </div>
    </>
  );

  return (
    <Modal title="Life model" onClose={onClose} footer={footer}>
      <ModelPicker
        label="Life model"
        value={initial?.model}
        onChange={setModel}
      />
    </Modal>
  );
}
