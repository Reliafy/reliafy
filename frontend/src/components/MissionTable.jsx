import { useCallback, useEffect, useRef, useState } from "react";
import { listPositionMissions } from "../api.js";
import Chip from "./ui/Chip.jsx";
import {
  completesText, covStatus, feedsList, isCovRow, isPhaseRow, isRuleRow, latestOnly, lengthText, pct, phaseLengthText, phaseOfText, phasesText,
  placeholderTitle, placeholderTone, ruleText,
} from "../explorerMissions.js";

// The Explorer's Models tab has each position's missions in its tree, as rows under the model each
// is flown on (explorerMissions.js nestMissions): the read of every position's RBD missions, each
// mission row's cells in the Models tab's columns and its phone line. A mission opens in the table
// area (MissionPane.jsx).

// Every position's RBDs and their missions, read when the tab is on (and again on `load`). Two
// reads can be out at once (a mission saved, then its result worked out): the one asked for last
// is the one shown, whichever answers first.
export function useTreeMissions({ on, within = null }) {
  const [state, setState] = useState({ links: null, hasModel: [], otherModel: [], error: null });
  const asked = useRef(null);
  if (!asked.current) asked.current = latestOnly();
  const load = useCallback(() => {
    const latest = asked.current();
    return listPositionMissions(null, { within })
      .then((d) => latest() && setState({ links: d.links || [], hasModel: d.has_model || [], otherModel: d.other_model || [], error: null }))
      .catch((e) => latest() && setState((s) => ({ ...s, error: e.message })));
  }, [within]);
  useEffect(() => { if (on) load(); }, [on, load]);
  return { links: state.links, hasModel: state.hasModel, otherModel: state.otherModel, error: state.error, load };
}

// A position's roll-up on the Missions tab, with "Add a mission" a real button wherever one can be
// added (it was plain words, the action only in the row's menu). `text`: rollupText's words.
export function MissionRollup({ text, onAdd = null }) {
  const tail = " · Add a mission";
  if (!onAdd || !String(text || "").endsWith(tail)) return text || "";
  // One inline span, so a flex parent (the heading's roll-up) keeps the space before the button.
  return (
    <span>
      {text.slice(0, -tail.length)}{" · "}
      <button type="button" className="link mt-add-mission" onClick={(e) => { e.stopPropagation(); onAdd(); }}>Add a mission</button>
    </span>
  );
}

// One cell of a mission row (r.ref: {mission, rbd}); a phase row (r.ref.phase: {index, of,
// duration}) has its place in the mission under Phases and its own length under Length, in the
// mission's unit (the mission's row has their total). A phase's own chance is in the mission, opened.
export function MissionCell({ r, col }) {
  // Under a phase: a covariate's value in it (flagged when unset), what it feeds; a rule's state.
  if (isCovRow(r)) {
    const st = covStatus(r.ref.cov);
    if (col.id === "phases") {
      if (st.flag === "needs") return <Chip tone="warning" title={st.title}>Needs a value</Chip>;
      if (st.flag === "unset") return <Chip tone="neutral" title={st.title}>{st.text}</Chip>;
      return <span className="ml-num" title={st.title}>{st.text}</span>;
    }
    if (col.id === "rbd") return <span className="ml-src" title={feedsList(r.ref.cov)}>{feedsList(r.ref.cov)}</span>;
    return null;
  }
  if (isRuleRow(r)) {
    if (col.id === "phases") return <span className="ml-src">{ruleText(r.ref.rule)}</span>;
    return null;
  }
  if (isPhaseRow(r)) {
    if (col.id === "phases") return <span className="ml-src">{phaseOfText(r.ref.phase)}</span>;
    if (col.id === "reliability") {
      const pr = r.ref.result;
      if (pr?.waiting) return <Chip tone="warning">Needs values</Chip>;
      return pr?.completes != null ? <span className="ml-num" title="The chance of getting through this phase, once started">{pct(pr.completes)}</span> : null;
    }
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
      if (placeholderTone(m.result)) {
        return <Chip tone={placeholderTone(m.result)} title={placeholderTitle(m.result)}>{text} · placeholders</Chip>;
      }
      return <span className="ml-num" title="The chance the mission completes">{text}</span>;
    }
    case "rbd":
      return <span className="ml-src" title={r.ref.rbd.name}>{r.ref.rbd.name}</span>;
    default:
      return null;
  }
}

