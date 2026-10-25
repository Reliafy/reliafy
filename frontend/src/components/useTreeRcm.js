import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  addFailureMode, addFunctionalFailure, addPositionFunction, assignFailureMode, decideFailureMode, getWorkspaceRcm,
  linkFunctionalFailureCause, removeFunctionalFailure, removePositionFunction, unlinkFunctionalFailureCause, retireFailureMode, updateFailureMode, updateFunctionalFailure,
  updatePositionFunction,
} from "../api.js";
import { COLUMN, FUNCTION_MAX, FUNCTION_NUDGE, decisionBody } from "../rcmWorksheet.js";

// The RCM in the Explorer's tree (the RCM tab): every position's functions,
// functional failures and failure modes, read once when the tab opens and
// again after each change, and the changes themselves, each written at once as
// the graph's own events (no Undo yet). After a change the tree is read again
// too (its "not analysed" marks follow). With `prefetch` it's read once a
// moment early (the Summary tab), so opening the tab doesn't wait for it.

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;

const WORDS = {
  // A function's text is kept short where it's typed (a counter, and a nudge
  // to put the standard in its own field).
  fn: { title: "Add a function", label: "What must this position do?", confirmLabel: "Add function",
    limit: { max: FUNCTION_MAX, nudge: FUNCTION_NUDGE } },
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
    // A function's description, in a dialog with its counter (the row menu's
    // Edit description): the text saved before, however long, to edit; saved
    // from the dialog, which stays open until it's done (or says why not).
    // Resolves true once saved, null when cancelled or unchanged.
    async editFunction(r) {
      const before = r.ref.text || "";
      const out = await askText({
        title: "Edit the function", label: "What must this position do?", confirmLabel: "Save",
        value: before, pendingLabel: "Saving…",
        limit: { max: FUNCTION_MAX, nudge: FUNCTION_NUDGE, before },
        run: async (text) => {
          if (text === before.trim()) return "same";
          await after(updatePositionFunction(r.ref.id, { text }));
          return "saved";
        },
      });
      return out === "saved" ? true : null;
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
    // A refusal goes to the caller (it says so beside the panel).
    assign(r, ffId) {
      return after(assignFailureMode(r.ref.id, ffId));
    },
    // A functional failure results from a lower one (the same link from either
    // end), or no longer does. The tree and the RCM are read again after.
    link(effectId, causeId) {
      return after(linkFunctionalFailureCause(effectId, causeId));
    },
    unlink(effectId, causeId) {
      return after(unlinkFunctionalFailureCause(effectId, causeId));
    },
    // Several links in one go, written in order, the RCM read again once at the
    // end (even when one is refused, so what was linked shows). Each item is
    // {effect, cause}, or, for a failure not written yet, {id, make, effect}
    // or {id, make, cause}: make is {position_id, function_id | function_text,
    // text}, and the failure is written (its function too) and fills the end
    // left out. `made` ({id: failure id}) remembers what was written, so trying
    // again after a refusal writes nothing twice. Returns how many were linked.
    async linkMany(items, made = {}) {
      let n = 0;
      try {
        for (const it of items) {
          let { effect, cause } = it;
          if (it.make) {
            if (!made[it.id]) {
              // A new function is written once, however many new failures go under it.
              const fnKey = `fn:${it.make.position_id}:${it.make.function_text}`;
              if (!it.make.function_id && !made[fnKey]) {
                made[fnKey] = (await addPositionFunction(it.make.position_id, { text: it.make.function_text })).id;
              }
              const fnId = it.make.function_id || made[fnKey];
              made[it.id] = (await addFunctionalFailure(fnId, { text: it.make.text })).id;
            }
            effect = effect || made[it.id];
            cause = cause || made[it.id];
          }
          await linkFunctionalFailureCause(effect, cause);
          n += 1;
        }
      } finally {
        await after(Promise.resolve());
      }
      return n;
    },
    decide(r, { consequence, decision }) {
      return after(decideFailureMode(r.ref.id, { consequence: consequence || null, decision }));
    },
  }), [after, askText]);

  return { rcm, error, setError, load, ops };
}
