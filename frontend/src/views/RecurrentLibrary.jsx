import { useState } from "react";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { seedFromString, reliabilityPath, relativeTime } from "../instrument.js";

const OpenIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M7 17 17 7M9 7h8v8" />
  </svg>
);
const TrashIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13" />
  </svg>
);

// Growth verdict → pill colour, mirroring the model-list distribution pill.
const GROWTH = {
  improving: { label: "Improving", color: "#2faa6a" },
  stable: { label: "Stable", color: "#6c727c" },
  deteriorating: { label: "Deteriorating", color: "#d05a5a" },
};

function summarise(models) {
  const systems = models.reduce((s, m) => s + (m.n_systems || 0), 0);
  const events = models.reduce((s, m) => s + (m.n_events || 0), 0);
  const latest = models.reduce((a, m) => (a && a > m.created_at ? a : m.created_at), null);
  return {
    models: models.length,
    systems: systems.toLocaleString(),
    events: events.toLocaleString(),
    lastFit: latest ? relativeTime(latest) : "—",
  };
}

// Saved recurrent-event models, rendered like the life-data model library.
export default function RecurrentLibrary({ models, loading, onOpen, onDelete }) {
  const [query, setQuery] = useState("");
  if (loading) return <div className="card empty">Loading…</div>;
  if (!models.length) {
    return (
      <div className="card empty">
        <h2>No saved models</h2>
        <p>Fit a recurrent model and save it to see it here.</p>
      </div>
    );
  }

  const s = summarise(models);
  const visible = models.filter((m) => matches(query, m.name, m.model, m.growth));

  return (
    <>
      <div className="stats">
        <div className="stat"><div className="k">Saved models</div><div className="v">{s.models}</div></div>
        <div className="stat"><div className="k">Systems</div><div className="v">{s.systems}</div></div>
        <div className="stat"><div className="k">Failures</div><div className="v">{s.events}</div></div>
        <div className="stat"><div className="k">Last fit</div><div className="v sm">{s.lastFit}</div></div>
      </div>

      <div className="tablebar">
        <span className="count">{visible.length} of {models.length} models</span>
        <span className="grow" />
        <ListSearch value={query} onChange={setQuery} placeholder="Search models…" />
      </div>

      <div className="lib">
        <table className="lib-table">
          <thead>
            <tr>
              <th style={{ width: "32%" }}>Model</th>
              <th>Growth</th>
              <th style={{ width: 90 }}>Systems</th>
              <th style={{ width: 90 }}>MCF</th>
              <th>Saved</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {visible.map((m) => {
              const g = GROWTH[m.growth] || { label: m.growth || "—", color: "#6c727c" };
              const seed = seedFromString(m.id || m.name);
              return (
                <tr key={m.id} className="lib-row" onClick={() => onOpen(m.id)}>
                  <td>
                    <div className="lib-name">
                      {m.name}
                      {m.is_sample && <span className="sample-tag">Sample</span>}
                      {m.shared_by && <span className="sample-tag shared" title={`Shared by ${m.shared_by}`}>Shared</span>}
                    </div>
                  </td>
                  <td>
                    <span className="dpill">
                      <span className="dot" style={{ background: g.color }} />
                      {g.label}
                    </span>
                  </td>
                  <td className="lib-n">{(m.n_systems ?? 0).toLocaleString()}</td>
                  <td>
                    {/* Cumulative-failures spark rises left→right (invert the reliability curve). */}
                    <svg className="lib-spark" width="72" height="26" viewBox="0 0 72 26" style={{ transform: "scaleY(-1)" }}>
                      <path d={reliabilityPath(72, 26, seed, 2)} fill="none" stroke={g.color} strokeWidth="1.6" />
                    </svg>
                  </td>
                  <td className="lib-date">{relativeTime(m.created_at)}</td>
                  <td className="lib-actions">
                    <div className="lib-acts">
                      <button className="act" title="Open" onClick={(e) => { e.stopPropagation(); onOpen(m.id); }}>
                        <OpenIcon />
                      </button>
                      {!m.read_only && (
                        <button className="act del" title="Delete" onClick={(e) => { e.stopPropagation(); onDelete(m); }}>
                          <TrashIcon />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