// What a mission row is, in the Kind column: "Mission", "Phase", "Covariate", "Node status".
export function missionKindText(r) {
  if (isCovRow(r)) return "Covariate";
  if (isRuleRow(r)) return "Node status";
  if (isPhaseRow(r)) return "Phase";
  return "Mission";
}

// One cell of a mission, phase, covariate or node status row in the Models tab's columns (one
// tree-table, Derryn 22 Nov 2026): Kind says which; Source what it's made of (a mission's phases, a
// phase's place, a covariate's value, a block's state); Headline its numbers (the chance it
// completes, then its length); Used by the RBD it's flown on (a covariate: the blocks it feeds).
// The life-model columns (Mean life, B10, Confidence) have nothing for a mission.
const AS_MISSION = { source: "phases", used: "rbd" };
export function MissionModelCell({ r, col }) {
  if (col.id === "kind") return <span className="ml-kind">{missionKindText(r)}</span>;
  if (col.id === "numbers") {
    if (isCovRow(r) || isRuleRow(r)) return null;
    // Not worked out yet (a mission never calculated, a phase with no result): its length alone.
    const worked = isPhaseRow(r) ? r.ref.result?.waiting || r.ref.result?.completes != null : !!r.ref.mission.result;
    const chance = worked ? MissionCell({ r, col: { id: "reliability" } }) : null;
    const length = isPhaseRow(r) ? phaseLengthText(r.ref.phase, r.ref.mission.unit)
      : r.ref.mission.phases ? lengthText(r.ref.mission.duration, r.ref.mission.unit) : "";
    if (!chance && !length) return <span className="rw-blank" title="Open it and Calculate">—</span>;
    return <span className="ml-num">{chance}{chance && length ? " · " : null}{length}</span>;
  }
  return AS_MISSION[col.id] ? <MissionCell r={r} col={{ id: AS_MISSION[col.id] }} /> : null;
}

// A row's second line on a phone.
export function missionPhoneRow(r, rollup) {
  if (isCovRow(r)) {
    const st = covStatus(r.ref.cov);
    return { line: st.flag ? "" : st.text, status: st.flag === "needs" ? <Chip tone="warning">Needs a value</Chip> : st.flag ? <Chip tone="neutral">Not set</Chip> : null };
  }
  if (isRuleRow(r)) return { line: ruleText(r.ref.rule), status: null };
  if (isPhaseRow(r)) {
    const pr = r.ref.result;
    return {
      line: [phaseOfText(r.ref.phase), phaseLengthText(r.ref.phase, r.ref.mission.unit)].filter(Boolean).join(" · "),
      status: pr?.waiting ? <Chip tone="warning">Needs values</Chip>
        : pr?.completes != null ? <Chip tone="neutral" title="The chance of getting through this phase, once started">{pct(pr.completes)}</Chip> : null,
    };
  }
  if (r.type !== "mission") return { line: rollup || "", status: null };
  const m = r.ref.mission;
  const done = m.result?.reliability != null;
  return {
    line: [phasesText(m), m.phases ? lengthText(m.duration, m.unit) : null].filter(Boolean).join(" · "),
    status: done && placeholderTone(m.result) ? <Chip tone={placeholderTone(m.result)} title={placeholderTitle(m.result)}>{completesText(m)} · placeholders</Chip>
      : done ? <Chip tone="neutral" title="The chance the mission completes">{completesText(m)}</Chip>
      : m.result ? <Chip tone="warning">Needs values</Chip> : null,
  };
}
