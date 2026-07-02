import { useCallback, useEffect, useState } from "react";
import Modal from "./Modal.jsx";
import { listRbds, deleteRbd } from "../api.js";

// Library of saved RBDs: open one into the canvas, or delete.
export default function RbdOpenModal({ onClose, onOpen }) {
  const [rbds, setRbds] = useState(null);
  const [error, setError] = useState(null);

  const refresh = useCallback(() => {
    listRbds()
      .then((d) => setRbds(d.rbds))
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => refresh(), [refresh]);

  const remove = async (e, r) => {
    e.stopPropagation();
    if (!window.confirm(`Delete RBD “${r.name}”?`)) return;
    await deleteRbd(r.id);
    refresh();
  };

  return (
    <Modal title="Open a saved RBD" onClose={onClose}>
      {error && <div className="error">{error}</div>}
      {rbds === null ? (
        <p className="muted-line">Loading…</p>
      ) : rbds.length === 0 ? (
        <p className="muted-line">No saved RBDs yet. Build one and use “Save RBD”.</p>
      ) : (
        <table className="lib-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Nodes</th>
              <th>Saved</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rbds.map((r) => (
              <tr key={r.id} className="lib-row" onClick={() => onOpen(r.id)}>
                <td className="lib-name">{r.name}</td>
                <td>{r.n_nodes}</td>
                <td className="lib-date">
                  {new Date(r.updated_at || r.created_at).toLocaleDateString()}
                </td>
                <td className="lib-actions">
                  <button className="lib-del" onClick={(e) => remove(e, r)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Modal>
  );
}
