import { useEffect, useMemo, useRef, useState } from "react";
import { getPredictionEnvironments, linkPositionModel, previewPositionPrediction } from "../api.js";
import Modal from "./Modal.jsx";
import Field from "./ui/Field.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import PartTypePicker from "./PartTypePicker.jsx";
import { saveErrorText } from "../confirm.js";
import { fmtHours, fmtPerMillion } from "../predictions.js";
import { predictionAssign } from "../explorerModels.js";

// "Add a prediction…" on the Modelling tab (Derryn, 9 Nov 2026: reliability prediction "by
// the parts/component method; this is the only place that should go"): a parts count of the
// position from its parts list and those of the positions inside it (a product design's bill
// of materials where they list none). Set the environment once; give each part a handbook part
// type (and a quality factor where the handbook has one); the result updates as you go. Saved,
// it's a prediction on the Predictions page and an exponential model at its rate, attached here.
//
//   position  {id, name}      link  the position's prediction row, when refreshing it
//   onDone    (link, text)

export default function PredictionModal({ position, link = null, onClose, onDone }) {
  const [envs, setEnvs] = useState([]);
  const [environment, setEnvironment] = useState(link?.source?.environment || "");
  const [mission, setMission] = useState(link?.source?.mission_time ? String(link.source.mission_time) : "");
  const [lines, setLines] = useState(null); // [{part_id, reference, name, quantity, assembly, record, quality_factor}]
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const seq = useRef(0);

  useEffect(() => { getPredictionEnvironments().then((d) => setEnvs(d.environments || []), () => {}); }, []);

  const body = useMemo(() => ({
    ...(environment ? { environment } : {}),
    ...(Number(mission) > 0 ? { mission_time: Number(mission) } : {}),
    ...(lines ? { assign: predictionAssign(lines) } : {}),
  }), [environment, mission, lines]);

  // The preview, a moment after each change: the lines (with the part types it knows), the result.
  useEffect(() => {
    const mine = ++seq.current;
    const t = setTimeout(() => {
      previewPositionPrediction(position.id, body).then((d) => {
        if (mine !== seq.current) return;
        setError(null);
        setResult(d.results);
        if (!environment) setEnvironment(d.environment);
        setLines((was) => (was || []).length ? was : d.lines.map((l, i) => {
          const r = (d.results?.lines || [])[i];
          return { ...l, record: l.record_id ? { id: l.record_id, name: r?.part_type || l.record_id } : null };
        }));
      }, (e) => mine === seq.current && setError(e.message));
    }, 300);
    return () => clearTimeout(t);
  }, [JSON.stringify(body), position.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    setSaving(true);
    try {
      const made = await linkPositionModel(position.id, { prediction: body, ...(link ? { replace_link_id: link.id } : {}) });
      onDone(made, `Saved the parts-count prediction for ${position.name}.`);
    } catch (e) {
      setSaving(false);
      setError(saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };
  const setLine = (i, change) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...change } : l)));
  const rate = result?.failure_rate_per_million_hours;
  const counts = result?.counts || {};
  return (
    <Modal title={link ? "Refresh the prediction" : "Add a prediction"} onClose={onClose} locked={saving} trapFocus
           className="ml-dialog ml-predict"
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose} disabled={saving}>Cancel</button>
               <button type="button" onClick={save} disabled={saving || !rate} aria-busy={saving || undefined}
                       title={!rate ? "Give at least one part a handbook part type" : undefined}>
                 {saving ? "Saving…" : "Save as this position's model"}
               </button>
             </>
           )}>
      <p className="rw-fhelp">
        A parts count predicts {position.name}’s failure rate from the parts it’s made of, before there’s failure
        data: each part’s handbook base rate (MIL-HDBK-217F), times factors for the environment and its quality, added
        up as if every part were needed. It compares designs early; it doesn’t say how it will fail in service.
      </p>
      <div className="ml-row">
        <Field label="Environment" help="Where it works: one for the whole position.">
          <Select value={environment} onChange={(e) => setEnvironment(e.target.value)}>
            {envs.map((e) => <option key={e.code} value={e.code}>{e.name} ({e.code})</option>)}
          </Select>
        </Field>
        <Field label="Mission time (hours)" optional>
          <TextInput inputMode="decimal" value={mission} onChange={(e) => setMission(e.target.value)} placeholder="1000" />
        </Field>
      </div>
      {error && <p className="field-error" role="alert">{error}</p>}
      {lines === null && !error && <p className="rim-tquiet">Reading its parts list…</p>}
      {lines && (
        <div className="maint-scroll">
          <table className="ml-params ml-lines">
            <thead><tr><th>Part</th><th className="num">Qty</th><th>Handbook part type</th><th className="num">Quality factor</th><th className="num">Per 10⁶ h</th></tr></thead>
            <tbody>
              {lines.map((l, i) => {
                const r = (result?.lines || [])[i];
                return (
                  <tr key={`${l.reference}:${i}`}>
                    <td>{l.name}{l.reference ? <span className="rw-sum"> {l.reference}</span> : null}{l.assembly?.length ? <span className="rw-sum"> · {l.assembly.join(" › ")}</span> : null}</td>
                    <td className="num">{l.quantity}</td>
                    <td><PartTypePicker value={l.record} label={`Handbook part type of ${l.name}`} onChange={(record) => setLine(i, { record })} /></td>
                    <td className="num"><TextInput inputMode="decimal" aria-label={`Quality factor of ${l.name}`} value={String(l.quality_factor ?? 1)}
                                                   onChange={(e) => setLine(i, { quality_factor: e.target.value })} /></td>
                    <td className="num">{r?.rate_per_million_hours != null ? fmtPerMillion(r.rate_per_million_hours) : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {result && (
        <p className="ml-lead" role="status">
          {rate
            ? <>Predicted <b>{fmtPerMillion(rate)} failures per million hours</b>: an MTBF of about {fmtHours(result.mtbf_hours)} hours ({counts.assigned} of {counts.lines} parts with a part type).</>
            : <>Give the parts their handbook part types to see the predicted failure rate.</>}
        </p>
      )}
    </Modal>
  );
}
