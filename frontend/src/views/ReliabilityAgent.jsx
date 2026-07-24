import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  reliabilityAgentInfo,
  reliabilityAgentUpload,
  reliabilityAgentStream,
  listAgentSessions,
  getAgentSession,
} from "../api.js";
import { renderAgentMarkdown } from "../agentMarkdown.js";
import { relativeTime } from "../instrument.js";

// A conversational chat with the Reliability Agent (Anthropic Managed Agents).
// The agent assesses the task, builds the solution with surpyval/repyability in
// its sandbox, proposes a plan, and — after the user approves — calls Reliafy
// tools to load datasets + life models into the workspace. Messages persist in a
// scrolling thread; the session is reused across turns.

const TOOL_LABEL = { create_dataset: "Create dataset", create_life_model: "Create life model", create_rbd: "Create RBD" };

// A compact summary of the held create-tool calls awaiting approval, e.g.
// "2 datasets, 1 model". Drives the Approve button label.
const PENDING_NOUN = { create_dataset: "dataset", create_life_model: "model", create_rbd: "RBD" };
function summarizePending(pending) {
  const counts = {};
  for (const p of pending) counts[p.name] = (counts[p.name] || 0) + 1;
  return Object.entries(counts)
    .map(([name, n]) => `${n} ${PENDING_NOUN[name] || name}${n === 1 ? "" : "s"}`)
    .join(", ");
}

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
  if (p.type === "tool_blocked")
    return <div className="agent-load blocked">⏸ {TOOL_LABEL[p.name] || p.name} — needs your approval</div>;
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
  const navigate = useNavigate();
  const [info, setInfo] = useState(null);
  const [messages, setMessages] = useState([]); // [{role, text} | {role:'agent', parts:[], status, pending}]
  const [input, setInput] = useState("");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [credit, setCredit] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [showHistory, setShowHistory] = useState(false);
  const [loadingTx, setLoadingTx] = useState(false);
  const sessionRef = useRef(null); // reused across turns
  const scrollRef = useRef(null);

  const refreshSessions = () =>
    listAgentSessions().then((r) => setSessions(r.sessions || [])).catch(() => {});

  useEffect(() => {
    reliabilityAgentInfo().then((i) => { setInfo(i); setCredit(i.credit_cents); }).catch((e) => setError(e.message));
    refreshSessions();
  }, []);

  // Start a fresh conversation (new session on the next message).
  const newChat = () => {
    if (busy) return;
    sessionRef.current = null;
    setMessages([]);
    setError(null);
    setShowHistory(false);
  };

  // Reopen a past run: load its transcript and point the session at it so the
  // next message resumes the same conversation on the platform.
  const openSession = async (id) => {
    if (busy) return;
    setShowHistory(false);
    setLoadingTx(true);
    setError(null);
    try {
      const tx = await getAgentSession(id);
      setMessages(tx.messages || []);
      sessionRef.current = id;
    } catch (e) {
      setError(e.message);
    } finally {
      setLoadingTx(false);
    }
  };
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

  // Run one turn. `approved` arms the create tools for this turn only (the
  // "Approve & run" button); a normal Send is never approved, so the agent can
  // only propose and ask.
  const runTurn = async (text, { attach = null, approved = false } = {}) => {
    if (!text || busy) return;
    setBusy(true);
    setError(null);
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
        approved,
        sessionId: sessionRef.current,
        onEvent: (ev) => {
          switch (ev.type) {
            case "text": pushPart({ type: "text", text: ev.text }); break;
            case "tool_use": pushPart({ type: "code", name: ev.name, code: ev.code || "" }); break;
            case "tool_result": pushPart({ type: "result", output: ev.output }); break;
            case "reliafy_tool": pushPart({ type: "tool_call", name: ev.name }); break;
            case "reliafy_tool_blocked": pushPart({ type: "tool_blocked", name: ev.name }); break;
            case "reliafy_tool_result": pushPart({ type: "tool_done", ok: ev.ok, summary: ev.summary }); break;
            case "status": setAgentStatus(ev.status); break;
            case "error": pushPart({ type: "error", detail: ev.detail }); break;
            case "done":
              if (ev.session_id) sessionRef.current = ev.session_id;
              if (ev.credit_cents != null) setCredit(ev.credit_cents);
              refreshSessions();  // keep the history list current
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

  const send = () => {
    const text = input.trim();
    if (!text) return;
    const attach = file;
    setFile(null);
    setInput("");
    runTurn(text, { attach });
  };

  const approve = () => runTurn("Approved — go ahead with the plan.", { approved: true });

  // Pro-only feature: free tier is locked out (server enforces it too).
  const upgradeRequired = !!info?.enabled && info?.upgrade_required;
  const disabled = busy || !info?.enabled || upgradeRequired;
  // Offer the greenlight ONLY when the agent has actually proposed actions and
  // is waiting — i.e. its last turn holds create-tool calls pending approval.
  // (Not a standing button after every agent message.)
  const lastMsg = messages[messages.length - 1];
  const pending = lastMsg?.role === "agent" && !lastMsg.pending
    ? lastMsg.parts.filter((p) => p.type === "tool_blocked")
    : [];
  const canApprove = !disabled && pending.length > 0;
  const pendingSummary = summarizePending(pending);

  return (
    <div className="app agent-page">
      <header>
        <div>
          <h1>Reliability Agent <span className="agent-poc">POC</span></h1>
          {!info?.enabled && (
            <p className="muted-line" style={{ margin: 0 }}>
              Not configured yet — set ANTHROPIC_API_KEY on the server to enable.
            </p>
          )}
        </div>
        <div className="row" style={{ margin: 0, gap: "0.6rem", alignItems: "center" }}>
          {credit != null && info?.billing_enabled && (
            <span className="muted-line" style={{ margin: 0 }}>{credit} credits</span>
          )}
          {info?.enabled && (
            <>
              <button className="secondary" onClick={newChat} disabled={busy}>New chat</button>
              <div className="agent-hist-wrap">
                <button className="secondary" onClick={() => { setShowHistory((s) => !s); refreshSessions(); }}>
                  History {sessions.length > 0 ? `(${sessions.length})` : ""}
                </button>
                {showHistory && (
                  <div className="agent-hist">
                    {sessions.length === 0 ? (
                      <div className="agent-hist-empty">No past runs yet.</div>
                    ) : (
                      sessions.map((s) => (
                        <button key={s.id} className="agent-hist-row" onClick={() => openSession(s.id)}
                                title={s.title}>
                          <span className="agent-hist-title">{s.title}</span>
                          <span className="agent-hist-meta">
                            {relativeTime(s.updated_at)} · {s.turns} turn{s.turns === 1 ? "" : "s"}
                          </span>
                        </button>
                      ))
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </header>

      {upgradeRequired && (
        <div className="card agent-upgrade">
          <strong>The Reliability Agent is a paid feature.</strong>
          <p className="muted-line" style={{ margin: "0.35rem 0 0.7rem" }}>
            It runs Python (surpyval/repyability) in a managed sandbox to build and save models
            for you. Subscribe to Pro or buy AI credits to use it — the everyday assistant stays free.
          </p>
          <button className="chat-approve-btn" onClick={() => navigate("/billing")}>Get Pro or credits →</button>
        </div>
      )}

      <div className="chat" ref={scrollRef}>
        {loadingTx && <div className="chat-empty"><p className="chat-empty-head">Loading conversation…</p></div>}
        {info?.enabled && messages.length === 0 && !upgradeRequired && !loadingTx && (
          <div className="chat-empty">
            <p className="chat-empty-head">Tell me what to build — attach data if you have it.</p>
          </div>
        )}
        {messages.map((m, i) => <Bubble key={i} msg={m} />)}
      </div>

      {error && <div className="card error" style={{ marginTop: "0.6rem" }}>{error}</div>}

      {canApprove && (
        <div className="chat-approve">
          <button className="chat-approve-btn" onClick={approve}>
            ✓ Approve &amp; build{pendingSummary ? ` — ${pendingSummary}` : ""}
          </button>
          <span className="muted-line" style={{ margin: 0 }}>
            The agent is asking to proceed. Approve to run it, or keep typing to change the plan.
          </span>
        </div>
      )}

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
          placeholder={
            upgradeRequired
              ? "Get Pro or buy AI credits to use the Reliability Agent"
              : info?.enabled
                ? "Message the agent…  (Enter to send, Shift+Enter for newline)"
                : "Agent not configured"
          }
        />
        <button onClick={send} disabled={disabled || !input.trim()}>{busy ? "…" : "Send"}</button>
      </div>
    </div>
  );
}
