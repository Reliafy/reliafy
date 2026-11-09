// Cancelling a long calculation (a simulation, a condition-based fit, a
// sampled calendar, a test plan checked by simulation).
//
// A calculation either comes back as a job to poll (the calculation service)
// or answers in the request itself (no queue: self-hosted, dev). Both are
// cancelled the same way: the page stops waiting at once and tells the server
// (POST /api/rbd-jobs/{id}/cancel), with the job's id, or with the run token
// the page sent with the request. The server marks the job cancelled and
// throws its result away when it still arrives; the page ignores any answer
// to a cancelled run.

// A fresh token to send with a request that may compute in the request.
export function newRunToken() {
  const c = globalThis.crypto;
  if (c?.randomUUID) return c.randomUUID().replace(/-/g, "");
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}

// Which run is current. ``start()`` begins one and returns its token;
// ``cancel()`` ends it (returning its token, for the server); an answer is
// used only while ``isCurrent(token)``. Starting a new run supersedes the
// old one the same way.
export function createRunGuard() {
  let current = null;
  return {
    start() {
      current = newRunToken();
      return current;
    },
    cancel() {
      const token = current;
      current = null;
      return token;
    },
    finish(token) {
      if (token && token === current) current = null;
    },
    isCurrent(token) {
      return token != null && token === current;
    },
    get active() {
      return current != null;
    },
  };
}

// The id to cancel on the server: the job's when it was queued, otherwise
// the run's token (null when there is nothing to cancel).
export function cancelTarget({ jobId = null, runToken = null } = {}) {
  return jobId || runToken || null;
}

// Whether a polled job has stopped (and so polling should).
export function jobFinished(status) {
  return status === "done" || status === "failed" || status === "cancelled";
}

export const CANCELLED_TEXT = "Cancelled. Nothing was kept — run it again when you're ready.";
