// First-party telemetry: report client errors and pageviews to the backend,
// which logs them (Cloud Logging / Error Reporting in the cloud). No cookies,
// no third parties, fire-and-forget.

function post(url, payload) {
  try {
    const body = JSON.stringify(payload);
    if (navigator.sendBeacon) {
      navigator.sendBeacon(url, new Blob([body], { type: "application/json" }));
    } else {
      fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        keepalive: true,
      }).catch(() => {});
    }
  } catch {
    /* telemetry must never break the app */
  }
}

export function reportError(message, stack) {
  post("/api/client-error", {
    message: String(message || "").slice(0, 1000),
    stack: String(stack || "").slice(0, 4000),
    path: window.location.pathname,
  });
}

export function trackEvent(name, extra = {}) {
  post("/api/metrics/event", {
    name,
    path: window.location.pathname,
    referrer: document.referrer || "",
    ...extra,
  });
}

let installed = false;

// Global handlers for errors that never reach a React boundary.
export function installTelemetry() {
  if (installed) return;
  installed = true;
  window.addEventListener("error", (e) => {
    reportError(e.message, e.error?.stack);
  });
  window.addEventListener("unhandledrejection", (e) => {
    const r = e.reason;
    reportError(r?.message || String(r), r?.stack);
  });
}
