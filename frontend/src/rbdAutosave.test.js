// Run with: node --test src/
// The RBD builder's autosave (debounce, one save at a time, failure and retry, off), its
// status words, and Undo/Redo.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createAutosaver, isConflict } from "./rbdAutosave.js";
import { rbdSaveStatus } from "./rbdSaveState.js";
import { canRedo, canUndo, emptyHistory, historyKey, recordHistory, redoHistory, resetHistory, undoHistory } from "./rbdHistory.js";

// Timers we move by hand.
function fakeTimers() {
  let now = 0;
  let seq = 0;
  const due = new Map();
  return {
    setTimeout: (fn, ms) => { seq += 1; due.set(seq, { at: now + ms, fn }); return seq; },
    clearTimeout: (id) => { due.delete(id); },
    advance(ms) {
      now += ms;
      for (const [id, t] of [...due]) if (t.at <= now) { due.delete(id); t.fn(); }
    },
    pending: () => due.size,
  };
}
const tick = () => new Promise((r) => setImmediate(r));

test("autosave: one save, a moment after the last of several changes", async () => {
  const timers = fakeTimers();
  let saves = 0;
  const states = [];
  const s = createAutosaver({ save: async () => { saves += 1; }, onState: ({ state }) => states.push(state), delay: 1000, timers });
  s.schedule();
  timers.advance(600);
  s.schedule(); // another change before the first save: the wait starts again
  timers.advance(600);
  assert.equal(saves, 0);
  timers.advance(400);
  await tick();
  assert.equal(saves, 1);
  assert.equal(s.state, "idle");
  assert.deepEqual(states, ["pending", "pending", "saving", "idle"]);
});

test("autosave: a change while a save runs is saved after it, never two at once", async () => {
  const timers = fakeTimers();
  let inFlight = 0;
  let most = 0;
  let saves = 0;
  let release;
  const s = createAutosaver({
    save: () => { inFlight += 1; most = Math.max(most, inFlight); saves += 1;
      return new Promise((r) => { release = () => { inFlight -= 1; r(); }; }); },
    delay: 500, timers,
  });
  s.schedule();
  timers.advance(500);
  assert.equal(s.state, "saving");
  s.schedule(); // during the save
  assert.equal(timers.pending(), 0);
  await tick();
  release();
  await tick();
  assert.equal(s.state, "pending");
  timers.advance(500);
  await tick();
  release();
  await tick();
  assert.equal(saves, 2);
  assert.equal(most, 1);
  assert.equal(s.state, "idle");
});

test("autosave: a failed save waits for Retry, and Retry saves", async () => {
  const timers = fakeTimers();
  let fail = true;
  let saves = 0;
  const s = createAutosaver({ save: async () => { saves += 1; if (fail) throw new Error("Offline"); }, delay: 100, timers });
  s.schedule();
  timers.advance(100);
  await tick();
  assert.equal(s.state, "failed");
  assert.equal(s.error.message, "Offline");
  timers.advance(10_000); // no loop of retries
  assert.equal(saves, 1);
  fail = false;
  await s.retry();
  assert.equal(s.state, "idle");
  assert.equal(saves, 2);
});

test("autosave: flush saves at once what waits; cancel (autosave off) drops it", async () => {
  const timers = fakeTimers();
  let saves = 0;
  const s = createAutosaver({ save: async () => { saves += 1; }, delay: 1000, timers });
  s.schedule();
  await s.flush();
  assert.equal(saves, 1);
  await s.flush(); // nothing waits
  assert.equal(saves, 1);
  s.schedule();
  s.cancel();
  timers.advance(5000);
  assert.equal(saves, 1);
  assert.equal(s.state, "idle");
  s.dispose();
  s.schedule();
  timers.advance(5000);
  assert.equal(saves, 1);
});

