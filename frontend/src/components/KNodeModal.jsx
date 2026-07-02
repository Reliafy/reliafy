import { useState } from "react";
import Modal from "./Modal.jsx";

// Set the n and k of an n-out-of-k voting node: the system through this node
// works if at least n of the k connected branches work.
export default function KNodeModal({ initial, onClose, onSubmit }) {
  const [n, setN] = useState(initial?.n ?? 2);
  const [k, setK] = useState(initial?.k ?? 3);

  const nNum = Number(n);
  const kNum = Number(k);
  const valid =
    Number.isInteger(nNum) &&
    Number.isInteger(kNum) &&
    nNum >= 1 &&
    kNum >= 1 &&
    nNum <= kNum;

  const submit = () => {
    if (valid) onSubmit({ n: nNum, k: kNum });
  };

  const footer = (
    <>
      <span className="hint">At least n of the k branches must work.</span>
      <div className="row" style={{ margin: 0 }}>
        <button className="secondary" onClick={onClose}>
          Cancel
        </button>
        <button onClick={submit} disabled={!valid}>
          {initial?.mode === "edit" ? "Update" : "Add node"}
        </button>
      </div>
    </>
  );

  return (
    <Modal title="n-out-of-k voting node" onClose={onClose} footer={footer}>
      <p className="muted-line" style={{ marginTop: 0 }}>
        {valid
          ? `At least ${nNum} of ${kNum} branches must work.`
          : "n must be between 1 and k."}
      </p>
      <div className="param-fields">
        <label className="param-field">
          <span>n (required)</span>
          <input
            type="number"
            min="1"
            value={n}
            onChange={(e) => setN(e.target.value)}
          />
        </label>
        <label className="param-field">
          <span>k (total)</span>
          <input
            type="number"
            min="1"
            value={k}
            onChange={(e) => setK(e.target.value)}
          />
        </label>
      </div>
    </Modal>
  );
}
