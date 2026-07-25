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

const ALT_COLOR = "#0f9ab0";

function summarise(models) {
  const obs = models.reduce((s, m) => s + (m.n || 0), 0);
  const laws = new Set(models.map((m) => m.life_model).filter(Boolean)).size;
  const latest = models.reduce((a, m) => (a && a > m.created_at ? a : m.created_at), null);
  return {
    models: models.length,
    observations: obs.toLocaleString(),
    laws,
    lastFit: latest ? relativeTime(latest) : "—",
  };
}

// Saved accelerated-life models, rendered like the life-data and recurrent
// libraries: stats strip, search, then the table.
export default function AltLibrary({ models, loading, onOpen, onDelete }) {
  const [query, setQuery] = useState("");
  if (loading) return <div className="card empty">Loading…</div>;
  if (!models.length) {
    return (
      <div className="card empty">
        <h2>No saved models</h2>
        <p>Fit an accelerated-life model and save it to see it here.</p>
      </div>
    );
  }

  const s = summarise(models);
  const visible = models.filter((m) =>
    matches(query, m.name, m.distribution, m.life_model, m.id)
  );

  return (
    <>
      <div className="stats">
        <div className="stat"><div className="k">Saved models</div><div className="v">{s.models}</div></div>
        <div className="stat"><div className="k">Observations</div><div className="v">{s.observations}</div></div>
        <div className="stat"><div className="k">Life-stress laws</div><div className="v">{s.laws}</div></div>
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
              <th style={{ width: "30%" }}>Model</th>
              <th>Life–stress</th>
              <th style={{ width: 80 }}>Stresses</th>
              <th style={{ width: 70 }}>n</th>
              <th style={{ width: 90 }}>Life</th>
              <th>Saved</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {visible.map((m) => {
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
                      <span className="dot" style={{ background: ALT_COLOR }} />
                      {[m.distribution, m.life_model].filter(Boolean).join(" · ") || "—"}
                    </span>
                  </td>
                  <td className="lib-n">{m.n_stresses ?? 1}</td>
                  <td className="lib-n">{(m.n ?? 0).toLocaleString()}</td>
                  <td>
                    {/* Characteristic life falls as stress rises — a declining spark. */}
                    <svg className="lib-spark" width="72" height="26" viewBox="0 0 72 26">
                      <path d={reliabilityPath(72, 26, seed, 2)} fill="none" stroke={ALT_COLOR} strokeWidth="1.6" />
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
