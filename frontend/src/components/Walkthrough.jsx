import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { portalHost } from "../fullScreen.js";
import { useLocation, useNavigate } from "react-router-dom";
import { claimWalkthroughAutoStart } from "../api.js";
import { trackEvent } from "../telemetry.js";
import {
  TARGET_WAIT_MS,
  canGoBack,
  getWalkthrough,
  move,
  parseLaunch,
  placeCallout,
  rectInView,
  ringRect,
  routeMatches,
  stripLaunch,
  targetsOf,
} from "../walkthroughs.js";
import "./Walkthrough.css";

// In-app guided walkthroughs (#32): a small callout anchored to the real
// control, one sentence a step, with Next / Back / Skip, and a ring around
// the control. A bottom sheet on a phone. Steps are data (walkthroughs.js).
//
// Started by start(id) (the "Show me how" links) or by a URL carrying
// ?walkthrough=<id> (&auto=1 for a first-run start, which runs at most once
// per user). Started, each step reached, completed and skipped are counted
// as product events. If a step's control isn't on the page, or the user
// leaves the page, the walkthrough ends quietly. Nothing here may throw into
// the page: every DOM touch is guarded.

// null outside the app shell (a public share page): no walkthroughs there.
const Ctx = createContext(null);

export function useWalkthrough() {
  return useContext(Ctx);
}

// How long a shown step's control may be missing (a re-render swapping the
// element) before the walkthrough gives up.
const LOST_MS = 800;

function visible(el) {
  try {
    return !!el && el.isConnected && el.getClientRects().length > 0;
  } catch {
    return false;
  }
}

function findTarget(step) {
  for (const sel of targetsOf(step)) {
    try {
      const el = document.querySelector(sel);
      if (visible(el)) return el;
    } catch {
      // A bad selector is a missing target.
    }
  }
  return null;
}

function sameRect(a, b) {
  return a && b && a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height;
}

