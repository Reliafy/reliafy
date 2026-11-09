import { useEffect, useState } from "react";
import { getLibraryRecord } from "../api.js";
import Modal from "./Modal.jsx";
import CovariateCalculator from "./CovariateCalculator.jsx";
import { modelWords } from "../covariate.js";

// "Conditions…" for a parts-list line on an NSWC-11 part type (a covariate model): the model's
// inputs with their units, defaults and the handbook's limits, and its rate as they change, in the
// same CovariateCalculator as the record page's Try it. Done keeps them on the line (saved with the
// prediction; a refresh keeps them).
//
//   line      {name, record: {id, name}, conditions, cycles_per_hour}
//   onDone    ({conditions, cycles_per_hour})        onClose

export default function ConditionsModal({ line, onDone, onClose }) {
  const recordId = line.record?.id || line.record_id;
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [values, setValues] = useState(() => Object.fromEntries(Object.entries(line.conditions || {}).map(([k, v]) => [k, String(v)])));
  const [cycles, setCycles] = useState(line.cycles_per_hour != null ? String(line.cycles_per_hour) : "");
  useEffect(() => { getLibraryRecord(recordId).then(setD, (e) => setError(e.message)); }, [recordId]);
  const cov = d?.covariate;
  const done = () => onDone({ conditions: values, cycles_per_hour: cycles });
  return (
    <Modal title={`Conditions: ${line.name}`} onClose={onClose} className="cov-modal"
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose}>Cancel</button>
               <button type="button" onClick={done} disabled={!cov}>Done</button>
             </>
           )}>
      {error && <div className="card error" role="alert">{error}</div>}
      {!d && !error && <p className="rim-tquiet">Reading the model…</p>}
      {d && (
        <>
          <p className="cov-intro"><b>{d.record.name}</b> (NSWC-11 Eq. {cov.equation}). {modelWords(d.record)}</p>
          <CovariateCalculator recordId={recordId} inputs={cov.inputs} unit={cov.rate_unit} values={values} onChange={setValues}
                               cycles={cycles} onCycles={setCycles} idPrefix="cond" />
          {d.disclaimer && <p className="rim-tquiet cov-note">{d.disclaimer}</p>}
        </>
      )}
    </Modal>
  );
}
