import { useState } from "react";
import Modal from "./Modal.jsx";

// Set the count n of identical units in a series/parallel block.
export default function CountModal({ initial, onClose, onSubmit }) {
  const [n, setN] = useState(initial?.n ?? 2);
  const num = Number(n);
  const valid = Number.isInteger(num) && num >= 1;

  const footer = (
    <>
      <span className="hint">
        Identical units arranged in {initial?.kind || "this block"}.
      </span>
      <div className="row" style={{ margin: 0 }}>
        <button className="secondary" onClick={onClose}>
          Cancel
        </button>
        <button onClick={() => valid && onSubmit({ n: num })} disabled={!valid}>
          Set count
        </button>
      </div>
    </>
  );

  return (
    <Modal
      title={`${initial?.label || "Block"} — count`}
      onClose={onClose}
      footer={footer}
    >
      <p className="muted-line" style={{ marginTop: 0 }}>
        Number of identical units in {initial?.kind || "this block"}.
      </p>
      <div className="param-fields">
        <label className="param-field">
          <span>n (count)</span>
          <input
            type="number"
            min="1"
            value={n}
            onChange={(e) => setN(e.target.value)}
          />
        </label>
      </div>
    </Modal>
  );
}
