import { useMemo, useState } from "react";
import Modal from "./Modal.jsx";
import { cleanPhases, phaseBlocks, voteNodes } from "../rbdMission.js";
import "./RbdMission.css";

// The phased-mission editor (#160), from the builder's ⋯ menu: the mission's
// phases in order, each with a name and a duration, and — folded under each
// phase — the blocks it doesn't need and any vote node that needs a different
// number of its inputs in it. Stored as graph.phases; Save with no phases
// clears it.
//
//   initial   the diagram's phases (or none)
//   nodes, edges, unit   the live diagram, for the block and vote lists
//   onSubmit(phases | null), onClose

let rowKey = 0;
const newRow = (i) => ({ key: ++rowKey, name: `Phase ${i + 1}`, duration: "", not_needed: [], votes: {} });
const fromStored = (p) => ({
  key: ++rowKey,
  name: p.name || "",
  duration: p.duration ?? "",
  not_needed: [...(p.not_needed || [])],
  votes: { ...(p.votes || {}) },
});

export default function RbdPhasesModal({ initial, nodes, edges, unit, onClose, onSubmit }) {
  const [rows, setRows] = useState(() => (initial?.length ? initial.map(fromStored) : [newRow(0)]));
  const [tried, setTried] = useState(false);
  const blocks = useMemo(() => phaseBlocks(nodes), [nodes]);
  const votes = useMemo(() => voteNodes(nodes, edges), [nodes, edges]);
  const labelOf = useMemo(() => new Map(blocks.map((b) => [b.id, b.label])), [blocks]);
  const { phases, errors } = cleanPhases(rows, nodes);
  const u = unit ? ` (${unit})` : "";

  const update = (key, patch) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const toggleBlock = (row, id) =>
    update(row.key, {
      not_needed: row.not_needed.includes(id) ? row.not_needed.filter((b) => b !== id) : [...row.not_needed, id],
    });
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
          const changed = votes.filter((v) => String(row.votes[v.id] ?? "").trim() !== "");
          const summary = [
            skipped.length
              ? `Doesn't need ${skipped.length === 1 ? labelOf.get(skipped[0]) : `${skipped.length} blocks`}`
              : "Needs every block",
            ...changed.map((v) => `${v.label}: ${row.votes[v.id]} of ${v.inputs}`),
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
                  <input type="number" min="0" step="any" value={row.duration} placeholder="—"
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
              {(blocks.length > 0 || votes.length > 0) && (
                <details className="rbd-phase-needs">
                  <summary>{summary}</summary>
                  {blocks.length > 0 && (
                    <div className="rbd-phase-blocks">
                      <span className="rbd-phase-k">Blocks needed in this phase</span>
                      <div className="chip-row">
                        {blocks.map((b) => {
                          const needed = !row.not_needed.includes(b.id);
                          return (
                            <button key={b.id} type="button" aria-pressed={needed}
                                    className={"chip chip-btn rbd-need " + (needed ? "chip-accent" : "chip-neutral is-off")}
                                    onClick={() => toggleBlock(row, b.id)}
                                    title={needed ? "Needed — click if this phase doesn't need it" : "Not needed in this phase — click to need it"}>
                              {b.label}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  {votes.map((v) => (
                    <label key={v.id} className="rbd-phase-vote">
                      <span>{v.label}: working inputs needed</span>
                      <input type="number" min="1" max={v.inputs || undefined} step="1" value={row.votes[v.id] ?? ""}
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
