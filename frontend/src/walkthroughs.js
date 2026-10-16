// In-app guided walkthroughs (#32): the step definitions, as data, and the
// pure helpers the Walkthrough component runs on. Each walkthrough opens a
// shared sample and points at the real controls, one sentence a step.
//
// A step:
//   target  CSS selector (or a list, first match wins) of the element to point at.
//           Point at a data-wt anchor on the element itself, not a class path:
//           class names and markup move (the shared tab row did), anchors don't.
//   text    one sentence
//   next    "click" — Next also clicks the target (runs the fit, opens the tab),
//           so the following step can point at what that shows
//   wait    ms to wait for the target to appear (default TARGET_WAIT_MS)
//
// The ids are also the backend's allowlist (backend/services/walkthroughs.py):
// keep them in step.

export const TARGET_WAIT_MS = 5000;
// At or below this width the callout is a bottom sheet.
export const SHEET_MAX_WIDTH = 600;

export const WALKTHROUGHS = {
  fit: {
    title: "Fit a model",
    route: "/models/new?dataset=sample-ds-bearings",
    steps: [
      {
        target: ['[data-wt="fit-data"] .ds-summary', '[data-wt="fit-data"]'],
        text: "This is the bearing sample: 30 failure times in hours, and with no column for units still running, every row counts as a failure.",
      },
      {
        target: '[data-wt="fit-next"]',
        text: "Next moves on to the model, where you choose the distribution to fit.",
        next: "click",
      },
      {
        target: '[data-wt="fit-run"]',
        text: "Weibull suits wear-out data like this, and Fit estimates its shape and scale from the 30 times.",
        next: "click",
      },
      {
        target: ['[data-wt="fit-result"] .gof-card', '[data-wt="fit-result"]'],
        text: "The answer: a shape β above 1 means failures rise with age; name the model and save it to use in Strategy and Forecasts.",
        wait: 15000,
      },
    ],
  },
  replacement: {
    title: "Optimal replacement",
    route: "/strategy/replacement?model=sample-model-bearings-weibull&planned=200&unplanned=1500",
    steps: [
      {
        target: '[data-wt="repl-model"]',
        text: "Start from a life model: here, the bearing sample's Weibull fit.",
      },
      {
        target: '[data-wt="repl-costs"]',
        text: "Then what each event costs: 200 to replace a bearing on schedule, 1,500 when one fails in service.",
      },
      {
        target: '[data-wt="repl-run"]',
        text: "Compute finds the replacement age with the lowest long-run cost per hour.",
        next: "click",
      },
      {
        target: '[data-wt="repl-result"]',
        text: "The answer: the age to replace at and what it saves against running to failure; save it to cite in an RCM study.",
        wait: 15000,
      },
    ],
  },
  rbd: {
    title: "Build a block diagram",
    route: "/systems/b/sample-rbd-pump-station",
    steps: [
      {
        target: '[data-wt="rbd-canvas"]',
        text: "A controller in series with two pumps in parallel: the system runs while the controller and either pump work.",
        wait: 8000,
      },
      {
        target: '[data-wt="rbd-add"]',
        text: "Add a block here, or right-click the canvas, then drag from one block's edge to the next to wire it in.",
      },
      {
        target: '[data-wt="rbd-tab-calc"]',
        text: "The Calculator works out the whole system from its blocks.",
        next: "click",
      },
      {
        // The last step's Done runs the calculation, so it ends on the answer.
        target: '[data-wt="rbd-calculate"]',
        text: "Calculate gives the system's reliability over time and its mean life; Done runs it for this diagram.",
        next: "click",
        wait: 8000,
      },
    ],
  },
  rcm: {
    title: "An RCM study",
    route: "/maintenance/rcm/sample-rcm-truck",
    steps: [
      {
        target: '[data-wt="rcm-function"]',
        text: "A study starts from what the system must do, its functions, and then the ways each one can fail.",
      },
      {
        target: '[data-wt="rcm-mode"]',
        text: "Each failure mode gets a decision: inspect its condition, replace on a schedule, check a hidden function, or run to failure.",
      },
      {
        target: '[data-wt="rcm-evidence"]',
        text: "Link a decision to its evidence, a saved model or analysis, and Reliafy checks that the evidence backs it.",
      },
      {
        target: '[data-wt="rcm-checks"]',
        text: "The checks run each time you open the study: here one run-to-failure call is contradicted, because its own model shows wear-out.",
      },
    ],
  },
  fleet: {
    title: "A fleet forecast",
    route: "/forecasts/sample-fleet-trucks",
    steps: [
      {
        target: '[data-wt="fleet-model"]',
        text: "A forecast runs every item in a fleet against one life model, here the bearing Weibull.",
      },
      {
        target: '[data-wt="fleet-assume"]',
        text: "It assumes how much each item is used a month and how far ahead to look.",
      },
      {
        target: '[data-wt="fleet-answer"]',
        text: "The answer: how many failures to expect over the horizon, replacements failing again included, with a likely range.",
        wait: 15000,
      },
      {
        target: '[data-wt="fleet-items"]',
        text: "Each item's use so far sets its share; add your own items, or send usage over the API to keep the forecast current.",
      },
    ],
  },
};

export const WALKTHROUGH_IDS = ["fit", "replacement", "rbd", "rcm", "fleet"];

export function getWalkthrough(id) {
  return Object.prototype.hasOwnProperty.call(WALKTHROUGHS, id) ? WALKTHROUGHS[id] : null;
}

// A step's selectors, as a list.
export function targetsOf(step) {
  if (!step || !step.target) return [];
  return Array.isArray(step.target) ? step.target : [step.target];
}

