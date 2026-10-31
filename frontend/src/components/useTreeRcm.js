import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  addFailureMode, addFailureModeTask, applyRcm, addFunctionStandard, addFunctionalFailure, addPositionFunction, assignFailureMode,
  decideFailureMode, getFailureModeTasks, getPositionFunction, getWorkspaceRcm, linkFunctionalFailureCause,
  linkTaskFailureMode, removeFunctionStandard, removeFunctionalFailure, removeMaintenanceDocument, removePositionFunction,
  reorderFunctionStandards, retireFailureMode, retireMaintenanceTask, splitFunctionStandard, unlinkFunctionalFailureCause,
  unlinkTaskFailureMode, updateFailureMode, updateFunctionStandard, updateFunctionalFailure, updateMaintenanceTask,
  updatePositionFunction, uploadMaintenanceDocument,
} from "../api.js";
import { COLUMN, FUNCTION_MAX, FUNCTION_NUDGE, decisionBody, tasksOf } from "../rcmWorksheet.js";
import { itemWrites } from "../explorerRcm.js";

// The RCM in the Explorer's tree (the RCM tab): every position's functions,
// functional failures and failure modes, read once when the tab opens and
// again after each change, and the changes themselves, each written at once as
// the graph's own events (a move, by drag and drop or Move to…, is one batch
// that can be undone). After a change the tree is read again too (its "not
// analysed" marks follow). With `prefetch` it's read once a
// moment early (the Summary tab), so opening the tab doesn't wait for it.

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;

