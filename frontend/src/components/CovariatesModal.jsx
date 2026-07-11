import Select from "./Select.jsx";
import { useState } from "react";
import Modal from "./Modal.jsx";

// Edit the covariate values for every node backed by a proportional-hazards
// model. Edits go into a draft and are only committed on Apply.
export default function CovariatesModal({ covNodes, values, onApply, onClose }) {
  const [draft, setDraft] = useState(values || {});

  const get = (node, c) => draft[node.id]?.[c.name] ?? c.default;
  const set = (nodeId, name, value) =>
    setDraft((prev) => ({
      ...prev,
      [nodeId]: { ...(prev[nodeId] || {}), [name]: value },
    }));

  const footer = (
    <>
      <span className="hint">These feed the reliability calculation.</span>
      <div className="row" style={{ margin: 0 }}>
        <button className="secondary" onClick={onClose}>
          Cancel
        </button>
        <button onClick={() => onApply(draft)}>Apply</button>
      </div>
    </>
  );

  return (
    <Modal title="Covariates" onClose={onClose} footer={footer}>
      <p className="hint" style={{ marginTop: 0 }}>
        These nodes use proportional-hazards models. Set the covariate values to
        evaluate each one at.
      </p>
      {covNodes.map((node) => (
        <div className="rbd-cov-node" key={node.id}>
          <span className="rbd-cov-node-label">{node.label}</span>
          <div className="calc-cov-fields">
            {node.covariates.map((c) => (
              <label className="calc-cov" key={c.name}>
                <span>{c.name}</span>
                {c.type === "category" ? (
                  <Select
                    value={get(node, c)}
                    onChange={(v) => set(node.id, c.name, v)}
                    options={c.options || []}
                  />
                ) : (
                  <input
                    type="number"
                    step="any"
                    value={get(node, c)}
                    onChange={(e) => set(node.id, c.name, e.target.value)}
                  />
                )}
              </label>
            ))}
          </div>
        </div>
      ))}
    </Modal>
  );
}
