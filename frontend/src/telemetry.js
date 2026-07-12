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

// Campaign attribution: capture utm_* once per browser session so every
// pageview in the visit stays tied to the link that brought it here.
// sessionStorage, not localStorage — attribution shouldn't outlive the visit.
const UTM_KEY = "reliafy_utm";

function sessionUtm() {
  try {
    const saved = sessionStorage.getItem(UTM_KEY);
    if (saved) return JSON.parse(saved);
    const q = new URLSearchParams(window.location.search);
    const utm = {
      utm_source: q.get("utm_source") || "",
      utm_medium: q.get("utm_medium") || "",
      utm_campaign: q.get("utm_campaign") || "",
    };
    if (utm.utm_source || utm.utm_medium || utm.utm_campaign) {
      sessionStorage.setItem(UTM_KEY, JSON.stringify(utm));
    }
    return utm;
  } catch {
    return {};
  }
}

// document.referrer never changes across SPA navigations, so only the first
// pageview of a page load reports it — referrer counts then measure
// landings (acquisition), not every route change within a visit.
let referrerSent = false;

export function trackEvent(name, extra = {}) {
  let referrer = "";
  if (name === "pageview" && !referrerSent) {
    referrerSent = true;
    referrer = document.referrer || "";
  }
  post("/api/metrics/event", {
    name,
    path: window.location.pathname,
    referrer,
    ...sessionUtm(),
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
