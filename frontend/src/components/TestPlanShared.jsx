// Pieces the Test planning tabs share: a number field, the run-and-show
// hook, the answer card, the assumptions list and the simulation check (Pro).
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { getRbdJob, simulateTestPlan, testPlan } from "../api.js";
import { percentApiMessage } from "../percent.js";

export function Field({ label, value, onChange, type = "number", ...props }) {
  return (
    <label className="calc-t">
      <span>{label}</span>
      <input
        type={type}
        step={type === "number" ? "any" : undefined}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        {...props}
      />
    </label>
  );
}

export function Choice({ label, value, onChange, options }) {
  return (
    <label className="calc-t">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {Object.entries(options).map(([v, text]) => (
          <option key={v} value={v}>{text}</option>
        ))}
      </select>
    </label>
  );
}

// Run one calculator: the answer for the latest inputs (an older answer that
// arrives late is dropped).
export function usePlan(kind) {
  const [result, setResult] = useState(null);
  const [inputs, setInputs] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const ticket = useRef(0);
  const run = async (body) => {
    const mine = ++ticket.current;
    setLoading(true);
    setError(null);
    try {
      const out = await testPlan(kind, body);
      if (mine !== ticket.current) return;
      setResult(out);
      setInputs(body);
    } catch (e) {
      if (mine !== ticket.current) return;
      setError(percentApiMessage(e.message));
      setResult(null);
      setInputs(null);
    } finally {
      if (mine === ticket.current) setLoading(false);
    }
  };
  return { result, inputs, error, loading, run };
}

export function ComputeButton({ loading, onClick }) {
  return (
    <button type="button" onClick={onClick} disabled={loading}>
      {loading ? "Computing…" : "Compute"}
    </button>
  );
}

// The answer first: the plan in plain words, then up to four figures.
export function PlanAnswer({ result, stats, tone = "neutral", note = null }) {
  return (
    <ResultSummary tone={tone} sentence={result.summary} stats={stats}>
      {note}
    </ResultSummary>
  );
}

export function Assumptions({ items, children = null, rows = [] }) {
  return (
    <ResultDetails rows={rows}>
      {children}
      {items?.length > 0 && (
        <>
          <h3 className="demo-h">Assumptions</h3>
          <ul className="demo-assumptions">
            {items.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </>
      )}
    </ResultDetails>
  );
}

const POLL_FIRST_MS = 1500;
const POLL_MAX_MS = 6000;

function jobText(job) {
  if (job.status === "running") return "Simulating the test…";
  const ahead = job.queue_position;
  return ahead ? `Queued for the calculation service (${ahead} ahead)…` : "Queued for the calculation service…";
}

// Check a life or accelerated test plan by simulating it (Pro): the
// precision above is a large-sample approximation, which can flatter a test
// with few failures. Runs as a compute job when the service has a queue.
export function SimulationCheck({ kind, inputs }) {
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState(null);
  const [out, setOut] = useState(null);
  const [error, setError] = useState(null);
  const [needsPro, setNeedsPro] = useState(false);
  const key = JSON.stringify(inputs);

  useEffect(() => {
    setOut(null); setJob(null); setError(null); setNeedsPro(false); setBusy(false);
  }, [key]);

  const start = async () => {
    setBusy(true); setError(null); setOut(null); setNeedsPro(false);
    try {
      const res = await simulateTestPlan(kind, inputs);
      if (res.job) { setJob(res.job); return; }
      setOut(res); setBusy(false);
    } catch (e) {
      setBusy(false);
      if (e.status === 402 && e.code === "pro_required") setNeedsPro(true);
      else setError(percentApiMessage(e.message));
    }
  };

  const jobId = job?.job_id;
  useEffect(() => {
    if (!jobId) return undefined;
    let cancelled = false;
    let timer = null;
    let delay = POLL_FIRST_MS;
    let failures = 0;
    const poll = async () => {
      try {
        const view = await getRbdJob(jobId);
        if (cancelled) return;
        failures = 0;
        if (view.status === "done") { setJob(null); setOut(view.result); setBusy(false); return; }
        if (view.status === "failed") {
          setJob(null); setBusy(false); setError(view.error || "The simulation failed."); return;
        }
        setJob((prev) => (prev && prev.job_id === jobId ? { ...prev, ...view } : prev));
      } catch (err) {
        if (cancelled) return;
        if (err.status === 404 || ++failures >= 6) {
          setJob(null); setBusy(false);
          setError(err.status === 404 ? "The simulation was lost: run it again." : err.message);
          return;
        }
      }
      delay = Math.min(delay * 1.3, POLL_MAX_MS);
      timer = setTimeout(poll, delay);
    };
    timer = setTimeout(poll, POLL_FIRST_MS);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [jobId]);

  return (
    <div className="tp-sim">
      <h3 className="demo-h">Check it by simulation</h3>
      <p className="rs-note">
        The precision above is an approximation that holds for large tests. To see how this exact test would do,
        simulate it hundreds of times, fit each result, and look at how far the estimates spread.
      </p>
      <button type="button" className="secondary" onClick={start} disabled={busy}>
        {busy ? "Simulating…" : "Simulate this test (Pro)"}
      </button>
      {busy && job && <p className="hint" role="status" aria-live="polite">{jobText(job)}</p>}
      {needsPro && (
        <div className="card note" role="status">
          <p style={{ margin: 0 }}>
            <b>Checking by simulation is part of Pro.</b> It fits the model to hundreds of simulated tests on
            Reliafy&apos;s calculation service. Every plan on this page is free.
          </p>
          <div className="rbd-upgrade-actions"><Link className="cta cta-solid" to="/billing">Upgrade to Pro</Link></div>
        </div>
      )}
      {error && <div className="calc-warn">{error}</div>}
      {out && <p className="tp-sim-out" role="status">{out.summary}</p>}
    </div>
  );
}
