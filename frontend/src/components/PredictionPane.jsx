import { useEffect, useMemo, useRef, useState } from "react";
import {
  addPositionPart, getPositionParts, getPredictionEnvironments, linkPositionModel, previewPositionPrediction,
  removePositionPart, updatePositionPart,
} from "../api.js";
import TablePane from "./TablePane.jsx";
import RowMenu from "./RowMenu.jsx";
import { MoreIcon, PlusIcon } from "./icons.jsx";
import { NewPartModal, PartEntryModal } from "./PartForms.jsx";
import { FormModal } from "./MaintenanceParts.jsx";
import { ImportBomModal } from "./MaintenanceStructure.jsx";
import { useKinds } from "./MaintenanceItemClasses.jsx";
import Field from "./ui/Field.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import { NotElectronic, OwnRate, PartTypeChoice } from "./PartTypeCell.jsx";
import ConditionsModal from "./ConditionsModal.jsx";
import { saveErrorText } from "../confirm.js";
import { defaultQuality, fmtPerMillion, fmtQuantity, handbookConditionsLabel, qualityHint } from "../predictions.js";
import { predictionAssign } from "../explorerModels.js";
import {
  branchPositions, conditionsLabel, isCovariateLine, leftOutKeys, lineChange, lineFromPreview, lineKey, lineMenu, lineMode,
  mergeLines, noPartsText, predictionKey, predictionResult, predictionTitle, quantityTyped, removeQuestion, resultLines,
} from "../predictionPane.js";
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
// The lines are the parts lists' (Derryn, 9 Nov 2026: "definitely need a way to add and remove
// rows"), changed from here with the same forms as everywhere else (PartForms.jsx): "+ Add a part"
// (a new part, on this position or one inside it) or "Add an existing part…", and Import a BOM when
// there are none. Each line's ⋯ (or right-click): change its quantity (on its parts list), leave
// it out of this prediction (kept on the list; saved with the prediction, so a refresh leaves it
// out again) or take it off its parts list.
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
  const [branch, setBranch] = useState([]); // the position and those inside it, for "On"
  const [menu, setMenu] = useState(null); // {i, at}
  const [modal, setModal] = useState(null); // "new" | "existing" | "bom" | {remove: line} | {conditions: i}
  const [toast, setToast] = useState(null); // {text, undo?}
  const [reload, setReload] = useState(0); // read the parts lists again
  const [kinds] = useKinds();
  const merging = useRef(false);
  const focusKey = useRef(null);
  const setSaving = (v) => { setSavingState(v); onSaving?.(v); };
  const seq = useRef(0);
  // What it opened with (once the parts list is read): leaving it for another row asks first only
  // when something has changed since.
  const opened = useRef(null);
  const title = predictionTitle(link);
  const rowId = (i) => `pred2-row-${position.id}-${i}`;

  useEffect(() => { getPredictionEnvironments().then((d) => setEnvs(d.environments || []), () => {}); }, []);

  const body = useMemo(() => ({
    ...(environment ? { environment } : {}),
    ...(Number(mission) > 0 ? { mission_time: Number(mission) } : {}),
    ...(lines ? { assign: predictionAssign(lines), left_out: leftOutKeys(lines) } : {}),
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
        setBranch(d.branch || []);
        if (!environment) setEnvironment(d.environment);
        if (lines === null) {
          const byResult = resultLines(d.lines, d.results);
          const first = d.lines.map((l, i) => lineFromPreview(l, byResult[i]));
          opened.current = predictionKey({ environment: environment || d.environment, mission, lines: first });
          setLines(first);
        } else if (merging.current) {
          merging.current = false;
          setLines((old) => {
            const got = mergeLines(old || [], d.lines, d.results);
            if (got.added.length) focusKey.current = got.added[got.added.length - 1];
            return got.lines;
          });
        }
      }, (e) => {
        if (mine !== seq.current) return;
        setBusy(false);
        setError(e.message);
      });
    }, 300);
    return () => clearTimeout(t);
  }, [JSON.stringify(body), position.id, reload]); // eslint-disable-line react-hooks/exhaustive-deps

  // A part just added: its part-type picker takes the focus.
  useEffect(() => {
    const key = focusKey.current;
    if (!key || !lines) return;
    const i = lines.findIndex((l) => lineKey(l) === key);
    if (i < 0) return;
    focusKey.current = null;
    const row = document.getElementById(rowId(i));
    row?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    row?.querySelector(".pred2-c-type input, .pred2-c-type button")?.focus({ preventScroll: true });
  }, [lines]); // eslint-disable-line react-hooks/exhaustive-deps

  // Read the parts lists again (a part added, removed or its quantity changed), keeping each
  // line's choices.
  const refresh = () => { merging.current = true; setReload((n) => n + 1); };
  const say = (text, undo = null) => setToast({ text, undo });
  // The note goes after a while (longer while it offers Undo).
  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(null), toast.undo ? 15000 : 8000);
    return () => clearTimeout(t);
  }, [toast]);

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
  const qtyId = (i) => `pred2-qty-${position.id}-${i}`;
  const byResult = lines ? resultLines(lines, result) : [];
  const places = branchPositions(branch.length ? branch : [{ id: position.id, name: position.name, depth: 0 }], lines || []);

  const setQuantity = async (i, text) => {
    const l = lines[i];
    const q = quantityTyped(text, l.quantity);
    if (q == null || !l.listing_id) return;
    setLine(i, { quantity: q });
    try {
      await updatePositionPart(l.listing_id, { quantity: q });
      refresh();
    } catch (e) {
      setLine(i, { quantity: l.quantity });
      setError(e.message);
    }
  };
  const removeLine = async (l) => {
    // What the entry was, so Undo puts it back as it was.
    let was = null;
    try { was = (await getPositionParts(l.position.id)).parts_list.find((x) => x.id === l.listing_id) || null; } catch { was = null; }
    await removePositionPart(l.listing_id);
    setModal(null);
    refresh();
    const back = was && {
      part_id: was.part.id, role: was.role, quantity: was.quantity, critical: was.critical, notes: was.notes,
      ...(was.critical ? { min_on_hand: was.min_on_hand } : {}),
    };
    say(`Removed ${l.name} from ${l.position.name}’s parts list.`, back ? async () => {
      try {
        await addPositionPart(l.position.id, back);
        say(`Put ${l.name} back on ${l.position.name}’s parts list.`);
        refresh();
      } catch (e) {
        say(`Couldn't put it back: ${e.message}`);
      }
    } : null);
  };
  const choose = (i, id) => {
    const l = lines[i];
    if (id === "quantity") setTimeout(() => { const el = document.getElementById(qtyId(i)); el?.focus(); el?.select?.(); }, 0);
    else if (id === "out") setLine(i, { left_out: true });
    else if (id === "back") setLine(i, { left_out: false });
    else if (id === "remove") setModal({ remove: l });
  };
  const openMenu = (i, at) => setMenu({ i, at });

  return (
    <TablePane title={title} subject={position.name} phone={phone} busy={saving} headingRef={headingRef} onClose={onClose}
               className="pred-pane">
      <div className="pred2">
        <div className="pred2-in">
          <p className="rw-fhelp pred2-help">
            A parts count predicts {position.name}’s failure rate from its parts, before there’s failure data: each
            electronic part’s handbook base rate (MIL-HDBK-217F), times factors for the environment and its quality, and
            each mechanical part’s NSWC-11 model under its conditions, added up as if every part were needed. It compares
            designs early; it doesn’t say how it will fail in service.
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
            <div className="pred2-empty">
              <p className="rim-tquiet">{noPartsText(position.name)}</p>
              <div className="maint-row">
                <button type="button" className="sm" onClick={() => setModal("new")}><PlusIcon /> Add a part</button>
                <button type="button" className="secondary sm" onClick={() => setModal("existing")}>Add an existing part…</button>
                <button type="button" className="secondary sm" onClick={() => setModal("bom")}>Import a BOM</button>
              </div>
            </div>
          )}
          {lines?.length > 0 && (
            <div className="maint-scroll pred2-lines">
              <table className="ml-params pred2-table">
                <thead>
                  <tr>
                    <th>Part</th>
                    <th className="num">Qty</th>
                    <th>Handbook part type</th>
                    <th className="num pred2-wrap" title="πQ: left blank, the part type's default grade (1, or the lowest grade for a parts-count type such as a commercial microcircuit). An NSWC-11 part takes its conditions instead.">Quality or conditions</th>
                    <th className="pred2-c-ne pred2-wrap" title="Not an electronic part (an airframe, a propeller): the handbook has no rate for it, so it's left out of the total and the result says so.">Not electronic</th>
                    <th className="pred2-wrap">Your own rate</th>
                    <th className="num">λ per 10⁶ h</th>
                    <th className="pred2-c-more"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((l, i) => {
                    const r = byResult[i];
                    const mode = lineMode(l);
                    const off = !!l.left_out;
                    const hasType = !!(l.record?.id || l.record_id);
                    const change = (c) => setLine(i, lineChange(c));
                    return (
                      <tr key={lineKey(l) || `${l.reference}:${i}`} id={rowId(i)}
                          className={off ? "is-off pred2-out-row" : mode === "excluded" ? "is-off" : undefined}
                          onContextMenu={(e) => { e.preventDefault(); openMenu(i, { x: e.clientX, y: e.clientY }); }}>
                        <td className="pred2-c-part">
                          <span className="pred2-name">{l.name}</span>
                          {(l.reference || l.assembly?.length) ? (
                            <span className="pred2-ref">{[l.reference, l.assembly?.length ? l.assembly.join(" › ") : null].filter(Boolean).join(" · ")}</span>
                          ) : null}
                        </td>
                        <td className="num pred2-c-qty">
                          {l.listing_id && !off ? (
                            <TextInput id={qtyId(i)} key={`q${l.quantity}`} inputMode="decimal" className="pred2-qty"
                                       aria-label={`Quantity of ${l.name}`} title={`On ${l.position?.name || "its"} parts list`}
                                       defaultValue={String(l.quantity)}
                                       onBlur={(e) => setQuantity(i, e.target.value)}
                                       onKeyDown={(e) => {
                                         if (e.key === "Enter") e.currentTarget.blur();
                                         if (e.key === "Escape") { e.currentTarget.value = String(l.quantity); e.currentTarget.blur(); }
                                       }} />
                          ) : fmtQuantity(l.quantity)}
                        </td>
                        <td className="pred2-c-type">
                          {off ? (
                            <span className="pred2-left">Left out of this prediction{" "}
                              <button type="button" className="link" onClick={() => setLine(i, { left_out: false })}>Put back</button>
                            </span>
                          ) : mode === "excluded" ? <span className="rw-blank">Left out: not electronic</span>
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
                          {isCovariateLine(l) && !off ? (
                            <button type="button" className={"secondary sm pred2-cond" + (r?.needs_conditions ? " is-needed" : "")}
                                    aria-label={`Conditions of ${l.name}`} title="The conditions it works in: the NSWC-11 model's inputs"
                                    onClick={() => setModal({ conditions: i })}>
                              {conditionsLabel(l)}
                            </button>
                          ) : (
                          <span className="pred-q-cell">
                            <TextInput inputMode="decimal" className="pred2-q" aria-label={`Quality factor of ${l.name}`}
                                       value={l.quality_factor == null ? "" : String(l.quality_factor)}
                                       placeholder={hasType ? defaultQuality(l.record) : "—"} title={qualityHint(l.record)}
                                       disabled={off || !hasType || mode === "excluded"}
                                       onChange={(e) => setLine(i, { quality_factor: e.target.value })} />
                            {hasType && !off && mode !== "excluded" && (
                              <button type="button" className="secondary sm" aria-label={`Environment and grade of ${l.name}`}
                                      onClick={() => setModal({ conditions: i })}>
                                {handbookConditionsLabel(l)}
                              </button>
                            )}
                          </span>
                          )}
                        </td>
                        <td className="pred2-c-ne">
                          {off ? null : <NotElectronic name={l.name} excluded={l.excluded} onChange={change}>{null}</NotElectronic>}
                        </td>
                        <td className="pred2-c-rate">
                          <OwnRate id={rateId(i)} name={l.name} onChange={change} unit="per 10⁶ h"
                                   rate={mode === "rate" ? (l.rate_per_million_hours ?? "") : ""} placeholder={mode === "rate" ? "Rate" : "—"}
                                   disabled={off || mode === "excluded" || hasType}
                                   why={hasType ? "Clear the part type to give a rate of your own" : "A rate of your own, for a part the handbook doesn't have (a battery)"} />
                        </td>
                        <td className="num pred2-c-lambda">{r?.rate_per_million_hours != null ? fmtPerMillion(r.rate_per_million_hours)
                          : r?.needs_conditions ? <span className="pred2-needs" title={(r.line_warnings || []).join(" ")}>Needs conditions</span> : "—"}</td>
                        <td className="pred2-c-more">
                          <button type="button" className="ghost sm more-btn" aria-label={`Actions for ${l.name}`} title={`Actions for ${l.name}`}
                                  aria-haspopup="menu" aria-expanded={menu?.i === i}
                                  onClick={(e) => { const b = e.currentTarget.getBoundingClientRect(); openMenu(i, { x: b.right, y: b.bottom + 4 }); }}>
                            <MoreIcon />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr className="pred2-add">
                    <td colSpan={8}>
                      <div className="pred2-add-in">
                        <button type="button" className="link" onClick={() => setModal("new")}><PlusIcon /> Add a part</button>
                        <button type="button" className="link" onClick={() => setModal("existing")}>Add an existing part…</button>
                      </div>
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
          {toast && (
            <div className="pred2-toast" aria-live="polite">
              <span>{toast.text}</span>
              {toast.undo && <button type="button" className="secondary sm" onClick={() => { const u = toast.undo; setToast(null); u(); }}>Undo</button>}
              <button type="button" className="ghost sm" aria-label="Dismiss" onClick={() => setToast(null)}>✕</button>
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
                <p className="pred2-none">Give the parts their handbook part types to see the predicted failure rate:
                  MIL-HDBK-217F for electronic parts, NSWC-11 (with its conditions) for mechanical ones.</p>
              )}
              {out.rate && !out.reliability && <p className="pred2-sub">Give a mission time to see the chance of getting through it with no failure.</p>}
              <p className="pred2-sub">{out.counted}{out.environment ? ` · ${out.environment}` : ""}</p>
              {out.notElectronic.length > 0 && (
                <p className="pred2-sub"><b>Left out, not electronic:</b> {out.notElectronic.join(", ")}. The total is for the electronics.</p>
              )}
              {out.needsConditions.length > 0 && (
                <p className="pred2-sub"><b>Left out, needs its conditions:</b> {out.needsConditions.join(", ")}. Open Conditions… on the line.</p>
              )}
              {out.handbooks && <p className="pred2-sub"><b>Handbooks:</b> {out.handbooks}.</p>}
              {out.disclaimer && <p className="pred2-sub pred2-disclaimer">NSWC-11: {out.disclaimer}</p>}
              {out.noType.length > 0 && (
                <p className="pred2-sub"><b>Left out, no part type yet:</b> {out.noType.join(", ")}.</p>
              )}
              {out.leftOut.length > 0 && (
                <p className="pred2-sub"><b>Left out of this prediction:</b> {out.leftOut.join(", ")}. Still on the parts list.</p>
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
      {menu && lines?.[menu.i] && (
        <RowMenu items={lineMenu(lines[menu.i])} at={menu.at} label={`Actions for ${lines[menu.i].name}`} anchorId={rowId(menu.i)}
                 onChoose={(id) => choose(menu.i, id)}
                 onClose={() => {
                   const i = menu.i;
                   setMenu(null);
                   document.getElementById(rowId(i))?.querySelector(".more-btn")?.focus({ preventScroll: true });
                 }} />
      )}
      {modal === "new" && (
        <NewPartModal kinds={kinds} place={{ positions: places, positionId: position.id }} onClose={() => setModal(null)}
                      onDone={(part) => {
                        setModal(null);
                        const on = places.find((x) => x.id === part.on);
                        say(`Added ${part.name} to ${on?.name || position.name}’s parts list.`);
                        refresh();
                      }} />
      )}
      {modal === "existing" && (
        <PartEntryModal p={places[0]} positions={places} onClose={() => setModal(null)}
                        onDone={() => { setModal(null); refresh(); }} />
      )}
      {modal === "bom" && <ImportBomModal onClose={() => setModal(null)} onDone={() => { setModal(null); refresh(); }} />}
      {modal?.conditions != null && lines?.[modal.conditions] && (
        <ConditionsModal line={lines[modal.conditions]} environment={environment || null} onClose={() => setModal(null)}
                         onDone={(c) => { setLine(modal.conditions, c); setModal(null); }} />
      )}
      {modal?.remove && (
        <FormModal title="Remove from the parts list" submitLabel="Remove" pendingLabel="Removing…" danger
                   onClose={() => setModal(null)} onSubmit={() => removeLine(modal.remove)}>
          <p>{removeQuestion(modal.remove)}</p>
        </FormModal>
      )}
    </TablePane>
  );
}
