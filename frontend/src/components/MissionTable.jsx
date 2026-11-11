import { useCallback, useEffect, useRef, useState } from "react";
import { listPositionMissions } from "../api.js";
import Chip from "./ui/Chip.jsx";
import { completesText, isPhaseRow, latestOnly, lengthText, phaseLengthText, phaseOfText, phasesText, placeholderTitle } from "../explorerMissions.js";

// The Explorer's Missions tab is the tree with each position's missions in it
// (explorerMissions.js), like the Modelling tab: the read of every position's RBD missions, each
// mission row's cells and its phone line. A mission opens in the table area (MissionPane.jsx).

export { MISSION_COLUMNS, MISSION_TREE_HEAD } from "../explorerMissions.js";

// Every position's RBDs and their missions, read when the tab is on (and again on `load`). Two
// reads can be out at once (a mission saved, then its result worked out): the one asked for last
// is the one shown, whichever answers first.
export function useTreeMissions({ on }) {
  const [state, setState] = useState({ links: null, hasModel: [], error: null });
  const asked = useRef(null);
  if (!asked.current) asked.current = latestOnly();
  const load = useCallback(() => {
    const latest = asked.current();
    return listPositionMissions()
      .then((d) => latest() && setState({ links: d.links || [], hasModel: d.has_model || [], error: null }))
      .catch((e) => latest() && setState((s) => ({ ...s, error: e.message })));
  }, []);
  useEffect(() => { if (on) load(); }, [on, load]);
  return { links: state.links, hasModel: state.hasModel, error: state.error, load };
}

// One cell of a mission row (r.ref: {mission, rbd}); a phase row (r.ref.phase: {index, of,
// duration}) has its place in the mission under Phases and its own length under Length, in the
// mission's unit (the mission's row has their total). A phase's own chance is in the mission, opened.
export function MissionCell({ r, col }) {
  if (isPhaseRow(r)) {
    if (col.id === "phases") return <span className="ml-src">{phaseOfText(r.ref.phase)}</span>;
    if (col.id !== "duration") return null;
    const text = phaseLengthText(r.ref.phase, r.ref.mission.unit);
    return text ? <span className="ml-num">{text}</span> : <span className="rw-blank">—</span>;
  }
  const m = r.ref.mission;
  switch (col.id) {
    case "phases":
      return <span className="ml-src" title={phasesText(m)}>{phasesText(m)}</span>;
    case "duration":
      return m.phases ? <span className="ml-num">{lengthText(m.duration, m.unit)}</span> : <span className="rw-blank">—</span>;
    case "reliability": {
      const text = completesText(m);
      if (!m.result) return <span className="rw-blank" title="Open it and Calculate">—</span>;
      if (m.result.reliability == null) return <Chip tone="warning" title={text}>Needs values</Chip>;
      // Worked out on placeholders: the figure is shown as what it is, never alone.
      if (m.result.placeholders?.length) {
        return <Chip tone="warning" title={placeholderTitle(m.result)}>{text} · placeholders</Chip>;
      }
      return <span className="ml-num" title="The chance the mission completes">{text}</span>;
    }
    case "rbd":
      return <span className="ml-src" title={r.ref.rbd.name}>{r.ref.rbd.name}</span>;
    default:
      return null;
  }
}

// A row's second line on a phone.
export function missionPhoneRow(r, rollup) {
  if (isPhaseRow(r)) return { line: [phaseOfText(r.ref.phase), phaseLengthText(r.ref.phase, r.ref.mission.unit)].filter(Boolean).join(" · "), status: null };
  if (r.type !== "mission") return { line: rollup || "", status: null };
  const m = r.ref.mission;
  const done = m.result?.reliability != null;
  return {
    line: [phasesText(m), m.phases ? lengthText(m.duration, m.unit) : null].filter(Boolean).join(" · "),
    status: done && m.result.placeholders?.length ? <Chip tone="warning" title={placeholderTitle(m.result)}>{completesText(m)} · placeholders</Chip>
      : done ? <Chip tone="neutral" title="The chance the mission completes">{completesText(m)}</Chip>
      : m.result ? <Chip tone="warning">Needs values</Chip> : null,
  };
}
