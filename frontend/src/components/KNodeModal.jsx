import { useState } from "react";
import Modal from "./Modal.jsx";
import { BlockNameField } from "./LifeModelModal.jsx";
import { moonText } from "./RbdNodes.jsx";

// Set a voting node (MooN): the system through this node works if at least
// M of the N connected branches work. Stored as the node's n (M, needed) and
// k (N, in total), and an optional name (#289).
export default function KNodeModal({ initial, onClose, onSubmit }) {
  const [name, setName] = useState(initial?.label ?? "");
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
    if (valid) onSubmit({ n: nNum, k: kNum, label: name.trim() || null });
  };

  const footer = (
    <>
      <span className="hint">At least M of the N branches must work. 1ooN is a plain junction.</span>
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
    <Modal title="Voting node (MooN)" onClose={onClose} footer={footer}>
      <BlockNameField value={name} onChange={setName} placeholder="e.g. Level transmitters vote" />
      <p className="muted-line" style={{ marginTop: 0 }}>
        {valid
          ? `${moonText(nNum, kNum)}: at least ${nNum} of ${kNum} branches must work.`
          : "M must be between 1 and N."}
      </p>
      <div className="param-fields">
        <label className="param-field">
          <span>M — needed to work</span>
          <input
            type="number"
            min="1"
            value={n}
            onChange={(e) => setN(e.target.value)}
          />
        </label>
        <label className="param-field">
          <span>N — branches in total</span>
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
