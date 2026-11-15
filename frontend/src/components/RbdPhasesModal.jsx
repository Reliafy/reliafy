import { useEffect, useMemo, useState } from "react";
import Modal from "./Modal.jsx";
import { getPhaseCovariates } from "../api.js";
import { cleanPhases, phaseBlocks, voteNodes } from "../rbdMission.js";
import { BLOCK_STATES, STATE_SHORT, blockState, covValueText, isSchedule, withBlockState } from "../explorerMissions.js";
import PhaseCovValue from "./PhaseCovValue.jsx";
import "./RbdMission.css";

// The phased-mission editor (#160), from the builder's ⋯ menu: the mission's
// phases in order, each with a name and a duration, and — folded under each
// phase — each block's state in it (working, standby, guaranteed working, not
// needed), its covariate values (one per covariate the diagram's life models
// leave open: the same list, and the same stored values, as the Explorer's
// mission tree) and any vote node that needs a different number of its inputs
// in it. Stored as graph.phases (a mission's own RBD: that mission's phases);
// Save with no phases clears it.
//
//   initial   the diagram's phases (or none)
//   nodes, edges, unit   the live diagram, for the block and vote lists
//   onSubmit(phases | null), onClose

let rowKey = 0;
const newRow = (i) => ({ key: ++rowKey, name: `Phase ${i + 1}`, duration: "", not_needed: [], standby: [], guaranteed: [], dormancy: {}, votes: {}, values: {} });
const fromStored = (p) => ({
  key: ++rowKey,
  name: p.name || "",
  duration: p.duration ?? "",
  not_needed: [...(p.not_needed || [])],
  votes: { ...(p.votes || {}) },
  // The same settings the Explorer's mission tree edits: each block's state, the covariate values.
  values: { ...(p.values || {}) },
  block_values: p.block_values || null,
  standby: [...(p.standby || [])],
  guaranteed: [...(p.guaranteed || [])],
  dormancy: { ...(p.dormancy || {}) },
});

