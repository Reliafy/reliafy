import { useEffect, useRef, useState } from "react";
import {
  reliabilityAgentInfo,
  reliabilityAgentUpload,
  reliabilityAgentStream,
} from "../api.js";
import { renderAgentMarkdown } from "../agentMarkdown.js";

// A conversational chat with the Reliability Agent (Anthropic Managed Agents).
// The agent assesses the task, builds the solution with surpyval/repyability in
// its sandbox, proposes a plan, and — after the user approves — calls Reliafy
// tools to load datasets + life models into the workspace. Messages persist in a
// scrolling thread; the session is reused across turns.

const TOOL_LABEL = { create_dataset: "Create dataset", create_life_model: "Create life model" };

// One streamed part within an agent turn. Conversational text is a message
// bubble; sandbox activity (bash/code + output) is a distinct collapsed "step"
// chip, so the agent's thinking is legible without a wall of code.
function Part({ p }) {
  if (p.type === "text")
    return p.text ? (
      <div
        className="chat-bubble agent md"
        dangerouslySetInnerHTML={{ __html: renderAgentMarkdown(p.text) }}
      />
    ) : null;
  if (p.type === "code")
    return (
      <details className="agent-step">
        <summary><span className="agent-step-k">$</span> {p.name || "ran code"}</summary>
        <pre>{p.code}</pre>
      </details>
    );
  if (p.type === "result")
    return (
      <details className="agent-step">
        <summary><span className="agent-step-k">»</span> output</summary>
        <pre>{p.output}</pre>
      </details>
    );
  // The agent invoking a Reliafy tool (the approved load), then its outcome.
  if (p.type === "tool_call")
    return <div className="agent-load">→ {TOOL_LABEL[p.name] || p.name}…</div>;
  if (p.type === "tool_done")
    return <div className={"agent-load done" + (p.ok ? "" : " err")}>{p.ok ? "✓ " : "✕ "}{p.summary}</div>;
  if (p.type === "error")
    return <div className="chat-error">{p.detail}</div>;
  return null;
}

function Bubble({ msg }) {
  if (msg.role === "user") {
    return (
      <div className="chat-row user">
        <div className="chat-bubble user">{msg.text}</div>
      </div>
    );
  }
  // The agent turn is a left-aligned stack of bubbles + step chips (not one card).
  return (
    <div className="chat-row agent">
      <div className="agent-stack">
        {msg.parts.length === 0 && msg.pending && <span className="chat-typing">Working…</span>}
        {msg.parts.map((p, i) => <Part key={i} p={p} />)}
        {msg.status && msg.pending && <span className="chat-status">{msg.status}…</span>}
      </div>
    </div>
  );
}

