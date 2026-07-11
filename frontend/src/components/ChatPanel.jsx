import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { SYSTEM_PROMPT, TOOLS, makeExecutor } from "../agent.js";
import { runTurn } from "../llm.js";
import { getAssistantInfo } from "../api.js";

const OPEN_KEY = "reliafy_chat_open";

const TOOL_LABEL = {
  list_datasets: "Looked up datasets",
  list_models: "Looked up models",
  list_distributions: "Looked up distributions",
  save_dataset: "Saved a dataset",
  create_model: "Created a model",
  list_rbds: "Looked up RBDs",
  get_current_rbd: "Read the diagram",
  set_current_rbd: "Updated the diagram",
  save_rbd: "Saved an RBD",
  validate_rbd: "Validated the diagram",
  navigate: "Opened a page",
};

// Users see AI usage as "credits", never dollars (1 credit == 1 cent internally).
const credits = (cents) => (cents || 0).toLocaleString();

// Right-side assistant. Runs on Reliafy's metered backend (no API key needed);
// usage is billed against the signed-in user's AI credit balance.
export default function ChatPanel() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(() => localStorage.getItem(OPEN_KEY) === "1");
  const [info, setInfo] = useState(null); // { enabled, provider, billing_enabled, credit_cents }
  const [balance, setBalance] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  const history = useRef([]);
  const scroller = useRef(null);
  const stopRef = useRef(false);

  const execute = useMemo(() => makeExecutor({ navigate }), [navigate]);

  useEffect(() => localStorage.setItem(OPEN_KEY, open ? "1" : "0"), [open]);

  // Load assistant config/balance once it's first opened.
  useEffect(() => {
    if (!open || info) return;
    getAssistantInfo()
      .then((d) => { setInfo(d); setBalance(d.credit_cents); })
      .catch(() => setInfo({ enabled: false }));
  }, [open, info]);

  useEffect(() => {
    if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight;
  }, [messages, busy, open]);

  const push = useCallback((m) => setMessages((xs) => [...xs, { key: `${Date.now()}-${Math.random()}`, ...m }]), []);

  const upsertTool = useCallback((evt) => {
    setMessages((xs) => {
      const i = xs.findIndex((m) => m.role === "tool" && m.toolId === evt.id);
      const ok = !(evt.result && evt.result.error);
      const node = {
        role: "tool", toolId: evt.id, name: evt.name, status: evt.status, ok,
        detail: evt.status === "done" && evt.result?.error ? String(evt.result.error) : "",
        key: i === -1 ? `t-${evt.id}` : xs[i].key,
      };
      if (i === -1) return [...xs, node];
      const next = xs.slice(); next[i] = node; return next;
    });
  }, []);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;
    let conf = info;
    if (!conf) {
      conf = await getAssistantInfo().catch(() => ({ enabled: false }));
      setInfo(conf); setBalance(conf.credit_cents);
    }
    if (!conf.enabled) {
      push({ role: "error", text: "The assistant isn't available yet." });
      return;
    }
    if (conf.billing_enabled && !conf.admin && (conf.credit_cents ?? 0) <= 0) {
      push({ role: "error", text: "You're out of AI credits.", action: "billing" });
      return;
    }

    setInput("");
    push({ role: "user", text });
    history.current.push({ role: "user", content: text });
    setBusy(true);
    stopRef.current = false;
    try {
      history.current = await runTurn({
        provider: conf.provider || "anthropic",
        system: SYSTEM_PROMPT,
        messages: history.current,
        tools: TOOLS,
        executeTool: execute,
        onText: (t) => push({ role: "assistant", text: t }),
        onTool: upsertTool,
        onBalance: (c) => setBalance(c),
        shouldStop: () => stopRef.current,
      });
    } catch (err) {
      if (err?.code === "no_credits" || err?.status === 402) {
        push({ role: "error", text: "You're out of AI credits.", action: "billing" });
      } else {
        push({ role: "error", text: String(err?.message || err) });
      }
    } finally {
      setBusy(false);
    }
  }, [input, busy, info, push, upsertTool, execute]);

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  const newChat = () => { stopRef.current = true; history.current = []; setMessages([]); setBusy(false); };

  if (!open) {
    return (
      <button className="chat-fab" onClick={() => setOpen(true)} title="Open the assistant">
        <ChatIcon /><span>Assistant</span>
      </button>
    );
  }

  const showBalance = info?.billing_enabled && !info?.admin; // operators aren't charged

  return (
    <aside className="chat-panel">
      <header className="chat-head">
        <div className="chat-title"><ChatIcon /><span>Assistant</span></div>
        <div className="chat-head-actions">
          {showBalance && (
            <button className="chat-balance" title="AI credits — click to top up" onClick={() => navigate("/billing")}>
              {credits(balance)} cr
            </button>
          )}
          <button className="chat-iconbtn" title="New chat" onClick={newChat}><NewIcon /></button>
          <button className="chat-iconbtn" title="Close" onClick={() => setOpen(false)}><CloseIcon /></button>
        </div>
      </header>

      <div className="chat-scroll" ref={scroller}>
        {messages.length === 0 && (
          <div className="chat-empty">
            {info && !info.enabled ? (
              <p>The AI assistant isn't available yet. Please check back soon.</p>
            ) : (
              <>
                <p>I can help with reliability engineering and act in Reliafy — fit models, build RBDs, run replacement and failure-finding calculations, track degradation and remaining useful life, and build evidence-linked RCM studies.</p>
                <div className="chat-suggest">
                  {[
                    "Fit a Weibull to the bearing sample",
                    "Build a 2-out-of-3 redundant sensor system",
                    "What does a Weibull beta below 1 mean?",
                  ].map((s) => <button key={s} onClick={() => setInput(s)}>{s}</button>)}
                </div>
                {showBalance && (
                  <p className="chat-credit-note">AI usage draws on your credit balance ({credits(balance)} credits). <button className="linkish" onClick={() => navigate("/billing")}>Manage credits</button></p>
                )}
              </>
            )}
          </div>
        )}

        {messages.map((m) => {
          if (m.role === "tool") {
            return (
              <div key={m.key} className={"chat-tool" + (m.status === "running" ? " running" : m.ok ? " ok" : " err")}>
                <span className="chat-tool-dot" />
                {TOOL_LABEL[m.name] || m.name}{m.status === "running" ? "…" : ""}{m.detail ? ` — ${m.detail}` : ""}
              </div>
            );
          }
          return (
            <div key={m.key} className={`chat-msg chat-${m.role}`}>
              {m.text}
              {m.action === "billing" && (
                <div><button className="chat-buybtn" onClick={() => navigate("/billing")}>Buy credits →</button></div>
              )}
            </div>
          );
        })}
        {busy && <div className="chat-typing"><span /><span /><span /></div>}
      </div>

      <div className="chat-input">
        <textarea
          rows={1}
          value={input}
          placeholder="Ask about reliability, or tell me to act…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
        />
        {busy ? (
          <button className="chat-send" onClick={() => { stopRef.current = true; }} title="Stop">■</button>
        ) : (
          <button className="chat-send" onClick={send} disabled={!input.trim()} title="Send"><SendIcon /></button>
        )}
      </div>
    </aside>
  );
}

const ChatIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 12a8 8 0 0 1-11.5 7.2L4 20l.8-5.5A8 8 0 1 1 21 12z" />
  </svg>
);
const NewIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 5v14M5 12h14" />
  </svg>
);
const CloseIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
);
const SendIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 12l16-8-6 16-3-7-7-1z" />
  </svg>
);