const WORDS = {
  // A function's text is kept short where it's typed (a counter, and a nudge
  // to put the standard in its own field).
  fn: { title: "Add a function", label: "What must this position do?", confirmLabel: "Add function",
    limit: { max: FUNCTION_MAX, nudge: FUNCTION_NUDGE } },
  std: { title: "Add a performance standard", label: "One parameter and one limit, e.g. pH 7.2-7.8", confirmLabel: "Add performance standard" },
  fail: { title: "Add a functional failure", label: "How does it fail to do it?", confirmLabel: "Add functional failure" },
  mode: { title: "Add a failure mode", label: "What causes it?", confirmLabel: "Add failure mode" },
};
// A functional failure added from a standard's row: it breaches that standard.
const WORDS_UNDER_STANDARD = { ...WORDS.fail, label: "How does it fail to meet this performance standard?" };

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
        // A standard's text; the one text's row (legacy) edits the function's text.
        if (r.type === "std") {
          return after(r.ref.legacy ? updatePositionFunction(r.ref.function_id, { standard: value })
            : updateFunctionStandard(r.ref.standard_id, { text: value }));
        }
        if (r.type === "fail") return after(updateFunctionalFailure(id, { text: value }));
        return after(updateFailureMode(id, { text: value }));
      }
      if (col === "standard") return after(updatePositionFunction(id, { standard: value }));
      if (col === "effects" || col === "notes") return after(updateFailureMode(id, { [col]: value }));
      if (col === "consequence") return after(decideFailureMode(id, { consequence: value || null }));
      return after(decideFailureMode(id, { decision: decisionBody(r.ref.decision, { [COLUMN[col].field]: value }) }));
    },
    // A row's fields saved from its details (values checked by checkValue):
    // its writes in order, then the RCM and the tree read again once, also
    // when one is refused (so what was saved shows); the refusal goes back to
    // the field.
    async saveItem(r, values) {
      const id = r.ref.id;
      const send = {
        function: (body) => updatePositionFunction(id, body),
        standard: (body) => updateFunctionStandard(r.ref.standard_id, body),
        "function-standard": (body) => updatePositionFunction(r.ref.function_id, body),
        failure: (body) => updateFunctionalFailure(id, body),
        mode: (body) => updateFailureMode(id, body),
        decide: (body) => decideFailureMode(id, body),
      };
      try {
        for (const w of itemWrites(r, values)) await send[w.api](w.body);
      } finally {
        await after(Promise.resolve());
      }
    },
    // Something new inside a row: a function on a position, a standard on a
    // function, a functional failure on a function (breaching one of its
    // standards, `standardId`, or none), a failure mode on a functional failure
    // (or under none). Asks for its words and adds it from the dialog, which
    // stays open (its button saying "Adding…") until the RCM is read again, so
    // a second click or Enter adds nothing more, and a refusal shows there with
    // the words kept. Returns the new row's id (null when cancelled).
    async add(kind, { positionId, functionId = null, failureId = null, standardId = null }) {
      const id = await askText({
        ...(kind === "fail" && standardId ? WORDS_UNDER_STANDARD : WORDS[kind]),
        pendingLabel: "Adding…",
        run: async (text) => {
          let made;
          if (kind === "fn") made = await addPositionFunction(positionId, { text });
          else if (kind === "std") made = await addFunctionStandard(functionId, { text });
          else if (kind === "fail") made = await addFunctionalFailure(functionId, { text, ...(standardId ? { standard_id: standardId } : {}) });
          else made = await addFailureMode(positionId, { text, functional_failure_id: failureId });
          await after(Promise.resolve());
          return made.id;
        },
      });
      return id || null;
    },
    // A standard moved up or down its function's list (the row menu).
    moveStandard(r, by) {
      const ids = [...(r.ref.standard_ids || [])];
      const i = ids.indexOf(r.ref.standard_id);
      const j = i + by;
      if (i < 0 || j < 0 || j >= ids.length) return Promise.resolve(false);
      [ids[i], ids[j]] = [ids[j], ids[i]];
      return after(reorderFunctionStandards(r.ref.function_id, ids)).then(() => true);
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
        const fails = Array.isArray(r.ref.failures) ? r.ref.failures.length : r.kids.length;
        return `${name} and its ${plural(fails, "functional failure")} go. ${stay}`;
      }
      if (r.type === "std") {
        // The one text's row: the function's text is cleared, nothing else moves.
        if (r.ref.legacy) return `The performance standard ${name} is cleared from this function. Its functional failures stay on the function, with their failure modes.`;
        const fails = r.kids.length;
        const moved = fails
          ? ` Its ${plural(fails, "functional failure")} move${fails === 1 ? "s" : ""} to the function with no performance standard (${fails === 1 ? "it breaches" : "they breach"} the whole function), with ${fails === 1 ? "its" : "their"} failure modes.`
          : "";
        return `${name} comes off this function.${moved}`;
      }
      if (r.type === "fail") return `${name} goes. ${stay}`;
      // Its tasks: one serving it alone is retired; one serving other modes too stays with them.
      const tasks = tasksOf(r.ref).filter((t) => t.id);
      const sole = tasks.filter((t) => !t.shared_with);
      const shared = tasks.length - sole.length;
      const bits = [];
      if (sole.length === 1) bits.push(`its task “${(sole[0].name || "").slice(0, 60)}” is retired too`);
      else if (sole.length) bits.push(`its ${plural(sole.length, "task")} are retired too`);
      if (shared) bits.push(`${shared === 1 ? "a task" : `${shared} tasks`} shared with other failure modes ${shared === 1 ? "stays" : "stay"} with them`);
      const task = bits.length ? ` ${bits.join("; ")[0].toUpperCase()}${bits.join("; ").slice(1)}.` : "";
      return `${name} goes from this position's RCM.${task} Failures already recorded against it keep it in their history.`;
    },
    remove(r) {
      const id = r.ref.id;
      if (r.type === "fn") return after(removePositionFunction(id));
      if (r.type === "std") {
        return after(r.ref.legacy ? updatePositionFunction(r.ref.function_id, { standard: "" }) : removeFunctionStandard(r.ref.standard_id));
      }
      if (r.type === "fail") return after(removeFunctionalFailure(id));
      return after(retireFailureMode(id));
    },
    // The working behind a function's performance standard (the panel's
    // section): the whole function read once when opened (the bulk read has
    // only a preview), the text saved, and PDFs attached or removed. A
    // refusal goes to the caller, who shows it under the field.
    basis: {
      read: (functionId) => getPositionFunction(functionId),
      save: (functionId, text) => after(updatePositionFunction(functionId, { standard_basis: text })),
      attach: (functionId, file, title = "") => after(uploadMaintenanceDocument({ target_id: functionId }, file, { title, kind: "other" })),
      detach: (documentId) => after(removeMaintenanceDocument(documentId)),
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
    // A failure mode's tasks (the dialog's Tasks section): the tasks it has and
    // the ones on its position, or above it, that could serve it; another task
    // added; one changed (a shared task changes for every mode it serves); one
    // taken off (a task serving other modes too is unlinked and stays; one
    // serving this mode alone is retired); an existing task linked.
    modeTasks(r) {
      return getFailureModeTasks(r.ref.id);
    },
    addTask(r, body) {
      return after(addFailureModeTask(r.ref.id, body));
    },
    editTask(taskId, body) {
      return after(updateMaintenanceTask(taskId, body));
    },
    removeTask(r, task) {
      return after(task.shared_with
        ? unlinkTaskFailureMode(task.id, r.ref.id)
        : retireMaintenanceTask(task.id, "Taken off its failure mode."));
    },
    linkTask(r, taskId) {
      return after(linkTaskFailureMode(taskId, r.ref.id));
    },
    // A function's performance standards, as a list (RcmFunctionStandards):
    // each change written at once; split writes the user's edited lines.
    standards: {
      add: (r, body) => after(addFunctionStandard(r.ref.id, body)),
      update: (standardId, body) => after(updateFunctionStandard(standardId, body)),
      remove: (standardId) => after(removeFunctionStandard(standardId)),
      reorder: (r, ids) => after(reorderFunctionStandards(r.ref.id, ids)),
      split: (r, standards) => after(splitFunctionStandard(r.ref.id, { standards, dry_run: false })),
    },
    // A drop (or a Move to…): one batch, all or nothing; the RCM and the
    // tree read again after it's written. dryRun: only checked, nothing read.
    arrange(operations, { dryRun = false } = {}) {
      if (dryRun) return applyRcm(operations, { dryRun: true });
      return after(applyRcm(operations));
    },
    // The standard a functional failure breaches (null: the whole function).
    setBreach(r, standardId) {
      return after(updateFunctionalFailure(r.ref.id, { standard_id: standardId || null }));
    },
  }), [after, askText]);

  return { rcm, error, setError, load, ops };
}
