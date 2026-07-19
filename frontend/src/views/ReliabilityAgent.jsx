import { useEffect, useRef, useState } from "react";
import {
  reliabilityAgentInfo,
  reliabilityAgentUpload,
  reliabilityAgentStream,
} from "../api.js";

// Proof-of-concept surface for the code-running Reliability Agent (Anthropic
// Managed Agents). Kept entirely separate from the existing sidebar assistant so
// it can grow (and the old assistant retire) independently. Upload a CSV, ask a
// question, and watch the agent run Python (with surpyval) in a managed sandbox,
// streamed step by step.

// One streamed event → a rendered block.
function EventBlock({ ev }) {
  if (ev.type === "text") return ev.text ? <p className="agent-text">{ev.text}</p> : null;
  if (ev.type === "tool_use") {
    return (
      <div className="agent-code">
        <div className="agent-code-h">{ev.name || "ran"}{ev.code ? " · code" : ""}</div>
        {ev.code
          ? <pre>{ev.code}</pre>
          : <pre>{JSON.stringify(ev.input, null, 2)}</pre>}
      </div>
    );
  }
  if (ev.type === "tool_result") {
    return ev.output ? (
      <div className="agent-result"><div className="agent-code-h">result</div><pre>{ev.output}</pre></div>
    ) : null;
  }
  if (ev.type === "custom_tool_use") {
    return <p className="agent-text"><em>calling {ev.name}…</em></p>;
  }
  if (ev.type === "status") {
    return <p className="agent-status">{ev.status.replace("session.status_", "")}</p>;
  }
  if (ev.type === "error") {
    return <div className="agent-result agent-err"><pre>{ev.detail}</pre></div>;
  }
  return null; // raw / done handled elsewhere
}

export default function ReliabilityAgent() {
  const [info, setInfo] = useState(null);
  const [events, setEvents] = useState([]); // streamed blocks for the current run
  const [input, setInput] = useState("");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [lastCost, setLastCost] = useState(null);
  const scrollRef = useRef(null);

  useEffect(() => { reliabilityAgentInfo().then(setInfo).catch((e) => setError(e.message)); }, []);
  useEffect(() => { scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight); }, [events]);

  const run = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    setLastCost(null);
    setEvents([{ type: "text", text: `You: ${text}` }]);
    try {
      let fileId = null;
      if (file) {
        setEvents((e) => [...e, { type: "status", status: `session.status_uploading ${file.name}` }]);
        fileId = (await reliabilityAgentUpload(file)).file_id;
      }
      await reliabilityAgentStream(text, fileId, {
        onEvent: (ev) => {
          if (ev.type === "done") {
            setLastCost({ cents: ev.cost_cents, credit: ev.credit_cents });
          } else {
            setEvents((e) => [...e, ev]);
          }
        },
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="app">
      <header>
        <div>
          <h1>Reliability Agent <span className="agent-poc">POC</span></h1>
          <p>
            {info?.enabled
              ? <>Runs Python (with surpyval) in a managed sandbox on your data. Model: <code>{info.model}</code>.</>
              : "Not configured yet — set ANTHROPIC_API_KEY on the server to enable."}
            {" "}Separate from the existing assistant, with its own metering.
          </p>
        </div>
        {lastCost && (
          <span className="muted-line" style={{ margin: 0 }}>
            Last run: {lastCost.cents} credit{lastCost.cents === 1 ? "" : "s"} · {lastCost.credit} left
          </span>
        )}
      </header>

      <div className="card note">
        POC (Anthropic Managed Agents, beta). Upload a CSV and ask the agent to
        explore or fit models — surpyval is installed in the sandbox. Saving back
        into Reliafy comes next.
      </div>

      <div className="card agent-chat" ref={scrollRef}>
        {events.length === 0 && !busy && (
          <p className="agent-empty">
            Upload a CSV of failure times (and a censoring column) and ask, e.g.
            “Fit the best distribution and report the parameters, MTTF and B10.”
          </p>
        )}
        {events.map((ev, i) => <EventBlock key={i} ev={ev} />)}
        {busy && <p className="agent-status">working…</p>}
      </div>

      {error && <div className="card error">{error}</div>}

      <div className="row" style={{ gap: "0.6rem", alignItems: "flex-end", marginTop: "0.6rem" }}>
        <label className="login-field" style={{ flex: 1 }}>
          <span>Message</span>
          <textarea
            rows={3}
            value={input}
            disabled={busy || !info?.enabled}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(); }}
            placeholder="Ask the agent to analyse your data… (⌘/Ctrl+Enter to send)"
          />
        </label>
        <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
          <label className="secondary agent-file" title={file ? file.name : "Attach a CSV"}>
            <input type="file" accept=".csv,text/csv" style={{ display: "none" }}
                   disabled={busy || !info?.enabled}
                   onChange={(e) => setFile(e.target.files?.[0] || null)} />
            {file ? `📎 ${file.name.slice(0, 16)}` : "Attach CSV"}
          </label>
          <button onClick={run} disabled={busy || !info?.enabled || !input.trim()}>
            {busy ? "Running…" : "Run"}
          </button>
        </div>
      </div>
    </div>
  );
}
