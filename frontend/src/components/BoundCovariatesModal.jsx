import { useState } from "react";
import Modal from "./Modal.jsx";
import BoundBlockFields from "./BoundBlockFields.jsx";
import { cleanConditions } from "../covariate.js";
import "./CovariateCalculator.css";

// The covariates an RBD's blocks take that their positions left open (covariate_binding.py): the
// diagram's Use and Environment values first ("Environment: 40 °C"), which every block with that
// covariate takes unless it says otherwise, then each block's own, each showing the value it's
// using and where it came from. Apply puts them on the diagram (unsaved until the diagram is).
//
//   graph       the diagram (its nodes and conditions)
//   onApply({conditions, nodeData: {id: {covariate_values, covariate_map}}})      onClose

export default function BoundCovariatesModal({ graph, onApply, onClose }) {
  const [rows, setRows] = useState(() => (graph.conditions || []).map((c) => ({ ...c, value: String(c.value) })));
  const [nodeData, setNodeData] = useState({});
  const bound = (graph.nodes || []).filter((n) => n.data?.model?.kind === "bound");
  const conditions = cleanConditions(rows);
  const set = (i, change) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...change } : r)));
  return (
    <Modal title="Covariates for the blocks" onClose={onClose} className="cov-modal"
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose}>Cancel</button>
               <button type="button" onClick={() => onApply({ conditions, nodeData })}>Apply</button>
             </>
           )}>
      <section aria-labelledby="bcm-diagram">
        <h3 id="bcm-diagram" className="ml-h">The diagram’s Use and Environment values</h3>
        <p className="rim-tquiet">Every block with a covariate of the same name and unit takes these unless it sets its own
          below (or picks one of these under another name).</p>
        <div className="maint-scroll">
          <table className="ml-params bcm-table">
            <thead><tr><th>Name</th><th>What it is</th><th>Unit</th><th>Value</th><th><span className="sr-only">Remove</span></th></tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td><input type="text" aria-label={`Name of value ${i + 1}`} value={r.name} onChange={(e) => set(i, { name: e.target.value })} /></td>
                  <td>
                    <select aria-label={`What value ${i + 1} is`} value={r.role || "environment"} onChange={(e) => set(i, { role: e.target.value })}>
                      <option value="use">Use</option><option value="environment">Environment</option>
                    </select>
                  </td>
                  <td><input type="text" aria-label={`Unit of value ${i + 1}`} value={r.unit || ""} onChange={(e) => set(i, { unit: e.target.value })} /></td>
                  <td><input type="text" inputMode="decimal" aria-label={`Value ${i + 1}`} value={r.value ?? ""} onChange={(e) => set(i, { value: e.target.value })} /></td>
                  <td><button type="button" className="ghost sm" aria-label={`Remove value ${i + 1}`} onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}>×</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button type="button" className="link" onClick={() => setRows((rs) => [...rs, { name: "", role: "environment", unit: "", value: "" }])}>+ Add a value</button>
      </section>
      {bound.map((n) => (
        <section key={n.id} className="bcm-block" aria-label={`Covariates of ${n.data.label || n.id}`}>
          <h3 className="ml-h">{n.data.label || n.id} <span className="rim-tquiet">· {n.data.model.name || "covariate model"}</span></h3>
          <BoundBlockFields node={n} conditions={conditions} idPrefix={`bcm-${n.id}`}
                            onChange={(d) => setNodeData((x) => ({ ...x, [n.id]: d }))} />
        </section>
      ))}
    </Modal>
  );
}