test("save status: autosave says Saving…, Saved or Couldn't save with what to do", () => {
  const base = { savedId: "r1", readOnly: false, autosave: true };
  assert.equal(rbdSaveStatus({ ...base, dirty: true, saveState: "pending" }).text, "Saving…");
  assert.equal(rbdSaveStatus({ ...base, dirty: false, saveState: "saving" }).text, "Saving…");
  assert.equal(rbdSaveStatus({ ...base, dirty: false, saveState: "idle" }).text, "Saved");
  const failed = rbdSaveStatus({ ...base, dirty: true, saveState: "failed", error: new Error("Check your connection") });
  assert.deepEqual([failed.text, failed.action], ["Couldn't save", "retry"]);
  assert.match(failed.title, /Check your connection\. Your changes are still here/);
  const conflict = Object.assign(new Error("Changed"), { status: 409 });
  assert.equal(isConflict(conflict), true);
  assert.equal(rbdSaveStatus({ ...base, dirty: true, saveState: "failed", error: conflict }).action, "copy");
  // Off: the explicit Save's words, as before.
  assert.equal(rbdSaveStatus({ savedId: "r1", readOnly: false, dirty: true }).text, "Unsaved changes");
  assert.equal(rbdSaveStatus({ savedId: "r1", readOnly: false, dirty: false }).text, "Saved");
  // Never autosaved: a sample, or a diagram not saved yet.
  assert.equal(rbdSaveStatus({ savedId: "r1", readOnly: true, dirty: true, autosave: false }).text, "Unsaved changes");
  assert.equal(rbdSaveStatus({ savedId: null, readOnly: false, dirty: true }).text, "Not saved yet");
});

test("undo and redo step through the diagram's states; a new edit clears redo", () => {
  let h = resetHistory("A", "a");
  assert.equal(canUndo(h), false);
  h = recordHistory(h, "B", "b");
  h = recordHistory(h, "B again", "b"); // the same diagram: not a step
  h = recordHistory(h, "C", "c");
  let u = undoHistory(h);
  assert.equal(u.state, "B");
  u = undoHistory(u.history);
  assert.equal(u.state, "A");
  assert.equal(undoHistory(u.history), null); // the diagram as opened
  const r = redoHistory(u.history);
  assert.equal(r.state, "B");
  assert.equal(canRedo(r.history), true);
  const edited = recordHistory(r.history, "D", "d");
  assert.equal(canRedo(edited), false);
  assert.equal(undoHistory(edited).state, "B");
});

test("undo keeps the last 100 steps; the first state of an empty history is where Undo stops", () => {
  let h = emptyHistory();
  for (let i = 0; i <= 150; i += 1) h = recordHistory(h, i, String(i));
  assert.equal(h.past.length, 100);
  assert.equal(h.present.state, 150);
});

test("the undo keys: Ctrl/⌘-Z, Ctrl/⌘-Shift-Z and Ctrl-Y", () => {
  assert.equal(historyKey({ key: "z", ctrlKey: true }), "undo");
  assert.equal(historyKey({ key: "z", metaKey: true }), "undo");
  assert.equal(historyKey({ key: "Z", metaKey: true, shiftKey: true }), "redo");
  assert.equal(historyKey({ key: "y", ctrlKey: true }), "redo");
  assert.equal(historyKey({ key: "z" }), null);
  assert.equal(historyKey({ key: "z", ctrlKey: true, altKey: true }), null);
});

test("leaving: asks only when changes would be lost", async () => {
  const { leaveLosesChanges, unloadShouldAsk, unloadAction } = await import("./rbdAutosave.js");
  // Autosave off: unsaved changes are lost on leaving.
  assert.equal(leaveLosesChanges({ dirty: true, autosave: false, saveState: "idle" }), true);
  assert.equal(leaveLosesChanges({ dirty: false, autosave: false, saveState: "idle" }), false);
  // On: the pending save is flushed, nothing to ask; unless the last save failed.
  assert.equal(leaveLosesChanges({ dirty: true, autosave: true, saveState: "pending" }), false);
  assert.equal(leaveLosesChanges({ dirty: true, autosave: true, saveState: "failed" }), true);
  // Closing the tab while a save waits or runs: it is sent at once (keepalive); no prompt.
  assert.equal(unloadShouldAsk({ dirty: true, autosave: true, saveState: "pending" }), false);
  assert.equal(unloadAction({ dirty: true, autosave: true, saveState: "pending", bodyBytes: 500 }), "send");
  assert.equal(unloadAction({ dirty: true, autosave: true, saveState: "saving", bodyBytes: 500 }), "send");
  assert.equal(unloadAction({ dirty: false, autosave: true, saveState: "idle" }), "none");
  // Too big to send as the page goes, or the save failed: ask.
  assert.equal(unloadAction({ dirty: true, autosave: true, saveState: "pending", bodyBytes: 90000 }), "ask");
  assert.equal(unloadAction({ dirty: true, autosave: true, saveState: "failed", bodyBytes: 500 }), "ask");
  assert.equal(unloadShouldAsk({ dirty: false, autosave: true, saveState: "idle" }), false);
  assert.equal(unloadShouldAsk({ dirty: true, autosave: false, saveState: "idle" }), true);
});
