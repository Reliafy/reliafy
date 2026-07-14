import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { distColor, relativeTime } from "../instrument.js";
import {
  listModels,
  deleteModel,
  listDegradationModels,
  deleteDegradationModel,
} from "../api.js";

const PlusIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 5v14M5 12h14" />
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

const distLabel = (d = "") => String(d).replace(/\s*\(.*$/, "").replace(/\s+PH$/, "");

// Every saved model — life-data and degradation — in one list. Rows link to
// the right detail page; the type-specific lists live under Life data models
// and Degradation models.
export default function AllModelsPage() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");

  const load = useCallback(() => {
    Promise.all([listModels(), listDegradationModels()])
      .then(([lm, dm]) => {
        const life = (lm.models || []).map((m) => ({
          id: m.id,
          name: m.name,
          type: "life",
          detail: distLabel(m.distribution) || "—",
          ph: m.kind === "regression",
          color: distColor(m.distribution),
          created_at: m.created_at,
          is_sample: m.is_sample,
          shared_by: m.shared_by,
          to: `/modelling/m/${m.id}`,
        }));
        const deg = (dm.models || []).map((m) => ({
          id: m.id,
          name: m.name,
          type: "degradation",
          detail: m.path_model || "—",
          ph: false,
          color: "#7c3aed",
          created_at: m.updated_at || m.created_at,
          is_sample: m.is_sample,
          shared_by: m.shared_by,
          to: `/modelling/degradation/${m.id}`,
        }));
        setRows([...life, ...deg].sort((a, b) => (a.created_at > b.created_at ? -1 : 1)));
      })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => load(), [load]);

  const onDelete = async (e, row) => {
    e.stopPropagation();
    const msg = row.is_sample
      ? `Remove the sample “${row.name}” from your workspace? It stays available to other users and you won't see it again.`
      : `Delete “${row.name}”?`;
    if (!window.confirm(msg)) return;
    try {
      if (row.type === "life") await deleteModel(row.id);
      else await deleteDegradationModel(row.id);
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  const loading = rows === null;
  const life = (rows || []).filter((r) => r.type === "life").length;
  const deg = (rows || []).filter((r) => r.type === "degradation").length;
  const visible = (rows || []).filter((r) => matches(query, r.name, r.detail));

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> / <b>Saved models</b>
          </div>
          <h1>Saved models</h1>
          <p>Every saved model — life-data and degradation — in one place.</p>
        </div>
        <div className="row" style={{ margin: 0 }}>
          <button onClick={() => navigate("/modelling/new")}>
            <PlusIcon /> New model
          </button>
        </div>
      </header>

      {error && <div className="card error">{error}</div>}

      {loading ? (
        <div className="card empty">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="card empty">
          <h2>No saved models</h2>
          <p>Fit a model and save it to see it here.</p>
        </div>
      ) : (
        <>
          <div className="stats">
            <div className="stat"><div className="k">Models</div><div className="v">{rows.length}</div></div>
            <div className="stat"><div className="k">Life data</div><div className="v">{life}</div></div>
            <div className="stat"><div className="k">Degradation</div><div className="v">{deg}</div></div>
          </div>

          <div className="tablebar">
            <span className="count">{visible.length} of {rows.length} models</span>
            <span className="grow" />
            <ListSearch value={query} onChange={setQuery} placeholder="Search models…" />
          </div>

          <div className="lib">
            <table className="lib-table">
              <thead>
                <tr>
                  <th style={{ width: "34%" }}>Model</th>
                  <th style={{ width: 130 }}>Type</th>
                  <th>Detail</th>
                  <th>Saved</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => (
                  <tr key={r.id} className="lib-row" onClick={() => navigate(r.to)}>
                    <td>
                      <div className="lib-name">
                        {r.name}
                        {r.is_sample && <span className="sample-tag">Sample</span>}
                        {r.shared_by && <span className="sample-tag shared" title={`Shared by ${r.shared_by}`}>Shared</span>}
                      </div>
                    </td>
                    <td>
                      <span className={"type-tag " + r.type}>
                        {r.type === "life" ? "Life data" : "Degradation"}
                      </span>
                    </td>
                    <td>
                      <span className="dpill">
                        <span className="dot" style={{ background: r.color }} />
                        {r.detail}
                        {r.ph && <span className="phflag">PH</span>}
                      </span>
                    </td>
                    <td className="lib-date">{relativeTime(r.created_at)}</td>
                    <td className="lib-actions">
                      <div className="lib-acts">
                        <button className="act" title="Open" onClick={(e) => { e.stopPropagation(); navigate(r.to); }}>
                          <OpenIcon />
                        </button>
                        <button className="act del" title="Delete" onClick={(e) => onDelete(e, r)}>
                          <TrashIcon />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
