import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import RcmWorksheet from "./RcmWorksheet.jsx";
import DecisionModal from "./DecisionModal.jsx";
import { RollupBadges } from "./RcmStatusBadge.jsx";
import { useAskText } from "./ConfirmProvider.jsx";
import {
  addFailureMode, addFunctionalFailure, addPositionFunction, assignFailureMode, decideFailureMode, getPositionRcm,
  getRcmOptions, removeFunctionalFailure, removePositionFunction, retireFailureMode, updateFailureMode,
  updateFunctionalFailure, updatePositionFunction,
} from "../api.js";
import { COLUMN, buildPositionRcmDisplay, decisionBody } from "../rcmWorksheet.js";

// A position's RCM tab in the Explorer: the RCM worksheet's outline grid over
// what the asset tree holds (functions › functional failures › failure modes,
// each mode's decision, task and evidence check) for the position picked in the
// tree. The tree beside it is the index: pick a position there and the table
// follows; "Include positions inside" adds theirs, each function naming its
// position in a Position column. Every edit is written at once as the graph's
// own events; nothing is a copy, so it can't drift from the assets. It fits the
// panel's height: the grid scrolls in its card.

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;

export default function PositionRcm({ position, inside, onInside, phone, readOnly, onChanged }) {
  const scope = inside ? "below" : "this";
  const askText = useAskText();
  const [sheet, setSheet] = useState(null);
  const [error, setError] = useState(null);
  const [options, setOptions] = useState(null);
  const [deciding, setDeciding] = useState(null); // a mode row

  // Only the latest read counts: walking down the tree fast mustn't show an
  // earlier position's RCM under a later one.
  const latest = useRef(0);
  const load = useCallback(() => {
    const n = ++latest.current;
    return getPositionRcm(position.id, scope)
      .then((s) => { if (n === latest.current) { setSheet(s); setError(null); } return s; })
      .catch((e) => { if (n === latest.current) setError({ text: e.message, notAllowed: e.status === 404 || e.status === 403 }); });
  }, [position.id, scope]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => { getRcmOptions().then(setOptions).catch(() => {}); }, []);

  const display = useMemo(() => (sheet ? buildPositionRcmDisplay(sheet) : null), [sheet]);

  // Each change is written, then the sheet read again (the evidence checks and
  // roll-ups come back with it); the tree's "not analysed" marks follow.
  const after = useCallback(async (p) => {
    const out = await p;
    await load();
    onChanged?.();
    return out;
  }, [load, onChanged]);

  const ops = useMemo(() => ({
    set(r, col, value) {
      const id = r.ref.id;
      if (col === "name") {
        if (r.type === "fn") return after(updatePositionFunction(id, { text: value }));
        if (r.type === "fail") return after(updateFunctionalFailure(id, { text: value }));
        return after(updateFailureMode(id, { text: value }));
      }
      if (col === "standard") return after(updatePositionFunction(id, { standard: value }));
      if (col === "effects" || col === "notes") return after(updateFailureMode(id, { [col]: value }));
      if (col === "consequence") return after(decideFailureMode(id, { consequence: value || null }));
      const c = COLUMN[col];
      return after(decideFailureMode(id, { decision: decisionBody(r.ref.decision, { [c.field]: value }) }));
    },
    async add(r) {
      const kind = !r || r.type === "pos" ? "fn" : r.type === "fn" ? "fail" : "mode";
      const words = {
        fn: { title: "Add a function", label: "What must this position do?", confirmLabel: "Add function" },
        fail: { title: "Add a functional failure", label: "How does it fail to do it?", confirmLabel: "Add functional failure" },
        mode: { title: "Add a failure mode", label: "What causes it?", confirmLabel: "Add failure mode" },
      }[kind];
      const text = (await askText(words))?.trim();
      if (!text) return null;
      const positionId = r ? r.ref.position_id : position.id;
      let made;
      if (kind === "fn") made = await addPositionFunction(positionId, { text });
      else if (kind === "fail") made = await addFunctionalFailure(r.ref.id, { text });
      else made = await addFailureMode(positionId, { text, functional_failure_id: r.type === "fail" ? r.ref.id : null });
      await after(Promise.resolve());
      return made.id;
    },
    removeText(r) {
      const name = `“${(r.ref.text || "").slice(0, 80)}”`;
      if (r.type === "fn") {
        return `${name} and its ${plural(r.kids.length, "functional failure")} go. `
          + (r.sum.modes ? `Its ${plural(r.sum.modes, "failure mode")} stay on the position, not under a functional failure, with their tasks.` : "");
      }
      if (r.type === "fail") {
        return `${name} goes. ${r.sum.modes ? `Its ${plural(r.sum.modes, "failure mode")} stay on the position, not under a functional failure, with their tasks.` : ""}`;
      }
      const task = r.ref.decision?.task_id ? ` Its task “${(r.ref.decision.task || "").slice(0, 60)}” is retired too.` : "";
      return `${name} goes from this position's RCM.${task} Failures already recorded against it keep it in their history.`;
    },
    remove(r) {
      const id = r.ref.id;
      if (r.type === "fn") return after(removePositionFunction(id));
      if (r.type === "fail") return after(removeFunctionalFailure(id));
      return after(retireFailureMode(id));
    },
    assign(r, ffId) {
      return after(assignFailureMode(r.ref.id, ffId)).catch((e) => setError({ text: e.message }));
    },
  }), [after, askText, position.id]);

  const saveDecision = async ({ consequence, decision }) => {
    const r = deciding;
    setDeciding(null);
    try {
      await after(decideFailureMode(r.ref.id, { consequence: consequence || null, decision }));
    } catch (e) {
      setError({ text: e.message });
    }
  };

  // The table's own line above it: the positions inside, and its evidence
  // checks. Outside the grid, so the switch stays put while the table reloads.
  const bar = (
    <div className="prcm-bar">
      <label className="prcm-inside" title="Add the functions of every position inside this one, each naming its position">
        <input type="checkbox" checked={inside} onChange={(e) => onInside(e.target.checked)} />
        Include positions inside
      </label>
      {sheet?.rollup && <RollupBadges rollup={sheet.rollup} />}
    </div>
  );

  let body;
  if (error && !sheet) {
    body = error.notAllowed ? (
      <div className="card empty"><p>This position's RCM isn't available to you.</p></div>
    ) : (
      <div className="card error td-error">
        <p>The RCM didn't load: {error.text} Your data is safe; check your connection and try again.</p>
        <button type="button" className="secondary" onClick={load}>Try again</button>
      </div>
    );
  } else if (!sheet || sheet.position.id !== position.id) {
    // (Turning "Include positions inside" on or off keeps the table, and the
    // switch, in place until the new one is in.)
    body = <div className="card empty prcm-loading">Loading the RCM…</div>;
  } else {
    body = (
      <div className="card rw-card prcm-card">
        <RcmWorksheet
          key={`${sheet.position.id}:${sheet.scope}`}
          studyId={`position:${sheet.position.id}:${sheet.scope}`}
          display={display}
          ops={ops}
          readOnly={readOnly}
          phone={phone}
          onDecision={(r) => setDeciding(r)}
          positionColumn={inside && sheet.positions.length > 1}
          notice={sheet.truncated ? (
            <p className="rw-legend">Showing the first {plural(sheet.positions.length, "position")} of {sheet.total_positions.toLocaleString("en-AU")} inside. Pick a position lower down in the tree.</p>
          ) : null}
        />
      </div>
    );
  }

  return (
    <div className="prcm">
      {bar}
      {error && sheet && <p className="prcm-err" role="alert">{error.text}</p>}
      {body}
      {deciding && options && (
        <DecisionModal options={options} mode={deciding.ref} onSave={saveDecision} onClose={() => setDeciding(null)} />
      )}
    </div>
  );
}
