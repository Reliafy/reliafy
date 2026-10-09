import { Link } from "react-router-dom";
import { trackEvent } from "../telemetry.js";
import { PasteIcon, RbdIcon, UploadIcon, WaveIcon } from "./icons.jsx";
import { SAMPLE_MODEL } from "../firstRun.js";

// First-run starts (#194). Each start reports one client event (allowlisted in
// backend/routers/telemetry.py), so first actions can be counted against
// signups. ``upload`` (#312) is only on the Modelling home's "Start here".
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
    to: sampleRbdId ? `/rbds/b/${sampleRbdId}` : "/rbds/b",
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
  return (
    <p className="first-run-agent">
      Work from Claude or another AI agent?{" "}
      <a href="/api-docs#mcp" onClick={() => trackEvent("first_run_agent")}>
        Connect it over MCP
      </a>
    </p>
  );
}

// The Modelling home's "Start here" (#312): upload, paste, a sample, a
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
        <Link to="/modelling/degradation">Degradation</Link>
      </p>
      {first && <AgentLine />}
    </section>
  );
}

// The per-type pages' version: one compact row of the same starts, shown
// only while the workspace has nothing of its own.
export function FirstRunStrip({ info }) {
  if (!info) return null;
  return (
    <section className="first-run first-run-lite" aria-label="Get started">
      <div className="first-run-lite-row">
        <span className="first-run-lite-label">New here?</span>
        {starts(info).map((s) => (
          <Link key={s.key} className="first-run-chip" to={s.to} onClick={s.onClick}>
            {s.icon}
            {s.short}
          </Link>
        ))}
      </div>
      <AgentLine />
    </section>
  );
}