export function WalkthroughProvider({ children }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [run, setRun] = useState(null); // { id, index, reached, path, arrived, key }
  const runRef = useRef(null);
  runRef.current = run;
  const targetRef = useRef(null);
  const openerRef = useRef(null);
  const loggedRef = useRef(new Set());

  const end = useCallback((outcome) => {
    const r = runRef.current;
    if (!r) return;
    if (outcome === "completed") trackEvent("walkthrough_completed", { walkthrough: r.id, step: r.index + 1 });
    if (outcome === "skipped") trackEvent("walkthrough_skipped", { walkthrough: r.id, step: r.index + 1 });
    runRef.current = null;
    targetRef.current = null;
    setRun(null);
    // Focus goes back to whatever started it when that is still on the page,
    // else to the page's title (a walkthrough often opens another page).
    const opener = openerRef.current;
    openerRef.current = null;
    try {
      if (opener && opener.isConnected && opener !== document.body && typeof opener.focus === "function") {
        opener.focus();
      } else {
        const title = document.querySelector("main h1");
        if (title) {
          if (!title.hasAttribute("tabindex")) title.setAttribute("tabindex", "-1");
          title.focus({ preventScroll: true });
        }
      }
    } catch {
      /* focus is a nicety */
    }
  }, []);

  const start = useCallback(
    async (id, { auto = false, here = null } = {}) => {
      const wt = getWalkthrough(id);
      if (!wt) return;
      if (auto) {
        // A start nobody asked for runs once per user: the server keeps the
        // claim, so another tab or device doesn't run it again.
        let claimed = false;
        try {
          claimed = !!(await claimWalkthroughAutoStart(id)).start;
        } catch {
          claimed = false;
        }
        if (!claimed) return;
      }
      openerRef.current = document.activeElement;
      loggedRef.current = new Set();
      const at = here || window.location;
      if (!routeMatches(wt.route, at.pathname, at.search)) navigate(wt.route);
      const path = wt.route.split("?")[0];
      setRun({ id, index: 0, reached: 0, path, arrived: false, key: Date.now() });
      trackEvent("walkthrough_started", { walkthrough: id });
    },
    [navigate]
  );

  // ?walkthrough=<id>[&auto=1]: take the parameters off the URL (a reload
  // shouldn't start it again), then start.
  useEffect(() => {
    const launch = parseLaunch(location.search);
    if (!launch) return;
    const search = stripLaunch(location.search);
    navigate({ pathname: location.pathname, search, hash: location.hash }, { replace: true });
    start(launch.id, { auto: launch.auto, here: { pathname: location.pathname, search } });
  }, [location.search, location.pathname, location.hash, navigate, start]);

  // A page that never opens (a bad route) ends it too.
  useEffect(() => {
    if (!run || run.arrived) return undefined;
    const t = setTimeout(() => {
      const r = runRef.current;
      if (r && r.key === run.key && !r.arrived) end(null);
    }, TARGET_WAIT_MS);
    return () => clearTimeout(t);
  }, [run, end]);

  // Leaving the walkthrough's page ends it.
  useEffect(() => {
    const r = runRef.current;
    if (!r) return;
    if (location.pathname.replace(/\/+$/, "") === r.path) {
      if (!r.arrived) setRun({ ...r, arrived: true });
    } else if (r.arrived) {
      end(null);
    }
  }, [location.pathname, run, end]);

  const onMove = useCallback(
    (action) => {
      const r = runRef.current;
      const wt = r && getWalkthrough(r.id);
      if (!wt) return;
      const res = move(r, action, wt.steps);
      if (res.click) {
        try {
          targetRef.current?.click();
        } catch {
          /* the step after it will find its control or end quietly */
        }
      }
      if (res.done) {
        end(res.done);
        return;
      }
      if (res.index !== r.index) setRun({ ...r, index: res.index, reached: res.reached });
    },
    [end]
  );

  const onShown = useCallback((r) => {
    if (loggedRef.current.has(r.index)) return;
    loggedRef.current.add(r.index);
    trackEvent("walkthrough_step", { walkthrough: r.id, step: r.index + 1 });
  }, []);

  return (
    <Ctx.Provider value={{ start, active: run?.id || null }}>
      {children}
      {run && run.arrived && (
        <WalkthroughCallout
          key={`${run.key}-${run.index}`}
          run={run}
          targetRef={targetRef}
          onMove={onMove}
          onEnd={end}
          onShown={onShown}
        />
      )}
    </Ctx.Provider>
  );
}

