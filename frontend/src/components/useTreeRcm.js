import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  addFailureMode, addFunctionalFailure, addPositionFunction, assignFailureMode, decideFailureMode, getWorkspaceRcm,
  removeFunctionalFailure, removePositionFunction, retireFailureMode, updateFailureMode, updateFunctionalFailure,
  updatePositionFunction,
} from "../api.js";
import { COLUMN, decisionBody } from "../rcmWorksheet.js";

// The RCM in the Explorer's tree (the RCM tab): every position's functions,
// functional failures and failure modes, read once when the tab opens and
// again after each change, and the changes themselves, each written at once as
// the graph's own events (no Undo yet). After a change the tree is read again
// too (its "not analysed" marks follow). With `prefetch` it's read once a
// moment early (the Summary tab), so opening the tab doesn't wait for it.

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;

const WORDS = {
  fn: { title: "Add a function", label: "What must this position do?", confirmLabel: "Add function" },
  fail: { title: "Add a functional failure", label: "How does it fail to do it?", confirmLabel: "Add functional failure" },
  mode: { title: "Add a failure mode", label: "What causes it?", confirmLabel: "Add failure mode" },
};

export default function useTreeRcm({ on, prefetch = false, onTreeChanged, askText }) {
  const [rcm, setRcm] = useState(null);
  const [error, setError] = useState(null);
  const latest = useRef(0);
  const load = useCallback(() => {
    const n = ++latest.current;
    return getWorkspaceRcm()
      .then((d) => { if (n === latest.current) { setRcm(d); setError(null); } return d; })
      .catch((e) => { if (n === latest.current) setError(e.message); });
  }, []);
  useEffect(() => {
    if (on) load();
  }, [on, load]);
  const fetched = useRef(false);
  useEffect(() => {
    if (on) fetched.current = true;
    if (!prefetch || on || fetched.current) return undefined;
    const t = setTimeout(() => {
      fetched.current = true;
      load();
    }, 600);
    return () => clearTimeout(t);
  }, [prefetch, on, load]);

  const after = useCallback(async (p) => {
    const out = await p;
    await load();
    onTreeChanged?.();
    return out;
  }, [load, onTreeChanged]);

  const ops = useMemo(() => ({
    // One cell changed (the value checked as the server checks it).
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
      return after(decideFailureMode(id, { decision: decisionBody(r.ref.decision, { [COLUMN[col].field]: value }) }));
    },
    // Something new inside a row: a function on a position, a functional failure
    // on a function, a failure mode on a functional failure (or under none). Asks
    // for its words and adds it from the dialog, which stays open (its button
    // saying "Adding…") until the RCM is read again, so a second click or Enter
    // adds nothing more, and a refusal shows there with the words kept.
    // Returns the new row's id (null when cancelled).
    async add(kind, { positionId, functionId = null, failureId = null }) {
      const id = await askText({
        ...WORDS[kind],
        pendingLabel: "Adding…",
        run: async (text) => {
          let made;
          if (kind === "fn") made = await addPositionFunction(positionId, { text });
          else if (kind === "fail") made = await addFunctionalFailure(functionId, { text });
          else made = await addFailureMode(positionId, { text, functional_failure_id: failureId });
          await after(Promise.resolve());
          return made.id;
        },
      });
      return id || null;
    },
    removeText(r) {
      const name = `“${(r.ref.text || "").slice(0, 80)}”`;
      const modes = r.rsum?.modes || 0;
      const stay = modes ? `Its ${plural(modes, "failure mode")} stay on the position, not under a functional failure, with their tasks.` : "";
      if (r.type === "fn") {
        const fails = r.kids.length;
        return `${name} and its ${plural(fails, "functional failure")} go. ${stay}`;
      }
      if (r.type === "fail") return `${name} goes. ${stay}`;
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
      return after(assignFailureMode(r.ref.id, ffId)).catch((e) => setError(e.message));
    },
    decide(r, { consequence, decision }) {
      return after(decideFailureMode(r.ref.id, { consequence: consequence || null, decision }));
    },
  }), [after, askText]);

  return { rcm, error, setError, load, ops };
}
