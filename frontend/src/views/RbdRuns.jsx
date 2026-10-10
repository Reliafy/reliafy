import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { listRbdRunDiagrams, listRbdRuns } from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import Chip from "../components/ui/Chip.jsx";
import { relativeTime } from "../instrument.js";
import { availabilityText, byText, runtimeText, statusChip, viaText } from "../rbdRuns.js";
import "../components/RbdRuns.css";

const MAX_COMPARE = 6;

// Simulation run history (#112): the user's availability simulations, newest
// first, from the app or any MCP connector — filter by diagram, open one, or
// tick a few finished ones to compare.
export default function RbdRuns() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const rbdId = params.get("rbd") || "";
  const [data, setData] = useState(null);
  const [diagrams, setDiagrams] = useState([]);
  const [error, setError] = useState(null);
  const [picked, setPicked] = useState([]);

  const load = useCallback(() => {
    setError(null);
    setData(null);
    listRbdRuns({ rbdId: rbdId || null })
      .then(setData)
      .catch((err) => setError(err.message));
  }, [rbdId]);

  useEffect(load, [load]);
  useEffect(() => {
    listRbdRunDiagrams().then((d) => setDiagrams(d.diagrams || [])).catch(() => {});
  }, []);
  // A run still going: look again in a few seconds.
  const active = (data?.runs || []).some((r) => r.status === "queued" || r.status === "running");
  useEffect(() => {
    if (!active) return undefined;
    const t = setTimeout(() => listRbdRuns({ rbdId: rbdId || null }).then(setData).catch(() => {}), 4000);
    return () => clearTimeout(t);
  }, [active, data, rbdId]);

  const runs = data?.runs || [];
  const diagram = diagrams.find((d) => d.rbd_id === rbdId);
  const toggle = (id) =>
    setPicked((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id].slice(-MAX_COMPARE)));
  const compare = () => navigate(`/rbds/runs/compare?ids=${picked.join(",")}`);

  return (
    <div className="app rbd-runs">
      <PageHeader
        crumbs={[{ label: "RBDs", to: "/rbds" }, ...(rbdId ? [{ label: diagram?.name || "Diagram", to: `/rbds/b/${rbdId}` }] : [])]}
        title="Simulation runs"
        meta={
          data
            ? `Availability simulations from the app and your connectors, kept ${data.kept_days} days.`
            : "Availability simulations from the app and your connectors."
        }
        primary={
          <button type="button" disabled={picked.length < 2} onClick={compare}
                  title={picked.length < 2 ? "Tick two or more finished runs" : undefined}>
            Compare{picked.length >= 2 ? ` ${picked.length} runs` : ""}
          </button>
        }
      />

      {error && <div className="card error">{error}</div>}

      <div className="tablebar">
        <label className="rbd-runs-filter">
          <span className="sr-only">Diagram</span>
          <select value={rbdId} onChange={(e) => {
            setPicked([]);
            setParams(e.target.value ? { rbd: e.target.value } : {});
          }}>
            <option value="">All diagrams</option>
            {diagrams.map((d) => (
              <option key={d.rbd_id} value={d.rbd_id}>{d.name}</option>
            ))}
            {rbdId && !diagram && <option value={rbdId}>This diagram</option>}
          </select>
        </label>
        <span className="grow" />
        {data && <span className="count">{runs.length}{data.more ? "+" : ""} run{runs.length === 1 ? "" : "s"}</span>}
      </div>

      {data === null && !error ? (
        <div className="card empty">Loading…</div>
      ) : runs.length === 0 && !error ? (
        <div className="card empty">
          <h2>No simulation runs yet</h2>
          <p>Run a simulation from a repairable diagram&rsquo;s Calculator tab to see it here.</p>
          {rbdId && <p><Link to={`/rbds/b/${rbdId}`}>Open the diagram</Link></p>}
        </div>
      ) : (
        <div className="lib">
          <table className="lib-table rbd-runs-table">
            <thead>
              <tr>
                <th className="rbd-runs-pick"><span className="sr-only">Compare</span></th>
                <th>When</th>
                {!rbdId && <th>Diagram</th>}
                <th>Availability over the window</th>
                <th className="lib-opt">Method</th>
                <th className="lib-opt">Runtime</th>
                <th className="lib-opt">Ran by</th>
                <th><span className="sr-only">Status</span></th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                const a = availabilityText(r.availability);
                const chip = statusChip(r.status);
                return (
                  <tr key={r.run_id} className="lib-row" onClick={() => navigate(`/rbds/runs/${r.run_id}`)}>
                    <td className="rbd-runs-pick" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label="Compare this run"
                        disabled={r.status !== "done"}
                        checked={picked.includes(r.run_id)}
                        onChange={() => toggle(r.run_id)}
                      />
                    </td>
                    <td className="lib-date" title={r.created_at ? new Date(r.created_at).toLocaleString() : ""}>
                      {relativeTime(r.created_at)}
                    </td>
                    {!rbdId && <td className="rbd-runs-name">{r.rbd_name || "Unsaved diagram"}</td>}
                    <td className="lib-n">
                      {a.value}
                      {a.interval && <span className="rbd-runs-ci"> {a.interval}</span>}
                    </td>
                    <td className="lib-opt">{r.method.label}</td>
                    <td className="lib-opt lib-n">{runtimeText(r.runtime_s)}</td>
                    <td className="lib-opt">
                      {byText(r)}
                      <span className="rbd-runs-via"> · {viaText(r)}</span>
                    </td>
                    <td className="lib-actions">
                      {r.status !== "done" && <Chip tone={chip.tone}>{chip.label}</Chip>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
