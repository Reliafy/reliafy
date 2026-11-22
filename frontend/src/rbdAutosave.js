// The RBD builder's autosave: the diagram saves itself a moment after each change (debounced),
// one save at a time, and a change made while a save runs is saved after it. A failed save
// waits for Retry (or the next change) rather than trying again in a loop.
//
//   const saver = createAutosaver({ save, onState, delay })
//   saver.schedule()   a change: save `delay` ms after the last one
//   saver.flush()      save now if anything waits (leaving the diagram); a promise
//   saver.retry()      after a failure
//   saver.cancel()     drop what waits (autosave turned off, another diagram opened)
//   saver.dispose()
// `save()` returns a promise; `onState({state, error})` hears "idle" | "pending" | "saving" |
// "failed". The timers can be passed in, for tests.

export const AUTOSAVE_DELAY = 1200;

export function createAutosaver({ save, onState = () => {}, delay = AUTOSAVE_DELAY, timers = globalThis }) {
  let state = "idle";
  let error = null;
  let timer = null;
  let running = null; // the save in flight
  let again = false; // a change came in while it ran
  let disposed = false;
  const set = (s, err = null) => {
    state = s;
    error = err;
    if (!disposed) onState({ state, error });
  };
  const clear = () => {
    if (timer != null) timers.clearTimeout(timer);
    timer = null;
  };
  const run = () => {
    clear();
    if (disposed) return Promise.resolve();
    again = false;
    set("saving");
    running = Promise.resolve()
      .then(() => save())
      .then(
        () => {
          running = null;
          if (again) schedule();
          else set("idle");
        },
        (err) => {
          running = null;
          set("failed", err);
        }
      );
    return running;
  };
  function schedule() {
    if (disposed) return;
    if (running) {
      again = true;
      return;
    }
    clear();
    set("pending", null);
    timer = timers.setTimeout(run, delay);
  }
  return {
    schedule,
    retry: () => (running ? running : run()),
    flush: () => {
      if (running) return running;
      if (timer != null) return run();
      return Promise.resolve();
    },
    cancel: () => {
      clear();
      again = false;
      if (!running && state !== "idle") set("idle");
    },
    dispose: () => {
      clear();
      disposed = true;
    },
    get state() { return state; },
    get error() { return error; },
  };
}

// Someone else saved the diagram since it was opened (the server's 409): trying again can't
// work, so the way out is a copy.
export const isConflict = (err) => err?.status === 409 || err?.data?.code === "conflict" || err?.code === "conflict";

// Whether leaving now would lose changes: they're unsaved and autosave won't keep them (it's
// off, or the diagram isn't one it saves, or its last save failed). The Explorer's pane asks
// before closing, and the page asks before following a link.
export function leaveLosesChanges({ dirty, autosave, saveState }) {
  return !!dirty && (!autosave || saveState === "failed");
}

// A save is waiting or running (the update bar holds a reload back for it).
export const savePending = ({ dirty, autosave, saveState }) =>
  !!autosave && (saveState === "pending" || saveState === "saving" || (!!dirty && saveState !== "failed"));

// What closing or reloading the tab does: "ask" (the browser's own prompt) only when changes would
// be lost: autosave off, or its save failed, or the save is too big to send as the page goes
// (a keepalive request carries 64 KB at most). Otherwise a waiting save is "send"t at once with
// keepalive, and "none" when nothing waits.
export const KEEPALIVE_LIMIT = 60000;
export function unloadAction({ dirty, autosave, saveState, bodyBytes = 0 }) {
  if (leaveLosesChanges({ dirty, autosave, saveState })) return "ask";
  if (!savePending({ dirty, autosave, saveState })) return "none";
  return bodyBytes > KEEPALIVE_LIMIT ? "ask" : "send";
}
export const unloadShouldAsk = (a) => unloadAction(a) === "ask";
