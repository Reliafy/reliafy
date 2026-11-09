import { useEffect, useState } from "react";
import { getLibraryRecord } from "../api.js";
import Modal from "./Modal.jsx";
import CovariateCalculator from "./CovariateCalculator.jsx";
import { modelWords } from "../covariate.js";

// "Conditions…" for a parts-list line: the part type's covariates in the one calculator (the same
// as the record page's Try it). An NSWC-11 part type (a covariate model): its inputs with their
// units, defaults and the handbook's limits, and its rate as they change. A MIL-HDBK-217F part type:
// its own environment (left blank, the prediction's) and its quality grade. Done keeps them on the
// line (saved with the prediction; a refresh keeps them).
//
//   line      {name, record: {id, name}, conditions, cycles_per_hour, environment, quality}
//   environment  the prediction's (the line's default)
//   onDone    ({conditions, cycles_per_hour}) or ({environment, quality})        onClose

const HANDBOOK_KEYS = ["environment", "quality"];

export default function ConditionsModal({ line, environment = null, onDone, onClose }) {
  const recordId = line.record?.id || line.record_id;
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [values, setValues] = useState(() => Object.fromEntries(Object.entries(line.conditions || {}).map(([k, v]) => [k, String(v)])));
  const [own, setOwn] = useState(() => ({ environment: line.environment || "", quality: line.quality || "" }));
  const [cycles, setCycles] = useState(line.cycles_per_hour != null ? String(line.cycles_per_hour) : "");
  useEffect(() => { getLibraryRecord(recordId).then(setD, (e) => setError(e.message)); }, [recordId]);
  const cov = d?.covariate;
  // A handbook part's own covariates: its environment shows the prediction's when the line has none.
  const handbook = d && !cov ? (d.covariates || []).filter((i) => HANDBOOK_KEYS.includes(i.key))
    .map((i) => (i.key === "environment" && environment ? { ...i, default: environment, default_basis: "prediction" } : i)) : [];
  const done = () => onDone(cov ? { conditions: values, cycles_per_hour: cycles }
    : { environment: own.environment || "", quality: own.quality || "" });
  return (
    <Modal title={`${cov ? "Conditions" : "Environment and grade"}: ${line.name}`} onClose={onClose} className="cov-modal"
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose}>Cancel</button>
               <button type="button" onClick={done} disabled={!d}>Done</button>
             </>
           )}>
      {error && <div className="card error" role="alert">{error}</div>}
      {!d && !error && <p className="rim-tquiet">Reading the model…</p>}
      {d && cov && (
        <>
          <p className="cov-intro"><b>{d.record.name}</b> (NSWC-11 Eq. {cov.equation}). {modelWords(d.record)}</p>
          <CovariateCalculator recordId={recordId} inputs={cov.inputs} unit={cov.rate_unit} values={values} onChange={setValues}
                               cycles={cycles} onCycles={setCycles} idPrefix="cond" />
          {d.disclaimer && <p className="rim-tquiet cov-note">{d.disclaimer}</p>}
        </>
      )}
      {d && !cov && (handbook.length ? (
        <>
          <p className="cov-intro"><b>{d.record.label}</b>. Left blank, the environment is the prediction’s and the grade the handbook’s lowest.</p>
          <CovariateCalculator recordId={recordId} inputs={handbook} values={own} onChange={setOwn} idPrefix="hb" />
        </>
      ) : <p>{d.record.label} has no environment or grade of its own to set.</p>)}
    </Modal>
  );
}
