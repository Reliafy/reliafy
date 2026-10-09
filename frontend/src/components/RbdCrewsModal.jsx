import { useState } from "react";
import Modal from "./Modal.jsx";

// A repairable diagram's repair crews, maintenance groups and safety function
// (#156, #157). Stored on the graph as
//   repair_crews       = {crews: 2}               (blank: as many as are needed)
//   maintenance_groups = {name: {setup_cost, system_down}}
//   safety_function    = true, target_sil = 1..4  (report PFDavg and its SIL band)
// RePyability has one pool of crews per diagram, shared by every block
// (and each unit of a standby group); a block's crew priority orders the queue.
// ``section`` (#314): "crews" edits the crews and groups, "safety" the safety
// function, each from its own item in the builder's ⋯ menu; the other
// section's settings pass through unchanged. ``repairable``: a safety function
// is analysed as a repairable diagram, so turning it on switches the diagram.
const isBlank = (v) => v == null || String(v).trim() === "";
const SILS = ["", "1", "2", "3", "4"];

export default function RbdCrewsModal({ initial = {}, groupNames = [], onClose, onSubmit, section = "crews", repairable = true }) {
  const [crews, setCrews] = useState(initial.repair_crews?.crews ?? "");
  const [groups, setGroups] = useState(() => {
    const saved = initial.maintenance_groups || {};
    // Every group a block names, plus any options saved for a group.
    const names = [...new Set([...groupNames, ...Object.keys(saved)])];
    return names.map((name) => ({
      name,
      setup: saved[name]?.setup_cost ?? "",
      down: !!saved[name]?.system_down,
      used: groupNames.includes(name),
    }));
  });
  const [safety, setSafety] = useState(!!initial.safety_function);
  const [sil, setSil] = useState(initial.target_sil ? String(initial.target_sil) : "");

  const crewsOk = isBlank(crews) || (Number.isInteger(Number(crews)) && Number(crews) >= 1);
  const setupOk = groups.every((g) => isBlank(g.setup) || (Number.isFinite(Number(g.setup)) && Number(g.setup) >= 0));
  const valid = section === "safety" || (crewsOk && setupOk);

  const setGroup = (i, patch) => setGroups((gs) => gs.map((g, j) => (j === i ? { ...g, ...patch } : g)));

  const submit = () => {
    if (!valid) return;
    const options = {};
    for (const g of groups) {
      if (isBlank(g.setup) && !g.down) continue;
      options[g.name] = {
        ...(isBlank(g.setup) ? {} : { setup_cost: Number(g.setup) }),
        ...(g.down ? { system_down: true } : {}),
      };
    }
    const crewFields = {
      repair_crews: isBlank(crews) ? null : { crews: Number(crews) },
      maintenance_groups: Object.keys(options).length ? options : null,
    };
    const safetyFields = {
      safety_function: safety || null,
      target_sil: safety && sil ? Number(sil) : null,
    };
    onSubmit(section === "safety" ? { ...initial, ...safetyFields } : { ...initial, ...crewFields });
  };

  const footer = (
    <>
      <span className="hint">
        {section === "safety" ? "Proof tests: double-click a block." : "Block priorities and groups: double-click a block."}
      </span>
      <div className="row" style={{ margin: 0 }}>
        <button className="secondary" onClick={onClose}>Cancel</button>
        <button onClick={submit} disabled={!valid}>Set</button>
      </div>
    </>
  );

  return (
    <Modal title={section === "safety" ? "Safety function" : "Repair crews and groups"} onClose={onClose} footer={footer}>
      {section === "safety" ? (
        <>
          <label className="rbd-instant-repair" title="A low-demand safety instrumented function: report the average probability of failure on demand (PFDavg) and the SIL band it falls in.">
            <input type="checkbox" checked={safety} onChange={(e) => setSafety(e.target.checked)} />
            This diagram is a safety function <span className="muted">— report PFDavg and its SIL</span>
          </label>
          {safety && !repairable && (
            <p className="hint">A safety function is analysed as a repairable diagram: this switches the diagram to Repairable.</p>
          )}
          {safety && (
            <>
              <div className="param-fields">
                <label className="param-field rbd-cost-field">
                  <span>Target SIL</span>
                  <select value={sil} onChange={(e) => setSil(e.target.value)} aria-label="Target SIL">
                    {SILS.map((s) => <option key={s} value={s}>{s ? `SIL ${s}` : "None"}</option>)}
                  </select>
                </label>
              </div>
              <p className="hint">
                PFDavg is the long-run unavailability over the proof-test cycle. Stagger redundant channels' tests
                (first test at) and set each test's coverage on the blocks; select 2+ identical channels to add a
                common-cause group (β), which enters the PFDavg.
              </p>
        </>
      )}
        </>
      ) : (
        <>
          <div className="rbd-costs-h">Repair crews</div>
          <p className="muted-line" style={{ marginTop: 0 }}>
            How many repairs can run at once. With fewer crews than repair jobs, a failed block waits — down —
            until a crew is free (highest priority first, then first come). Exponential lives and repairs give
            exact long-run values (a Markov chain of the repair queue); anything else is simulated.
          </p>
          <div className="param-fields">
            <label className="param-field rbd-cost-field" title="Every block's repairs (and each failed unit of a standby group) share these crews. Blank: as many as are needed, so no repair ever waits.">
              <span>Crews</span>
              <input type="number" min="1" step="1" value={crews} placeholder="unlimited" aria-label="Repair crews"
                     onChange={(e) => setCrews(e.target.value)} />
              <small>shared by every block · blank = unlimited</small>
            </label>
          </div>
          <div className="rbd-costs-h">Maintenance groups</div>
          {groups.length === 0 ? (
            <p className="hint">
              No groups yet. Give blocks a maintenance group (double-click a block → Maintenance) to share a
              set-up cost — mobilisation, scaffolding, a shutdown — and renew members early when the group stops.
            </p>
          ) : (
            <table className="calc-table rbd-groups-table">
              <thead>
                <tr><th>Group</th><th>Set-up cost per stop</th><th title="Every outage of the whole system is also a stop of this group">Stops with the system</th></tr>
              </thead>
              <tbody>
                {groups.map((g, i) => (
                  <tr key={g.name}>
                    <td>{g.name}{!g.used && <span className="muted"> (no blocks)</span>}</td>
                    <td>
                      <input type="number" min="0" step="any" value={g.setup} placeholder="—"
                             aria-label={`Set-up cost of ${g.name}`} onChange={(e) => setGroup(i, { setup: e.target.value })} />
                    </td>
                    <td>
                      <input type="checkbox" checked={g.down} aria-label={`${g.name} stops with the system`}
                             onChange={(e) => setGroup(i, { down: e.target.checked })} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
      {!valid && (
        <ul className="rbd-costs-errors">
          {!crewsOk && <li>The number of crews must be a whole number, 1 or more (blank for unlimited).</li>}
          {!setupOk && <li>A set-up cost must be a non-negative number (charged per stop, in your currency).</li>}
        </ul>
      )}
    </Modal>
  );
}
