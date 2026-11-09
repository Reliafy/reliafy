import { useEffect, useMemo, useRef, useState } from "react";
import { getPredictionEnvironments, linkPositionModel, previewPositionPrediction } from "../api.js";
import TablePane from "./TablePane.jsx";
import Field from "./ui/Field.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import { NotElectronic, OwnRate, PartTypeChoice } from "./PartTypeCell.jsx";
import { saveErrorText } from "../confirm.js";
import { defaultQuality, fmtPerMillion, fmtQuantity, qualityHint } from "../predictions.js";
import { predictionAssign } from "../explorerModels.js";
import { lineChange, lineMode, predictionKey, predictionResult, predictionTitle } from "../predictionPane.js";
import "./ModelTable.css";
import "./PredictionPane.css";

// "Add a prediction (parts count)…" on the Modelling tab, in the Explorer's table area (Derryn,
// 9 Nov 2026: reliability prediction "by the parts/component method; this is the only place that
// should go", and it "should also be the same, where it fills up the table area of the explorer
// view"): a parts count of the position from its parts list and those of the positions inside it
// (a product design's bill of materials where they list none). Set the environment once; give each
// part a handbook part type (and a quality factor where the handbook has one), a rate of the user's
// own for a part the handbook doesn't have (a battery), or tick "Not electronic" for a mechanical
// part (an airframe, a propeller) to leave it out. The parts table takes the width; the result
// beside it (under it when narrow) is the server's preview, asked again a moment after each change:
// the total failure rate, the MTBF, the reliability over the mission time and what was left out.
// Saved, it's a prediction on the Predictions page and an exponential model at its rate, attached
// here.
//
//   position  {id, name}      link  the position's prediction row, when refreshing it
//   onDone    (link, text)    onDirty (changed)    onSaving (busy)    phone, headingRef: TablePane's

