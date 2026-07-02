import {
  distColor,
  seedFromString,
  reliabilityPath,
  relativeTime,
} from "../instrument.js";

const SearchIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.2-3.2" />
  </svg>
);
const FilterIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 5h18M6 12h12M10 19h4" />
  </svg>
);
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

// Strip the " PH"/parenthetical suffix from a distribution name for the pill.
const distLabel = (d = "") => String(d).replace(/\s*\(.*$/, "").replace(/\s+PH$/, "");

// Derive the four header figures from the live saved-model list.
function summarise(models) {
  const observations = models.reduce((s, m) => s + (m.n || 0), 0);
  const distributions = new Set(
    models.map((m) => String(m.distribution || "").split(/[\s(]/)[0])
  ).size;
  const latest = models.reduce(
    (a, m) => (a && a > m.created_at ? a : m.created_at),
    null
  );
  return {
    models: models.length,
    observations: observations.toLocaleString(),
    distributions,
    lastFit: latest ? relativeTime(latest) : "—",
  };
}

// List of saved models, rendered as the Instrument Models screen.
export default function ModelLibrary({ models, loading, onOpen, onDelete }) {
  if (loading) {
    return <div className="card empty">Loading…</div>;
  }
  if (!models.length) {
    return (
      <div className="card empty">
        <h2>No saved models</h2>
        <p>Fit a model and save it to see it here.</p>
      </div>
    );
  }

  const s = summarise(models);

  return (
    <>
      <div className="stats">
        <div className="stat"><div className="k">Saved models</div><div className="v">{s.models}</div></div>
        <div className="stat"><div className="k">Observations</div><div className="v">{s.observations}</div></div>
        <div className="stat"><div className="k">Distributions</div><div className="v">{s.distributions}</div></div>
        <div className="stat"><div className="k">Last fit</div><div className="v sm">{s.lastFit}</div></div>
      </div>

      <div className="tablebar">
        <span className="count">{models.length} models</span>
        <span className="grow" />
        <div className="search"><SearchIcon /><span>Search models…</span></div>
        <div className="chip"><FilterIcon /> All distributions</div>
      </div>

      <div className="lib">
        <table className="lib-table">
          <thead>
            <tr>
              <th style={{ width: "32%" }}>Model</th>
              <th>Distribution</th>
              <th style={{ width: 80 }}>n</th>
              <th style={{ width: 90 }}>R(t)</th>
              <th>Saved</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {models.map((m) => {
              const color = distColor(m.distribution);
              const seed = seedFromString(m.id || m.name);
              return (
                <tr key={m.id} className="lib-row" onClick={() => onOpen(m.id)}>
                  <td><div className="lib-name">{m.name}{m.is_sample && <span className="sample-tag">Sample</span>}</div></td>
                  <td>
                    <span className="dpill">
                      <span className="dot" style={{ background: color }} />
                      {distLabel(m.distribution)}
                      {m.kind === "regression" && <span className="phflag">PH</span>}
                    </span>
                  </td>
                  <td className="lib-n">{(m.n ?? 0).toLocaleString()}</td>
                  <td>
                    <svg className="lib-spark" width="72" height="26" viewBox="0 0 72 26">
                      <path d={reliabilityPath(72, 26, seed, 2)} fill="none" stroke={color} strokeWidth="1.6" />
                    </svg>
                  </td>
                  <td className="lib-date">{relativeTime(m.created_at)}</td>
                  <td className="lib-actions">
                    <div className="lib-acts">
                      <button className="act" title="Open" onClick={(e) => { e.stopPropagation(); onOpen(m.id); }}>
                        <OpenIcon />
                      </button>
                      <button className="act del" title="Delete" onClick={(e) => { e.stopPropagation(); onDelete(m); }}>
                        <TrashIcon />
                      </button>
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
