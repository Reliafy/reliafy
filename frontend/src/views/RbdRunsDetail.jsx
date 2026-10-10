import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { downloadRbdRun, getRbdRun, rerunRbdRun } from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import Chip from "../components/ui/Chip.jsx";
import { ResultDetails } from "../components/ui/ResultSummary.jsx";
import { AvailabilityView } from "../components/RbdCalculator.jsx";
import { pctDigits } from "../components/availabilityPrecision.js";
import { unitInText } from "../components/unitText.js";
import { formatNumber } from "../format.js";
import { byText, jobStatusLine, runsPath, runtimeVsQuote, statusChip, viaText } from "../rbdRuns.js";
import "../components/RbdRuns.css";

const when = (iso) =>
  iso ? new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";

// "±0.012 points, within the target" / "not reached within the time budget".
function precisionText(p) {
  if (!p || p.half_width == null) return "—";
  const d = pctDigits(p.half_width);
  const half = `±${(p.half_width * 100).toFixed(d)} points (${Math.round((p.confidence || 0.95) * 100)}% interval)`;
  if (p.mode === "fixed") return `${half}, from a fixed number of replications`;
  if (p.mode === "quick") return `${half}, a quick estimate`;
  return p.reached ? `${half}, within the precision target` : `${half}; the target wasn't reached within the time budget`;
}

// One simulation run (#112): its stored results (the availability view, bands
// and all), what it ran on, the precision it reached; re-run or download it.
export default function RbdRunsDetail() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [run, setRun] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    let timer = null;
    setRun(null);
    setError(null);
    const load = () =>
      getRbdRun(runId)
        .then((r) => {
          if (!live) return;
          setRun(r);
          // Still queued or running: look again shortly.
          if (r.status === "queued" || r.status === "running") timer = setTimeout(load, 3000);
        })
        .catch((err) => live && setError(err.status === 404 ? "This run isn't there any more, or isn't yours." : err.message));
    load();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [runId]);

  const rerun = async () => {
    setBusy(true);
    setError(null);
    try {
      const out = await rerunRbdRun(runId);
      navigate(`/rbds/runs/${out.run_id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  const download = (format) => downloadRbdRun(runId, format).catch((err) => setError(err.message));

  if (!run) {
    return (
      <div className="app rbd-runs">
        <PageHeader crumbs={[{ label: "RBDs", to: "/rbds" }, { label: "Simulation runs", to: runsPath() }]} title="Simulation run" />
        {error ? <div className="card error">{error}</div> : <div className="card empty">Loading…</div>}
      </div>
    );
  }

  const inputs = run.inputs || {};
  const unit = inputs.unit || "";
  const u = unit ? ` ${unitInText(unit)}` : "";
  const chip = statusChip(run.status);
  const done = run.status === "done";
  const engines = [
    run.engines?.repyability && `RePyability ${run.engines.repyability}`,
    run.engines?.surpyval && `SurPyval ${run.engines.surpyval}`,
  ].filter(Boolean).join(" · ");
  const rows = [
    { label: "Ran", value: `${when(run.created_at)} · ${byText(run)}${run.via?.label ? ` in ${run.via.surface === "app" ? "the app" : run.via.label}` : ""}` },
    { label: "Where", value: run.where || "—" },
    { label: "Runtime", value: runtimeVsQuote(run) },
    { label: "Method", value: run.method.label },
    { label: "Window", value: inputs.window != null ? `${formatNumber(inputs.window)}${u}${inputs.window_chosen ? "" : " (automatic)"}${inputs.window_shortened ? ", shortened to keep it quick" : ""}` : "—" },
    { label: "Replications", value: inputs.replications != null ? inputs.replications.toLocaleString() : "—" },
    { label: "Precision", value: precisionText(run.precision) },
    { label: "Seed", value: inputs.seed ?? "—" },
    inputs.time_budget_s ? { label: "Time limit", value: `${formatNumber(inputs.time_budget_s)} s` } : null,
    { label: "Started from", value: inputs.current_state ? "The blocks' states then (as of now)" : "Every block new" },
    { label: "Diagram", value: `${inputs.blocks} blocks${inputs.diagram_changed_since ? ", changed since this run" : ""}` },
    { label: "Engines", value: engines || "Not recorded" },
  ];

  return (
    <div className="app rbd-runs">
      <PageHeader
        crumbs={[{ label: "RBDs", to: "/rbds" }, { label: "Simulation runs", to: runsPath(run.rbd_id) }]}
        title={run.rbd_name || "Simulation run"}
        badges={
          <>
            {!done && <Chip tone={chip.tone}>{chip.label}</Chip>}
            {run.method.key === "quick" && <Chip tone="warning">Quick estimate</Chip>}
          </>
        }
        meta={`${when(run.created_at)} · ${byText(run)} · ${viaText(run)} · ${runtimeVsQuote(run)}`}
        primary={
          <button type="button" onClick={rerun} disabled={busy}
                  title="Run the same inputs again: the diagram as it was then, its window and seed">
            {busy ? "Starting…" : "Re-run"}
          </button>
        }
        actions={run.rbd_id ? (
          <button type="button" className="secondary" onClick={() => navigate(`/rbds/b/${run.rbd_id}`)}>Open diagram</button>
        ) : null}
        menu={
          done ? (
            <>
              <button type="button" className="ovm-item" onClick={() => download("csv")}>Download CSV</button>
              <button type="button" className="ovm-item" onClick={() => download("json")}>Download JSON</button>
            </>
          ) : null
        }
        id={run.run_id}
      >
        {inputs.diagram_changed_since && (
          <p className="rbd-runs-note">The diagram has changed since this run. Re-run uses it as it was then.</p>
        )}
      </PageHeader>

      {error && <div className="card error">{error}</div>}

      {(run.status === "queued" || run.status === "running") && (
        <div className="card rbd-runs-pending" role="status" aria-live="polite">{jobStatusLine(run)}</div>
      )}
      {run.status === "failed" && <div className="card error">{run.error || "The calculation failed."}</div>}

      {done && run.result ? (
        <div className="card">
          <AvailabilityView result={run.result} unit={unit} />
          <ResultDetails summary="This run" rows={rows} />
        </div>
      ) : (
        <div className="card">
          <ResultDetails summary="This run" rows={rows} open />
        </div>
      )}
    </div>
  );
}
