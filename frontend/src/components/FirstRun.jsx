import { useEffect } from "react";
import { Link } from "react-router-dom";
import { trackEvent } from "../telemetry.js";
import { MCP_CONTACT } from "../appConfig.js";
import { useAppConfig } from "../ConfigProvider.jsx";
import { PasteIcon, RbdIcon, UploadIcon, WaveIcon } from "./icons.jsx";
import { SAMPLE_MODEL } from "../firstRun.js";
import { withLaunch } from "../walkthroughs.js";
import { ShowMeHow } from "./Walkthrough.jsx";

// First-run starts (#194). Each start reports one client event (allowlisted in
// backend/routers/telemetry.py), so first actions can be counted against
// signups. ``upload`` (#312) is only on Home's "Start here".
function starts({ sampleModelId, sampleRbdId }, { upload = false } = {}) {
  const list = [];
  if (upload) {
    list.push({
      key: "upload",
      to: "/modelling/new?mode=data",
      icon: <UploadIcon />,
      title: "Upload a CSV or Excel file",
      body: "A column of times to failure, and a 0/1 column for units still running if you have one.",
      cta: "Upload",
      short: "Upload a file",
    });
  }
  list.push({
    key: "paste",
    to: "/modelling/new?mode=paste",
    onClick: () => trackEvent("first_run_paste"),
    icon: <PasteIcon />,
    title: "Paste failure times",
    body: "Copy a column of times from a spreadsheet and fit a distribution. Add 0/1 for units still running.",
    cta: "Paste data",
    short: "Paste failure times",
  });
  if (sampleModelId) {
    list.push({
      key: "sample",
      to: `/modelling/m/${sampleModelId}`,
      onClick: () => trackEvent("first_run_sample"),
      icon: <WaveIcon />,
      title: "Open a sample model",
      body:
        sampleModelId === SAMPLE_MODEL
          ? "A Weibull fit to 30 bearing failure times, with its probability plot and calculator."
          : "A model already fitted to sample data, with its plots and life metrics.",
      cta: "Open sample",
      short: "Open a sample model",
    });
  }
  list.push({
    key: "rbd",
    // The sample diagram opens with its walkthrough, once per user (#32).
    to: sampleRbdId ? withLaunch(`/rbds/b/${sampleRbdId}`, "rbd", { auto: true }) : "/rbds/b",
    onClick: () => trackEvent("first_run_rbd"),
    icon: <RbdIcon />,
    title: "Build a block diagram",
    body: sampleRbdId
      ? "Start from a worked diagram, a controller and two pumps, and edit it to match your system."
      : "Lay out blocks in series and parallel and get the system's reliability.",
    cta: sampleRbdId ? "Open diagram" : "New diagram",
    short: "Build a block diagram",
  });
  return list;
}

function AgentLine() {
  const { mcp } = useAppConfig();
  if (!mcp) {
    return (
      <p className="first-run-agent">
        Work from Claude or another AI agent? The MCP connector is available on request: email{" "}
        <a href={`mailto:${MCP_CONTACT}`}>{MCP_CONTACT}</a>.
      </p>
    );
  }
  return (
    <p className="first-run-agent">
      Work from Claude or another AI agent?{" "}
      <a href="/api-docs/mcp" onClick={() => trackEvent("first_run_agent")}>
        Connect it over MCP
      </a>
    </p>
  );
}

// Home's "Start here" (#312): upload, paste, a sample, a
// diagram. ``info`` is the first-run state (useFirstRun): the starts for an
// empty workspace, or false once the user has work of their own — then the
// starts stay, without the first-run line and the agent line.
export function StartHere({ info, sampleModelId = null }) {
  if (info === null) return null;
  const first = !!info;
  const ids = first ? info : { sampleModelId, sampleRbdId: null };
  return (
    <section className="first-run" aria-labelledby="first-run-title">
      <h2 id="first-run-title">Start here</h2>
      {first && <p className="first-run-sub">Nothing saved yet. Pick one to get going.</p>}
      <div className="first-run-starts">
        {starts(ids, { upload: true }).map((s) => (
          <Link key={s.key} className="first-run-start" to={s.to} onClick={s.onClick}>
            <span className="first-run-ic">{s.icon}</span>
            <span className="first-run-start-body">
              <b>{s.title}</b>
              <span>{s.body}</span>
            </span>
            <span className="first-run-cta">{s.cta} →</span>
          </Link>
        ))}
      </div>
      <p className="first-run-more">
        Other models:{" "}
        <Link to="/modelling/recurrent/new">Recurrent events</Link> ·{" "}
        <Link to="/modelling/alt/new">Accelerated life</Link> ·{" "}
        <Link to="/modelling/degradation">Degradation</Link> ·{" "}
        <Link to="/modelling/joint/new">Condition monitoring</Link>
      </p>
      {first && (
        <p className="first-run-more">
          Show me how, on a sample:{" "}
          <ShowMeHow id="fit">Fit a model</ShowMeHow> ·{" "}
          <ShowMeHow id="replacement">Optimal replacement</ShowMeHow> ·{" "}
          <ShowMeHow id="rbd">Block diagram</ShowMeHow> ·{" "}
          <ShowMeHow id="rcm">RCM study</ShowMeHow> ·{" "}
          <ShowMeHow id="fleet">Fleet forecast</ShowMeHow>
        </p>
      )}
      {first && <AgentLine />}
    </section>
  );
}

// Home's compact version, once the workspace has work of its own: the same
// starts as one row of links.
export function StartHereCompact({ sampleModelId = null }) {
  return (
    <section className="first-run first-run-lite start-compact" aria-label="Start something new">
      <div className="first-run-lite-row">
        <span className="first-run-lite-label">Start something new</span>
        {starts({ sampleModelId, sampleRbdId: null }, { upload: true }).map((s) => (
          <Link key={s.key} className="first-run-chip" to={s.to} onClick={s.onClick}>
            {s.icon}
            {s.short || s.title}
          </Link>
        ))}
      </div>
    </section>
  );
}

// Activation metric: fire once, the moment a workspace shows its first
// life-data model of its own. localStorage-guarded so it reports a browser's
// first activation; storage that throws (private mode) just skips it.
const ACTIVATED_KEY = "reliafy_activated";
export function useActivation(rows) {
  const ownLife = (rows || []).some((r) => !r.is_sample && r.type === "life");
  useEffect(() => {
    if (!ownLife) return;
    try {
      if (localStorage.getItem(ACTIVATED_KEY) === "1") return;
      localStorage.setItem(ACTIVATED_KEY, "1");
    } catch {
      return;
    }
    trackEvent("activated");
  }, [ownLife]);
}