function splitRoute(route) {
  const i = route.indexOf("?");
  return i < 0 ? [route, ""] : [route.slice(0, i), route.slice(i + 1)];
}

// Whether the page at ``pathname`` + ``search`` is the walkthrough's start:
// the same path, and every query value the route sets (extra ones are fine).
export function routeMatches(route, pathname, search = "") {
  const [path, query] = splitRoute(route);
  if ((pathname || "").replace(/\/+$/, "") !== path.replace(/\/+$/, "")) return false;
  const want = new URLSearchParams(query);
  const have = new URLSearchParams(search || "");
  for (const [k, v] of want) {
    if (have.get(k) !== v) return false;
  }
  return true;
}

// A link that opens a page and starts a walkthrough there (?walkthrough=id).
// ``auto`` marks a start nobody asked for (a first-run start), which runs
// at most once per user.
export function launchHref(id, { auto = false } = {}) {
  const wt = getWalkthrough(id);
  if (!wt) return null;
  const [path, query] = splitRoute(wt.route);
  const q = new URLSearchParams(query);
  q.set("walkthrough", id);
  if (auto) q.set("auto", "1");
  return `${path}?${q.toString()}`;
}

// ``to`` with walkthrough ``id`` started on arrival, when ``to`` is that
// walkthrough's page; otherwise ``to`` unchanged (a link to some other
// diagram or sample gets no walkthrough).
export function withLaunch(to, id, { auto = false } = {}) {
  const wt = getWalkthrough(id);
  if (!wt || typeof to !== "string") return to;
  const [path, query] = splitRoute(to);
  if (!routeMatches(wt.route, path, query)) return to;
  const q = new URLSearchParams(query);
  q.set("walkthrough", id);
  if (auto) q.set("auto", "1");
  return `${path}?${q.toString()}`;
}

// The walkthrough a URL asks to start: { id, auto } or null.
export function parseLaunch(search) {
  const q = new URLSearchParams(search || "");
  const id = q.get("walkthrough");
  if (!id || !getWalkthrough(id)) return null;
  return { id, auto: q.get("auto") === "1" };
}

// ``search`` without the launch parameters ("" when nothing else is left).
export function stripLaunch(search) {
  const q = new URLSearchParams(search || "");
  q.delete("walkthrough");
  q.delete("auto");
  const s = q.toString();
  return s ? `?${s}` : "";
}

// Back is offered unless this is the first step, or the step before it
// clicked something (a fit run or a tab opened can't be undone by Back).
export function canGoBack(steps, index) {
  if (index <= 0) return false;
  return steps[index - 1]?.next !== "click";
}

// One move through a walkthrough. ``run`` is { index, reached } (reached:
// the furthest step index seen). Returns the next run, plus:
//   done    "completed" | "skipped" when the walkthrough ends
//   reachedNew  true when the move shows a step for the first time
//   click   true when the current target should be clicked first
export function move(run, action, steps) {
  const n = steps.length;
  const { index, reached } = run;
  const stay = { index, reached };
  if (action === "skip") return { ...stay, done: "skipped" };
  if (action === "back") return canGoBack(steps, index) ? { index: index - 1, reached } : stay;
  if (action === "next") {
    const click = steps[index]?.next === "click";
    if (index >= n - 1) return { ...stay, done: "completed", click };
    const to = index + 1;
    return { index: to, reached: Math.max(reached, to), reachedNew: to > reached, click };
  }
  return stay;
}

// The highlight ring around a target, ``pad`` px outside it.
export function ringRect(rect, pad = 6) {
  return {
    top: rect.top - pad,
    left: rect.left - pad,
    width: rect.width + pad * 2,
    height: rect.height + pad * 2,
  };
}

// Where the callout goes. On a narrow screen it's a bottom sheet; otherwise
// below the target, else above, else beside it, clamped inside the viewport
// with ``margin`` px to spare. ``rect`` is the target's viewport rect,
// ``size`` the callout's { width, height }, ``viewport`` { width, height }.
export function placeCallout(rect, size, viewport, { margin = 16, gap = 12 } = {}) {
  if (viewport.width <= SHEET_MAX_WIDTH) return { mode: "sheet" };
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(v, Math.max(lo, hi)));
  const left = clamp(rect.left, margin, viewport.width - size.width - margin);
  const below = rect.top + rect.height + gap;
  if (below + size.height <= viewport.height - margin) return { mode: "float", side: "below", top: below, left };
  const above = rect.top - gap - size.height;
  if (above >= margin) return { mode: "float", side: "above", top: above, left };
  const top = clamp(rect.top, margin, viewport.height - size.height - margin);
  const right = rect.left + rect.width + gap;
  if (right + size.width <= viewport.width - margin) return { mode: "float", side: "right", top, left: right };
  const leftSide = rect.left - gap - size.width;
  if (leftSide >= margin) return { mode: "float", side: "left", top, left: leftSide };
  // A target as big as the screen: sit over its lower edge, inside the viewport.
  return { mode: "float", side: "over", top: clamp(viewport.height - size.height - margin, margin, viewport.height), left };
}

// Whether a rect is (at least partly) on screen, with ``inset`` px kept
// clear at the bottom (the bottom sheet's height on a phone).
export function rectInView(rect, viewport, inset = 0) {
  return rect.top >= 0 && rect.top + Math.min(rect.height, 80) <= viewport.height - inset;
}

// The admin report's step funnel for one walkthrough's row ({ steps: {"1": n,
// …} }): how many runs reached each of its steps, in order, zeros included.
export function stepFunnel(row, id) {
  const wt = getWalkthrough(id);
  const n = wt ? wt.steps.length : Object.keys(row?.steps || {}).length;
  return Array.from({ length: n }, (_, i) => Number(row?.steps?.[String(i + 1)] || 0));
}
