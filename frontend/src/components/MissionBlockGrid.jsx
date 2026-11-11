import { BLOCK_STATES, blockState, withBlockState } from "../explorerMissions.js";

// Each block's state in each phase of a mission (MissionPane.jsx): a grid with a row per block of
// the mission's RBD and a column per phase, each cell Working (the default), Standby or Not
// needed, changed in place. Wide missions scroll inside the grid's own box, never the page.
//
//   blocks: [{id, label}]   phases: the pane's editable phases ({key, name, standby, not_needed})
//   readOnly                onChange(phaseKey, {standby, not_needed})

const SHORT = { working: "Working", standby: "Standby", off: "Not needed" };

export default function MissionBlockGrid({ blocks = [], phases = [], readOnly = false, onChange }) {
  if (!blocks.length) return null;
  return (
    <section className="mission-grid" aria-labelledby="mission-grid-h">
      <h3 className="mission-k" id="mission-grid-h">Blocks in each phase</h3>
      {phases.length === 0 ? (
        <p className="rim-tquiet">Add a phase to set which blocks run, stand by or aren't needed in it.</p>
      ) : (
        <div className="maint-scroll mission-grid-scroll">
          <table className="mission-grid-table">
            <thead>
              <tr>
                <th scope="col">Block</th>
                {phases.map((p, i) => (
                  <th key={p.key} scope="col" title={p.name || `Phase ${i + 1}`}>
                    <span className="mission-grid-n">{i + 1}</span> {p.name || <span className="rw-blank">no name</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {blocks.map((b) => (
                <tr key={b.id}>
                  <th scope="row">{b.label}</th>
                  {phases.map((p, i) => {
                    const state = blockState(p, b.id);
                    return (
                      <td key={p.key} className={`is-${state}`}>
                        <select value={state} disabled={readOnly}
                                aria-label={`${b.label} in ${p.name || `phase ${i + 1}`}`}
                                title={BLOCK_STATES.find((s) => s.id === state)?.title}
                                onChange={(e) => onChange?.(p.key, withBlockState(p, b.id, e.target.value))}>
                          {BLOCK_STATES.map((s) => <option key={s.id} value={s.id}>{SHORT[s.id]}</option>)}
                        </select>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <dl className="mission-grid-key">
        {BLOCK_STATES.map((s) => (
          <div key={s.id}><dt>{s.label}</dt><dd>{s.title}.</dd></div>
        ))}
      </dl>
    </section>
  );
}
