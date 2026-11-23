import { useState } from "react";
import Modal from "./Modal.jsx";
import { BlockNameField } from "./LifeModelModal.jsx";
import { moonText } from "./RbdNodes.jsx";
import { voteState } from "../rbdVotes.js";

// Set a voting node (MooN): the system through this node works if at least
// M of the N branches wired into it work. N is the wires coming in (counted, never
// typed), so only M is asked: stored as the node's n, with an optional name (#289).
// `initial.inputs`: the branches wired in now (none yet for a new node). M starts at 1
// (any one is enough: redundancy), and can't be set above what's wired in.
export default function KNodeModal({ initial, onClose, onSubmit }) {
  const inputs = Number(initial?.inputs) || 0;
  const [name, setName] = useState(initial?.label ?? "");
  const [n, setN] = useState(initial?.n ?? 1);

  const nNum = Number(n);
  const whole = Number.isInteger(nNum) && nNum >= 1;
  const valid = whole && (!inputs || nNum <= inputs);
  const state = valid && inputs ? voteState(nNum, inputs) : null;

  const submit = () => {
    if (valid) onSubmit({ n: nNum, ...(inputs ? { k: inputs } : {}), label: name.trim() || null });
  };

  let line;
  if (!whole) line = "Enter a whole number of 1 or more.";
  else if (!valid) line = `Only ${inputs} branch${inputs === 1 ? " is" : "es are"} wired in, so it can need at most ${inputs}. Wire in more first.`;
  else if (!inputs) line = `At least ${nNum} of the branches you wire into it must work.`;
  else if (state === "all_must_work") line = `${nNum} of ${inputs}: all must work, so these add no redundancy (it acts as series). Did you mean 1 of ${inputs}?`;
  else line = `${moonText(nNum, inputs)}: at least ${nNum} of the ${inputs} branches wired in must work.`;

  const footer = (
    <>
      <span className="hint">The branches are the wires into it. 1 needed is a plain junction.</span>
      <div className="row m-0">
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
      <p className={state === "all_must_work" || !valid ? "muted-line warn mt-0" : "muted-line mt-0"} role="status">{line}</p>
      {state === "all_must_work" && (
        <p className="mt-0">
          <button type="button" className="secondary sm" onClick={() => setN(1)}>Make it 1 of {inputs}</button>
        </p>
      )}
      <div className="param-fields">
        <label className="param-field">
          <span>M — working branches needed{inputs ? ` (of ${inputs} wired in)` : ""}</span>
          <input
            type="number" inputMode="decimal"
            min="1"
            max={inputs || undefined}
            value={n}
            onChange={(e) => setN(e.target.value)}
          />
        </label>
      </div>
    </Modal>
  );
}
