import { useEffect, useRef, useState } from "react";
import { getBoundBlocks } from "../api.js";
import CovariateInputs from "./CovariateInputs.jsx";
import { fmtRate } from "../covariate.js";

// An RBD block whose model's covariates were left open at its position (NSWC-11, accelerated life
// or proportional hazards; covariate_binding.py): those inputs, each set here for this block or
// taken from the diagram's Use and Environment values (by name and unit, or the one chosen), and
// what each is using and where it came from. Uses the one covariate input component.
//
//   node {id, type, data}   conditions  the diagram's [{name, role, unit, value}]
//   onChange({covariate_values, covariate_map})

export default function BoundBlockFields({ node, conditions = [], onChange, idPrefix }) {
  const data = node?.data || {};
  const [values, setValues] = useState(() => Object.fromEntries(Object.entries(data.covariate_values || {}).map(([k, v]) => [k, String(v)])));
  const [map, setMap] = useState(data.covariate_map || {});
  const [got, setGot] = useState(null);
  const [error, setError] = useState(null);
  const seq = useRef(0);
  const cleaned = () => Object.fromEntries(Object.entries(values).filter(([, v]) => String(v ?? "").trim() !== "")
    .map(([k, v]) => [k, Number.isFinite(Number(v)) && String(v).trim() !== "" ? Number(v) : v]));
  const sig = JSON.stringify([values, map, conditions]);
  useEffect(() => {
    const mine = ++seq.current;
    const t = setTimeout(() => {
      const one = { id: node.id, type: node.type || "component", data: { ...data, covariate_values: cleaned(), covariate_map: map } };
      getBoundBlocks({ nodes: [one], conditions }).then((d) => {
        if (mine !== seq.current) return;
        setGot(d.blocks?.[0] || null);
        setError(null);
      }, (e) => mine === seq.current && setError(e.message));
    }, 200);
    return () => clearTimeout(t);
  }, [sig]); // eslint-disable-line react-hooks/exhaustive-deps
  const emit = (v, m) => onChange?.({ covariate_values: Object.keys(v).length ? v : null, covariate_map: Object.keys(m).length ? m : null });
  const fixed = Object.entries(data.model?.binding?.fixed || {});
  // What each value is when not typed here: the diagram's, or a default (typed ones are this block's).
  const sources = Object.fromEntries(Object.entries(got?.sources || {}).filter(([k, s]) => s.from !== "block" && k));
  return (
    <div className="bound-block">
      {error && <p className="field-error" role="alert">{error}</p>}
      {fixed.length > 0 && (
        <p className="rim-tquiet">Fixed at its position: {fixed.map(([k, v]) => `${k} ${typeof v === "number" ? fmtRate(v) : v}`).join(", ")}.</p>
      )}
      {got?.problem && <p className="field-error">{got.problem}</p>}
      {got && !got.problem && got.inputs.length === 0 && <p className="rim-tquiet">Every covariate is fixed at its position.</p>}
      {got && got.inputs.length > 0 && (
        <CovariateInputs inputs={got.inputs} values={values} idPrefix={idPrefix || `bb-${node.id}`} sources={sources}
                         conditions={conditions} map={map}
                         onChange={(v) => {
                           setValues(v);
                           const c = Object.fromEntries(Object.entries(v).filter(([, x]) => String(x ?? "").trim() !== "")
                             .map(([k, x]) => [k, Number.isFinite(Number(x)) ? Number(x) : x]));
                           emit(c, map);
                         }}
                         onMap={(k, name) => {
                           const m = { ...map };
                           if (name) m[k] = name; else delete m[k];
                           setMap(m);
                           emit(cleaned(), m);
                         }} />
      )}
      {got?.needs && <p className="field-error" role="status">{got.needs}: set them here, or as the diagram’s Use and Environment values.</p>}
    </div>
  );
}
