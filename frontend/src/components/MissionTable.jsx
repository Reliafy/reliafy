import { useCallback, useEffect, useState } from "react";
import { listPositionMissions } from "../api.js";
import Chip from "./ui/Chip.jsx";
import { completesText, lengthText, phasesText } from "../explorerMissions.js";

// The Explorer's Missions tab is the tree with each position's missions in it
// (explorerMissions.js), like the Modelling tab: the read of every position's RBD missions, each
// mission row's cells and its phone line. A mission opens in the table area (MissionPane.jsx).

export { MISSION_COLUMNS, MISSION_TREE_HEAD } from "../explorerMissions.js";

// Every position's RBDs and their missions, read when the tab is on (and again on `load`).
export function useTreeMissions({ on }) {
  const [state, setState] = useState({ links: null, error: null });
  const load = useCallback(() => listPositionMissions()
    .then((d) => setState({ links: d.links || [], error: null }))
    .catch((e) => setState((s) => ({ links: s.links, error: e.message }))), []);
  useEffect(() => { if (on) load(); }, [on, load]);
  return { links: state.links, error: state.error, load };
}

// One cell of a mission row (r.ref: {mission, rbd}).
export function MissionCell({ r, col }) {
  const m = r.ref.mission;
  switch (col.id) {
    case "phases":
      return <span className="ml-src" title={phasesText(m)}>{phasesText(m)}</span>;
    case "duration":
      return m.phases ? <span className="ml-num">{lengthText(m.duration, m.unit)}</span> : <span className="rw-blank">—</span>;
    case "reliability": {
      const text = completesText(m);
      if (!m.result) return <span className="rw-blank" title="Open it and Calculate">—</span>;
      return m.result.reliability != null
        ? <span className="ml-num" title="The chance the mission completes">{text}</span>
        : <Chip tone="warning" title={text}>Needs values</Chip>;
    }
    case "rbd":
      return <span className="ml-src" title={r.ref.rbd.name}>{r.ref.rbd.name}</span>;
    default:
      return null;
  }
}

// A row's second line on a phone.
export function missionPhoneRow(r, rollup) {
  if (r.type !== "mission") return { line: rollup || "", status: null };
  const m = r.ref.mission;
  const done = m.result?.reliability != null;
  return {
    line: [phasesText(m), m.phases ? lengthText(m.duration, m.unit) : null].filter(Boolean).join(" · "),
    status: done ? <Chip tone="neutral" title="The chance the mission completes">{completesText(m)}</Chip>
      : m.result ? <Chip tone="warning">Needs values</Chip> : null,
  };
}