function WalkthroughCallout({ run, targetRef, onMove, onEnd, onShown }) {
  const wt = getWalkthrough(run.id);
  const steps = wt.steps;
  const step = steps[run.index];
  const [rect, setRect] = useState(null);
  const [size, setSize] = useState({ width: 320, height: 160 });
  const [viewport, setViewport] = useState({ width: window.innerWidth, height: window.innerHeight });
  const boxRef = useRef(null);
  const textId = `wt-text-${run.id}`;
  const titleId = `wt-title-${run.id}`;

  // Find the step's control: wait for it to render (a page loading, a fit
  // running), then bring it into view. Missing after the wait: end quietly.
  useEffect(() => {
    let cancelled = false;
    let timer = null;
    const deadline = Date.now() + (step.wait ?? TARGET_WAIT_MS);
    const look = () => {
      if (cancelled) return;
      const el = findTarget(step);
      if (el) {
        targetRef.current = el;
        try {
          const r = el.getBoundingClientRect();
          const vp = { width: window.innerWidth, height: window.innerHeight };
          const sheet = vp.width <= 600 ? 200 : 0;
          if (!rectInView(r, vp, sheet)) el.scrollIntoView({ block: "center", inline: "nearest" });
          setRect(el.getBoundingClientRect());
        } catch {
          onEnd(null);
          return;
        }
        onShown(run);
        return;
      }
      if (Date.now() > deadline) {
        onEnd(null);
        return;
      }
      timer = setTimeout(look, 100);
    };
    look();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Follow the control as the page scrolls, resizes or re-renders; if it
  // goes away for good, end quietly.
  const found = !!rect;
  useEffect(() => {
    if (!found) return undefined;
    let frame = 0;
    let lostAt = 0;
    let last = null;
    const tick = () => {
      let el = targetRef.current;
      if (!visible(el)) {
        el = findTarget(step);
        if (el) targetRef.current = el;
      }
      if (!el) {
        lostAt = lostAt || Date.now();
        if (Date.now() - lostAt > LOST_MS) {
          onEnd(null);
          return;
        }
      } else {
        lostAt = 0;
        try {
          const r = el.getBoundingClientRect();
          const next = { top: r.top, left: r.left, width: r.width, height: r.height };
          if (!sameRect(next, last)) {
            last = next;
            setRect(next);
          }
        } catch {
          /* measured next frame */
        }
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    const onResize = () => setViewport({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener("resize", onResize);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [found]);

  // Focus moves to the callout when its step shows, so a screen reader reads
  // the sentence and Tab reaches Skip / Back / Next. It's not modal: the page
  // stays usable, and focus returns to the opener when it ends.
  useEffect(() => {
    if (found) boxRef.current?.focus({ preventScroll: true });
  }, [found]);

  // Escape closes, from anywhere on the page.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onMove("skip");
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [onMove]);

  useLayoutEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const next = { width: box.offsetWidth, height: box.offsetHeight };
    if (next.width !== size.width || next.height !== size.height) setSize(next);
  });

  const place = rect ? placeCallout(rect, size, viewport) : null;
  const sheet = place?.mode === "sheet";

  // A bottom sheet mustn't hide the control: scroll it up above the sheet
  // (the spacer below lets the page scroll that far at its end).
  useEffect(() => {
    if (!sheet) return;
    try {
      const el = targetRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const limit = window.innerHeight - size.height - 32;
      const room = r.top - 64; // keep the top bar clear
      if (r.bottom > limit && room > 0) window.scrollBy(0, Math.min(r.bottom - limit, room));
    } catch {
      /* the step still shows */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sheet, size.height, found]);

  if (!rect) return null;
  const ring = ringRect(rect);
  const last = run.index === steps.length - 1;
  const back = canGoBack(steps, run.index);
  const style = sheet ? undefined : { top: place.top, left: place.left };

  return createPortal(
    <>
      {sheet && <div className="wt-spacer" aria-hidden="true" style={{ height: size.height + 32 }} />}
      <div className="wt-ring" aria-hidden="true" style={ring} />
      <div
        ref={boxRef}
        className={"wt-callout" + (sheet ? " wt-sheet" : "")}
        style={style}
        role="dialog"
        aria-modal="false"
        aria-labelledby={titleId}
        aria-describedby={textId}
        tabIndex={-1}
      >
        <div className="wt-head" id={titleId}>
          {wt.title} · {run.index + 1} of {steps.length}
        </div>
        <p className="wt-text" id={textId}>
          {step.text}
        </p>
        <div className="wt-actions">
          <button type="button" className="link wt-skip" onClick={() => onMove("skip")}>
            Skip
          </button>
          <span className="wt-grow" />
          {back && (
            <button type="button" className="secondary sm" onClick={() => onMove("back")}>
              Back
            </button>
          )}
          <button type="button" className="sm" onClick={() => onMove("next")}>
            {last ? "Done" : "Next"}
          </button>
        </div>
      </div>
    </>,
    portalHost()
  );
}

// "Show me how": starts walkthrough ``id`` (opening its page if need be).
// Renders nothing outside the app shell.
export function ShowMeHow({ id, children = "Show me how", className = "" }) {
  const ctx = useWalkthrough();
  if (!ctx || !getWalkthrough(id)) return null;
  return (
    <button type="button" className={"link wt-launch" + (className ? " " + className : "")} onClick={() => ctx.start(id)}>
      {children}
    </button>
  );
}