export default function RbdPhasesModal({ initial, nodes, edges, unit, conditions = [], onClose, onSubmit }) {
  const [rows, setRows] = useState(() => (initial?.length ? initial.map(fromStored) : [newRow(0)]));
  const [tried, setTried] = useState(false);
  const blocks = useMemo(() => phaseBlocks(nodes), [nodes]);
  const votes = useMemo(() => voteNodes(nodes, edges), [nodes, edges]);
  const labelOf = useMemo(() => new Map(blocks.map((b) => [b.id, b.label])), [blocks]);
  const { phases, errors } = cleanPhases(rows, nodes);
  const u = unit ? ` (${unit})` : "";
  // The covariates a phase can set: worked out from the diagram's life models by the server (one
  // list for the builder and the Explorer's tree).
  const [covs, setCovs] = useState([]);
  useEffect(() => {
    let live = true;
    getPhaseCovariates({ nodes, edges, unit, conditions }).then((d) => live && setCovs(d.rows || []), () => {});
    return () => { live = false; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const setValue = (row, name, v) => {
    const values = { ...(row.values || {}) };
    if (v == null || (typeof v !== "object" && String(v).trim() === "")) delete values[name];
    else values[name] = v;
    update(row.key, { values });
  };

  const update = (key, patch) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const move = (i, dir) =>
    setRows((rs) => {
      const j = i + dir;
      if (j < 0 || j >= rs.length) return rs;
      const out = [...rs];
      [out[i], out[j]] = [out[j], out[i]];
      return out;
    });

  const submit = () => {
    setTried(true);
    if (errors.length) return;
    onSubmit(phases.length ? phases : null);
  };

  const footer = (
    <>
      {initial?.length ? (
        <button type="button" className="secondary danger sm" onClick={() => onSubmit(null)}>
          Remove the phases
        </button>
      ) : (
        <span />
      )}
      <div className="row" style={{ margin: 0 }}>
        <button className="secondary" onClick={onClose}>Cancel</button>
        <button onClick={submit} disabled={tried && errors.length > 0}>Save phases</button>
      </div>
    </>
  );

  return (
    <Modal title="Phased mission" onClose={onClose} footer={footer} className="rbd-phases-modal">
      <p className="muted-line" style={{ marginTop: 0 }}>
        The mission runs through its phases in order. A block that fails in one phase stays failed for
        the rest of the mission, even through phases that don't need it.
      </p>
      <ol className="rbd-phase-list">
        {rows.map((row, i) => {
          const skipped = row.not_needed.filter((id) => labelOf.has(id));
          const standing = (row.standby || []).filter((id) => labelOf.has(id));
          const sure = (row.guaranteed || []).filter((id) => labelOf.has(id));
          const held = [...standing, ...sure];
          const named = (ids) => (ids.length === 1 ? labelOf.get(ids[0]) : `${ids.length} blocks`);
          const changed = votes.filter((v) => String(row.votes[v.id] ?? "").trim() !== "");
          const setCount = covs.filter((c) => String(row.values?.[c.name] ?? "").trim() !== "").length;
          const summary = [
            skipped.length
              ? `Doesn't need ${skipped.length === 1 ? labelOf.get(skipped[0]) : `${skipped.length} blocks`}`
              : held.length ? "Every block in use" : "Every block in use, wired as in the RBD",
            ...(standing.length ? [`${named(standing)} on standby`] : []),
            ...(sure.length ? [`${named(sure)} guaranteed working`] : []),
            ...changed.map((v) => `${v.label}: ${row.votes[v.id]} of ${v.inputs}`),
            ...(covs.length ? [`${setCount} of ${covs.length} covariate${covs.length === 1 ? "" : "s"} set`] : []),
          ].join(" · ");
          return (
            <li key={row.key} className="rbd-phase">
              <div className="rbd-phase-head">
                <span className="rbd-phase-n" aria-hidden="true">{i + 1}</span>
                <label className="rbd-phase-name">
                  <span>Name</span>
                  <input value={row.name} placeholder="Name" maxLength={80}
                         onChange={(e) => update(row.key, { name: e.target.value })} />
                </label>
                <label className="rbd-phase-duration">
                  <span>Duration{u}</span>
                  <input type="number" inputMode="decimal" min="0" step="any" value={row.duration} placeholder="—"
                         onChange={(e) => update(row.key, { duration: e.target.value })} />
                </label>
                <div className="rbd-phase-tools">
                  <button type="button" className="ghost sm" onClick={() => move(i, -1)} disabled={i === 0}
                          aria-label={`Move phase ${i + 1} earlier`} title="Earlier">↑</button>
                  <button type="button" className="ghost sm" onClick={() => move(i, 1)} disabled={i === rows.length - 1}
                          aria-label={`Move phase ${i + 1} later`} title="Later">↓</button>
                  <button type="button" className="ghost sm" onClick={() => setRows((rs) => rs.filter((r) => r.key !== row.key))}
                          disabled={rows.length === 1} aria-label={`Remove phase ${i + 1}`} title="Remove">×</button>
                </div>
              </div>
              {(blocks.length > 0 || votes.length > 0 || covs.length > 0) && (
                <details className="rbd-phase-needs">
                  <summary>{summary}</summary>
                  {blocks.length > 0 && (
                    <div className="rbd-phase-blocks">
                      <span className="rbd-phase-k">Each block in this phase</span>
                      <div className="rbd-phase-states">
                        {blocks.map((b) => {
                          const state = blockState(row, b.id);
                          return (
                            <label key={b.id} className={`rbd-phase-state is-${state}`}>
                              <span title={b.label}>{b.label}</span>
                              <select value={state} aria-label={`${b.label} in ${row.name || `phase ${i + 1}`}`}
                                      title={BLOCK_STATES.find((x) => x.id === state)?.title}
                                      onChange={(e) => update(row.key, withBlockState(row, b.id, e.target.value))}>
                                {BLOCK_STATES.map((x) => <option key={x.id} value={x.id}>{STATE_SHORT[x.id]}</option>)}
                              </select>
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  {covs.length > 0 && (
                    <div className="rbd-phase-blocks">
                      <span className="rbd-phase-k">Covariate values in this phase</span>
                      <div className="rbd-phase-states">
                        {covs.map((c) => {
                          const choice = c.kind === "choice" && (c.choices || []).length;
                          const v = row.values?.[c.name] ?? "";
                          const fallback = c.diagram != null && c.diagram !== "" ? c.diagram : c.blocks?.[0]?.default;
                          return (
                            <div key={c.name} className="rbd-phase-state rbd-phase-cov" title={`Feeds ${(c.blocks || []).map((b) => b.label).join(", ")}`}>
                              <span title={`${c.name}${c.unit ? ` (${c.unit})` : ""}`}>{c.name}{c.unit ? ` (${c.unit})` : ""}</span>
                              <PhaseCovValue cov={c} value={v} onChange={(x) => setValue(row, c.name, x)} unit={unit} duration={row.duration}
                                             constant={choice ? (
                                <select aria-label={`${c.name}${c.unit ? ` (${c.unit})` : ""}`} value={isSchedule(v) ? "" : v} onChange={(e) => setValue(row, c.name, e.target.value)}>
                                  <option value="">Not set</option>
                                  {c.choices.map((x) => <option key={x.code} value={x.code}>{x.label}</option>)}
                                </select>
                              ) : (
                                <input type="number" inputMode="decimal" step="any" aria-label={`${c.name}${c.unit ? ` (${c.unit})` : ""}`} value={isSchedule(v) ? "" : v}
                                       placeholder={fallback != null ? covValueText(fallback, "") : "needs a value"}
                                       onChange={(e) => setValue(row, c.name, e.target.value === "" ? "" : Number(e.target.value))} />
                              )} />
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  {votes.map((v) => (
                    <label key={v.id} className="rbd-phase-vote">
                      <span>{v.label}: working inputs needed</span>
                      <input type="number" inputMode="numeric" min="1" max={v.inputs || undefined} step="1" value={row.votes[v.id] ?? ""}
                             placeholder={String(v.n)}
                             onChange={(e) => update(row.key, { votes: { ...row.votes, [v.id]: e.target.value } })} />
                      <small>of {v.inputs}</small>
                    </label>
                  ))}
                </details>
              )}
            </li>
          );
        })}
      </ol>
      <button type="button" className="secondary sm" onClick={() => setRows((rs) => [...rs, newRow(rs.length)])}
              disabled={rows.length >= 50}>
        Add phase
      </button>
      {tried && errors.length > 0 && (
        <ul className="rbd-costs-errors">
          {errors.map((e) => <li key={e}>{e}</li>)}
        </ul>
      )}
    </Modal>
  );
}