export default function PredictionPane({ position, link = null, phone = false, headingRef = null, onClose, onDone, onDirty, onSaving }) {
  const [envs, setEnvs] = useState([]);
  const [environment, setEnvironment] = useState(link?.source?.environment || "");
  const [mission, setMission] = useState(link?.source?.mission_time ? String(link.source.mission_time) : "");
  const [lines, setLines] = useState(null); // [{part_id, reference, name, quantity, assembly, record, quality_factor, rate_per_million_hours, rate_mode, excluded}]
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [saving, setSavingState] = useState(false);
  const setSaving = (v) => { setSavingState(v); onSaving?.(v); };
  const seq = useRef(0);
  // What it opened with (once the parts list is read): leaving it for another row asks first only
  // when something has changed since.
  const opened = useRef(null);
  const title = predictionTitle(link);

  useEffect(() => { getPredictionEnvironments().then((d) => setEnvs(d.environments || []), () => {}); }, []);

  const body = useMemo(() => ({
    ...(environment ? { environment } : {}),
    ...(Number(mission) > 0 ? { mission_time: Number(mission) } : {}),
    ...(lines ? { assign: predictionAssign(lines) } : {}),
  }), [environment, mission, lines]);

  // The preview, a moment after each change: the lines (with the part types it knows), the result.
  useEffect(() => {
    const mine = ++seq.current;
    setBusy(true);
    const t = setTimeout(() => {
      previewPositionPrediction(position.id, body).then((d) => {
        if (mine !== seq.current) return;
        setError(null);
        setBusy(false);
        setResult(d.results);
        if (!environment) setEnvironment(d.environment);
        if (lines === null) {
          const first = d.lines.map((l, i) => {
            const r = (d.results?.lines || [])[i];
            return { ...l, record: l.record_id ? { id: l.record_id, name: r?.part_type || l.record_id } : null };
          });
          opened.current = predictionKey({ environment: environment || d.environment, mission, lines: first });
          setLines(first);
        }
      }, (e) => {
        if (mine !== seq.current) return;
        setBusy(false);
        setError(e.message);
      });
    }, 300);
    return () => clearTimeout(t);
  }, [JSON.stringify(body), position.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const changed = opened.current != null && lines != null && predictionKey({ environment, mission, lines }) !== opened.current;
  useEffect(() => { onDirty?.(changed); }, [changed]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    setSaving(true);
    try {
      const made = await linkPositionModel(position.id, { prediction: body, ...(link ? { replace_link_id: link.id } : {}) });
      setSaving(false);
      onDone(made, `Saved the parts-count prediction for ${position.name}.`);
    } catch (e) {
      setSaving(false);
      setError(saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };
  const setLine = (i, change) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...change } : l)));
  const out = predictionResult(result, mission);
  const rateId = (i) => `pred2-rate-${position.id}-${i}`;

  return (
    <TablePane title={title} subject={position.name} phone={phone} busy={saving} headingRef={headingRef} onClose={onClose}
               className="pred-pane">
      <div className="pred2">
        <div className="pred2-in">
          <p className="rw-fhelp pred2-help">
            A parts count predicts {position.name}’s failure rate from its parts, before there’s failure data: each
            part’s handbook base rate (MIL-HDBK-217F), times factors for the environment and its quality, added up as if
            every part were needed. It compares designs early; it doesn’t say how it will fail in service.
          </p>
          <div className="ml-row pred2-set">
            <Field label="Environment" help="Where it works: one for the whole position.">
              <Select value={environment} onChange={(e) => setEnvironment(e.target.value)}>
                {envs.map((e) => <option key={e.code} value={e.code}>{e.name} ({e.code})</option>)}
              </Select>
            </Field>
            <Field label="Mission time (hours)" optional help="For the chance of getting through it with no failure.">
              <TextInput inputMode="decimal" value={mission} onChange={(e) => setMission(e.target.value)} placeholder="1000" />
            </Field>
          </div>
          {error && <p className="field-error" role="alert">{error}</p>}
          {lines === null && !error && <p className="rim-tquiet">Reading its parts list…</p>}
          {lines?.length === 0 && (
            <p className="rim-tquiet">No parts listed on {position.name} or the positions inside it. Add parts on its Parts list first.</p>
          )}
          {lines?.length > 0 && (
            <div className="maint-scroll pred2-lines">
              <table className="ml-params pred2-table">
                <thead>
                  <tr>
                    <th>Part</th>
                    <th className="num">Qty</th>
                    <th>Handbook part type</th>
                    <th className="num pred2-wrap" title="πQ: left blank, the part type's default grade (1, or the lowest grade for a parts-count type such as a commercial microcircuit)">Quality factor</th>
                    <th className="pred2-c-ne pred2-wrap" title="Not an electronic part (an airframe, a propeller): the handbook has no rate for it, so it's left out of the total and the result says so.">Not electronic</th>
                    <th className="pred2-wrap">Your own rate</th>
                    <th className="num">λ per 10⁶ h</th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((l, i) => {
                    const r = (result?.lines || [])[i];
                    const mode = lineMode(l);
                    const hasType = !!(l.record?.id || l.record_id);
                    const change = (c) => setLine(i, lineChange(c));
                    return (
                      <tr key={`${l.reference}:${i}`} className={mode === "excluded" ? "is-off" : undefined}>
                        <td className="pred2-c-part">
                          <span className="pred2-name">{l.name}</span>
                          {(l.reference || l.assembly?.length) ? (
                            <span className="pred2-ref">{[l.reference, l.assembly?.length ? l.assembly.join(" › ") : null].filter(Boolean).join(" · ")}</span>
                          ) : null}
                        </td>
                        <td className="num">{fmtQuantity(l.quantity)}</td>
                        <td className="pred2-c-type">
                          {mode === "excluded" ? <span className="rw-blank">Left out</span>
                            : mode === "rate" ? (
                              <button type="button" className="link pred2-totype" onClick={() => change({ rate: "", rateMode: false })}>
                                Choose a part type instead
                              </button>
                            ) : (
                              <PartTypeChoice name={l.name} record={l.record} onChange={change}
                                              onUseRate={() => setTimeout(() => document.getElementById(rateId(i))?.focus(), 0)} />
                            )}
                        </td>
                        <td className="num">
                          <TextInput inputMode="decimal" className="pred2-q" aria-label={`Quality factor of ${l.name}`}
                                     value={l.quality_factor == null ? "" : String(l.quality_factor)}
                                     placeholder={hasType ? defaultQuality(l.record) : "—"} title={qualityHint(l.record)}
                                     disabled={!hasType || mode === "excluded"}
                                     onChange={(e) => setLine(i, { quality_factor: e.target.value })} />
                        </td>
                        <td className="pred2-c-ne">
                          <NotElectronic name={l.name} excluded={l.excluded} onChange={change}>{null}</NotElectronic>
                        </td>
                        <td className="pred2-c-rate">
                          <OwnRate id={rateId(i)} name={l.name} onChange={change} unit="per 10⁶ h"
                                   rate={mode === "rate" ? (l.rate_per_million_hours ?? "") : ""} placeholder={mode === "rate" ? "Rate" : "—"}
                                   disabled={mode === "excluded" || hasType}
                                   why={hasType ? "Clear the part type to give a rate of your own" : "A rate of your own, for a part the handbook doesn't have (a battery)"} />
                        </td>
                        <td className="num pred2-c-lambda">{r?.rate_per_million_hours != null ? fmtPerMillion(r.rate_per_million_hours) : "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <div className="pred2-out" role="region" aria-label="The prediction">
          <h3 className="ml-h">The prediction{busy && lines ? <span className="rw-sum"> · updating…</span> : null}</h3>
          {!out ? <p className="rim-tquiet">Working it out…</p> : (
            <div role="status" className="pred2-status">
              {out.rate ? (
                <>
                  <p className="pred2-big"><b>{out.rate}</b> failures per million hours</p>
                  <dl className="pred2-dl">
                    <dt>MTBF</dt><dd>about {out.mtbf} hours</dd>
                    {out.reliability && <><dt>Reliability</dt><dd>{out.reliability} chance of no failure in {out.mission} hours</dd></>}
                  </dl>
                </>
              ) : (
                <p className="pred2-none">Give the parts their handbook part types to see the predicted failure rate. The handbook
                  covers electronic parts only: tick “Not electronic” for mechanical parts.</p>
              )}
              {out.rate && !out.reliability && <p className="pred2-sub">Give a mission time to see the chance of getting through it with no failure.</p>}
              <p className="pred2-sub">{out.counted}{out.environment ? ` · ${out.environment}` : ""}</p>
              {out.notElectronic.length > 0 && (
                <p className="pred2-sub"><b>Left out, not electronic:</b> {out.notElectronic.join(", ")}. The total is for the electronics.</p>
              )}
              {out.noType.length > 0 && (
                <p className="pred2-sub"><b>Left out, no part type yet:</b> {out.noType.join(", ")}.</p>
              )}
            </div>
          )}
          <p className="pred2-sub pred2-how">It updates as you change the parts. Saved, it’s an exponential model at this rate, on this position and the Reliability prediction page.</p>
          <div className="pred2-foot">
            <button type="button" className="secondary" onClick={onClose} disabled={saving}>Cancel</button>
            <button type="button" onClick={save} disabled={saving || !out?.rate} aria-busy={saving || undefined}
                    title={!out?.rate ? "Give at least one part a handbook part type" : undefined}>
              {saving ? "Saving…" : "Save as this position's model"}
            </button>
          </div>
        </div>
      </div>
    </TablePane>
  );
}
