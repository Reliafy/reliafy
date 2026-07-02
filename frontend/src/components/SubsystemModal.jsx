import { useEffect, useState } from "react";
import Modal from "./Modal.jsx";
import { listRbds } from "../api.js";

// Pick a saved RBD to embed as a sub-system block.
export default function SubsystemModal({ onClose, onPick }) {
  const [rbds, setRbds] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    listRbds()
      .then((d) => setRbds(d.rbds))
      .catch((e) => setError(e.message));
  }, []);

  return (
    <Modal title="Select a saved RBD" onClose={onClose}>
      {error && <div className="error">{error}</div>}
      {rbds === null ? (
        <p className="muted-line">Loading…</p>
      ) : rbds.length === 0 ? (
        <p className="muted-line">
          No saved RBDs yet. Build one and use “Save RBD” first.
        </p>
      ) : (
        <table className="lib-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Nodes</th>
              <th>Saved</th>
            </tr>
          </thead>
          <tbody>
            {rbds.map((r) => (
              <tr
                key={r.id}
                className="lib-row"
                onClick={() => onPick({ id: r.id, name: r.name })}
              >
                <td className="lib-name">{r.name}</td>
                <td>{r.n_nodes}</td>
                <td className="lib-date">
                  {new Date(r.created_at).toLocaleDateString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Modal>
  );
}
