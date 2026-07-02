import { useState } from "react";
import Modal from "./Modal.jsx";
import ModelPicker from "./ModelPicker.jsx";

// Configure a standby-redundancy block: the active unit's life model, the
// number of spares, and (for cold standby) the start-success probability and an
// optional dormant failure model for the spares while in standby.
export default function StandbyModal({ initial, onClose, onSubmit }) {
  const [model, setModel] = useState(initial?.model ?? null);
  const [spares, setSpares] = useState(initial?.spares ?? 1);
  const [cold, setCold] = useState(initial?.cold ?? false);
  const [startProb, setStartProb] = useState(initial?.startProb ?? 1);
  const [standbyModel, setStandbyModel] = useState(initial?.standbyModel ?? null);

  const sparesNum = Number(spares);
  const probNum = Number(startProb);
  const validSpares = Number.isInteger(sparesNum) && sparesNum >= 1;
  const validProb = !cold || (probNum >= 0 && probNum <= 1);
  const valid = validSpares && validProb;

  const submit = () => {
    if (!valid) return;
    onSubmit({
      model,
      spares: sparesNum,
      cold,
      startProb: cold ? probNum : 1,
      standbyModel: cold ? standbyModel : null,
    });
  };

  const footer = (
    <>
      <span className="hint">One active unit with {spares} standby spare(s).</span>
      <div className="row" style={{ margin: 0 }}>
        <button className="secondary" onClick={onClose}>
          Cancel
        </button>
        <button onClick={submit} disabled={!valid}>
          Set standby
        </button>
      </div>
    </>
  );

  return (
    <Modal title="Standby redundancy" onClose={onClose} footer={footer}>
      <ModelPicker
        label="Active unit life model"
        value={model}
        onChange={setModel}
      />

      <div className="param-fields" style={{ marginTop: "1.25rem" }}>
        <label className="param-field">
          <span>spares</span>
          <input
            type="number"
            min="1"
            value={spares}
            onChange={(e) => setSpares(e.target.value)}
          />
        </label>
      </div>

      <label className="standby-toggle">
        <input
          type="checkbox"
          checked={cold}
          onChange={(e) => setCold(e.target.checked)}
        />
        Cold standby (spares must start when switched in)
      </label>

      {cold && (
        <div className="standby-cold">
          <div className="param-fields">
            <label className="param-field">
              <span>start success p</span>
              <input
                type="number"
                step="any"
                min="0"
                max="1"
                value={startProb}
                onChange={(e) => setStartProb(e.target.value)}
              />
            </label>
          </div>
          <ModelPicker
            label="Standby failure model (optional, dormant)"
            value={standbyModel}
            onChange={setStandbyModel}
          />
        </div>
      )}
    </Modal>
  );
}