export default function ReliabilityAgent() {
  const [info, setInfo] = useState(null);
  const [messages, setMessages] = useState([]); // [{role, text} | {role:'agent', parts:[], status, pending}]
  const [input, setInput] = useState("");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [credit, setCredit] = useState(null);
  const sessionRef = useRef(null); // reused across turns
  const scrollRef = useRef(null);

  useEffect(() => {
    reliabilityAgentInfo().then((i) => { setInfo(i); setCredit(i.credit_cents); }).catch((e) => setError(e.message));
  }, []);
  useEffect(() => { scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight); }, [messages]);

  // Append a streamed part to the last (agent) message. Consecutive text parts
  // merge so the reply reads as one paragraph.
  const pushPart = (part) =>
    setMessages((ms) => {
      const last = ms[ms.length - 1];
      if (!last || last.role !== "agent") return ms;
      const parts = [...last.parts];
      const prev = parts[parts.length - 1];
      if (part.type === "text" && prev?.type === "text") {
        parts[parts.length - 1] = { ...prev, text: prev.text + part.text };
      } else {
        parts.push(part);
      }
      return [...ms.slice(0, -1), { ...last, parts }];
    });

  const setAgentStatus = (status) =>
    setMessages((ms) => {
      const last = ms[ms.length - 1];
      if (!last || last.role !== "agent") return ms;
      return [...ms.slice(0, -1), { ...last, status }];
    });

  const finishAgent = () =>
    setMessages((ms) => {
      const last = ms[ms.length - 1];
      if (!last || last.role !== "agent") return ms;
      return [...ms.slice(0, -1), { ...last, pending: false, status: null }];
    });

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    const attach = file;
    setFile(null);
    setInput("");
    setMessages((ms) => [
      ...ms,
      { role: "user", text: attach ? `${text}  📎 ${attach.name}` : text },
      { role: "agent", parts: [], status: null, pending: true },
    ]);
    try {
      let fileId = null;
      if (attach) {
        setAgentStatus("uploading");
        fileId = (await reliabilityAgentUpload(attach)).file_id;
      }
      await reliabilityAgentStream(text, {
        fileId,
        sessionId: sessionRef.current,
        onEvent: (ev) => {
          switch (ev.type) {
            case "text": pushPart({ type: "text", text: ev.text }); break;
            case "tool_use": pushPart({ type: "code", name: ev.name, code: ev.code || "" }); break;
            case "tool_result": pushPart({ type: "result", output: ev.output }); break;
            case "reliafy_tool": pushPart({ type: "tool_call", name: ev.name }); break;
            case "reliafy_tool_result": pushPart({ type: "tool_done", ok: ev.ok, summary: ev.summary }); break;
            case "status": setAgentStatus(ev.status); break;
            case "error": pushPart({ type: "error", detail: ev.detail }); break;
            case "done":
              if (ev.session_id) sessionRef.current = ev.session_id;
              if (ev.credit_cents != null) setCredit(ev.credit_cents);
              break;
            default: break;
          }
        },
      });
    } catch (e) {
      setError(e.message);
      pushPart({ type: "error", detail: e.message });
    } finally {
      finishAgent();
      setBusy(false);
    }
  };

  const disabled = busy || !info?.enabled;

  return (
    <div className="app agent-page">
      <header>
        <div>
          <h1>Reliability Agent <span className="agent-poc">POC</span></h1>
          <p>
            {info?.enabled
              ? <>Analyses your data with surpyval/repyability, proposes a plan, and — once you approve — loads datasets and life models into your workspace. Model: <code>{info.model}</code>.</>
              : "Not configured yet — set ANTHROPIC_API_KEY on the server to enable."}
          </p>
        </div>
        {credit != null && info?.billing_enabled && (
          <span className="muted-line" style={{ margin: 0 }}>{credit} credits</span>
        )}
      </header>

      <div className="chat" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="chat-empty">
            <p>Attach a CSV of failure data and ask, for example:</p>
            <ul>
              <li>“Fit the best distribution to these failure times and save it to my workspace.”</li>
              <li>“Clean this data, compare Weibull vs lognormal by AIC, and load the winner.”</li>
              <li>“This has a censoring column — fit a Weibull and save the dataset and model.”</li>
            </ul>
            <p className="muted-line">It proposes a plan and asks before creating anything.</p>
          </div>
        )}
        {messages.map((m, i) => <Bubble key={i} msg={m} />)}
      </div>

      {error && <div className="card error" style={{ marginTop: "0.6rem" }}>{error}</div>}

      <div className="chat-composer">
        <label className="chat-attach" title={file ? file.name : "Attach a CSV"}>
          <input type="file" accept=".csv,text/csv" style={{ display: "none" }}
                 disabled={disabled} onChange={(e) => setFile(e.target.files?.[0] || null)} />
          {file ? `📎 ${file.name.length > 18 ? file.name.slice(0, 16) + "…" : file.name}` : "📎"}
        </label>
        <textarea
          rows={1}
          value={input}
          disabled={disabled}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          placeholder={info?.enabled ? "Message the agent…  (Enter to send, Shift+Enter for newline)" : "Agent not configured"}
        />
        <button onClick={send} disabled={disabled || !input.trim()}>{busy ? "…" : "Send"}</button>
      </div>
    </div>
  );
}
