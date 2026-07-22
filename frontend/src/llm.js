// Client side of the assistant loop. Each model round-trip goes through our
// metered backend proxy (api.js -> /api/assistant/step) on the operator's key —
// the browser never holds a provider key. Tools still execute in the browser;
// this just drives the loop. The server picks the provider, so the caller passes
// `provider` (from /api/assistant/info) only so we shape messages/tool results
// the way that provider expects.
import { assistantStep, assistantStepStream } from "./api.js";

const MAX_STEPS = 8; // safety cap on tool round-trips per user message

// Drive one user message to completion. Callbacks:
//   onText(text), onTool({id,name,input,status,result}), onBalance(credit_cents)
//   shouldStop() -> true to stop the loop between steps
// Returns the updated native message history.
export async function runTurn(opts) {
  return opts.provider === "anthropic" ? runAnthropic(opts) : runOpenAI(opts);
}

async function runAnthropic({ system, messages, tools, executeTool, onText, onTool, onBalance, shouldStop }) {
  let msgs = [...messages];
  for (let step = 0; step < MAX_STEPS; step++) {
    if (shouldStop?.()) return msgs;
    const res = await assistantStep(system, msgs, tools);
    onBalance?.(res.credit_cents);
    const message = res.message;
    msgs.push(message);

    const content = message.content || [];
    const text = content.filter((c) => c.type === "text").map((c) => c.text).join("");
    if (text) onText(text);

    const toolUses = content.filter((c) => c.type === "tool_use");
    if (res.stop_reason !== "tool_use" || toolUses.length === 0) return msgs;

    const results = [];
    for (const tu of toolUses) {
      const result = await runTool(executeTool, onTool, tu.name, tu.input);
      results.push({ type: "tool_result", tool_use_id: tu.id, content: JSON.stringify(result) });
    }
    msgs.push({ role: "user", content: results });
  }
  onText("(Stopped after too many tool steps.)");
  return msgs;
}

// OpenAI Responses API. `msgs` is a flat list of Responses *input items*: the
// first user turn (`{role:"user", content}`), then the raw `output` items the
// server returns each step (assistant message / function_call / reasoning),
// with a `function_call_output` item spliced in after each tool runs. The
// server (backend/services/assistant.py:_openai) returns `res.message` as that
// output-item array; we append it verbatim and resend everything next step.
async function runOpenAI({ system, messages, tools, executeTool, onText, onDelta, onTool, onBalance, onStreamEnd, shouldStop }) {
  let msgs = [...messages];
  for (let step = 0; step < MAX_STEPS; step++) {
    if (shouldStop?.()) return msgs;
    // Assistant text streams in via onDelta; the resolved payload carries the
    // full output items (message/function_call/reasoning) to continue the loop.
    const res = await assistantStepStream(system, msgs, tools, { onDelta: (t) => onDelta?.(t) });
    onBalance?.(res.credit_cents);
    onStreamEnd?.(); // close the live text bubble; tool chips / next step start fresh
    const output = Array.isArray(res.message) ? res.message : [];
    msgs.push(...output);

    const calls = output.filter((it) => it.type === "function_call");
    if (calls.length === 0) return msgs;

    for (const call of calls) {
      let args = {};
      try { args = JSON.parse(call.arguments || "{}"); } catch { args = {}; }
      const result = await runTool(executeTool, onTool, call.name, args);
      msgs.push({ type: "function_call_output", call_id: call.call_id, output: JSON.stringify(result) });
    }
  }
  onText("(Stopped after too many tool steps.)");
  return msgs;
}

let toolSeq = 0;
async function runTool(executeTool, onTool, name, input) {
  const id = ++toolSeq;
  onTool?.({ id, name, input, status: "running" });
  let result;
  try {
    result = await executeTool(name, input);
  } catch (err) {
    result = { error: String(err?.message || err) };
  }
  onTool?.({ id, name, input, status: "done", result });
  return result;
}
