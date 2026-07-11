import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { listDatasets, uploadDataset, deleteDataset } from "../api.js";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { relativeTime } from "../instrument.js";

const UploadIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 16V4m0 0 4 4m-4-4-4 4" />
    <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
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
const FileIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 3v5h5M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" />
  </svg>
);

function summarise(datasets) {
  const rows = datasets.reduce((s, d) => s + (d.n_rows || 0), 0);
  const linked = datasets.reduce((s, d) => s + (d.n_models || 0), 0);
  const latest = datasets.reduce((a, d) => (a && a > d.created_at ? a : d.created_at), null);
  return {
    datasets: datasets.length,
    rows: rows.toLocaleString(),
    linked,
    lastAdded: latest ? relativeTime(latest) : "—",
  };
}

// Landing page for the Datasets section: list uploaded CSVs, upload new, open
// or delete. Datasets are content-addressed, so re-uploading a file reuses it.
export default function DatasetsHome() {
  const navigate = useNavigate();
  const location = useLocation();
  const [datasets, setDatasets] = useState(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState(null);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef(null);

  // Open the file picker directly when arriving from the dashboard "Upload" card.
  useEffect(() => {
    if (location.state?.openUpload) {
      window.history.replaceState({}, "");
      inputRef.current?.click();
    }
  }, [location.state]);

  const refresh = useCallback(() => {
    listDatasets()
      .then((d) => setDatasets(d.datasets))
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => refresh(), [refresh]);

  const onPick = async (file) => {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const ds = await uploadDataset(file);
      await refresh();
      navigate(`/datasets/d/${ds.id}`);
    } catch (e) {
      setError(e.message);
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const onDelete = async (e, d) => {
    e.stopPropagation();
    const msg = d.is_sample
      ? `Remove the sample “${d.name}” from your workspace? It stays available to other users and you won't see it again.`
      : `Delete dataset “${d.name}”?`;
    if (!window.confirm(msg)) return;
    try {
      await deleteDataset(d.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const open = (id) => navigate(`/datasets/d/${id}`);
  const loading = datasets === null;
  const s = !loading ? summarise(datasets) : null;

  return (
    <div className="app">
      <input
        ref={inputRef}
        type="file"
        accept=".csv,text/csv"
        hidden
        onChange={(e) => onPick(e.target.files?.[0])}
      />
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/datasets")}>Datasets</button> / <b>Uploaded files</b>
          </div>
          <h1>Datasets</h1>
          <p>
            Uploaded CSVs, stored once and shared across the models fitted from
            them. Upload a file here or when you fit a new model.
          </p>
        </div>
        <button onClick={() => inputRef.current?.click()} disabled={uploading}>
          <UploadIcon /> {uploading ? "Uploading…" : "Upload CSV"}
        </button>
      </header>

      {error && <div className="card error">{error}</div>}

      {loading ? (
        <div className="card empty">Loading…</div>
      ) : datasets.length === 0 ? (
        <div className="card empty">
          <h2>No datasets yet</h2>
          <p>Upload a CSV to get started, or fit a model to create one.</p>
          <button style={{ marginTop: "1rem" }} onClick={() => inputRef.current?.click()} disabled={uploading}>
            <UploadIcon /> {uploading ? "Uploading…" : "Upload CSV"}
          </button>
        </div>
      ) : (
        <>
          <div className="stats">
            <div className="stat"><div className="k">Datasets</div><div className="v">{s.datasets}</div></div>
            <div className="stat"><div className="k">Total rows</div><div className="v">{s.rows}</div></div>
            <div className="stat"><div className="k">Linked models</div><div className="v">{s.linked}</div></div>
            <div className="stat"><div className="k">Last added</div><div className="v sm">{s.lastAdded}</div></div>
          </div>

          <div className="tablebar">
            <span className="count">{datasets.length} datasets</span>
            <span className="grow" />
          </div>

          <div className="lib">
            <div className="tablebar">
              <span className="grow" />
              <ListSearch value={query} onChange={setQuery} placeholder="Search datasets…" />
            </div>
            <table className="lib-table">
              <thead>
                <tr>
                  <th style={{ width: "38%" }}>Dataset</th>
                  <th style={{ width: 90 }}>Rows</th>
                  <th style={{ width: 100 }}>Columns</th>
                  <th style={{ width: 100 }}>Models</th>
                  <th>Added</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {datasets.filter((d) => matches(query, d.name)).map((d) => (
                  <tr key={d.id} className="lib-row" onClick={() => open(d.id)}>
                    <td>
                      <div className="ds-name">
                        <span className="ds-ic"><FileIcon /></span>
                        <span className="lib-name">{d.name}{d.is_sample && <span className="sample-tag">Sample</span>}{d.shared_by && <span className="sample-tag shared" title={`Shared by ${d.shared_by}`}>Shared</span>}</span>
                      </div>
                    </td>
                    <td className="lib-n">{(d.n_rows ?? 0).toLocaleString()}</td>
                    <td className="lib-n">{d.n_columns}</td>
                    <td className="lib-n">{d.n_models}</td>
                    <td className="lib-date">{relativeTime(d.created_at)}</td>
                    <td className="lib-actions">
                      <div className="lib-acts">
                        <button className="act" title="Open" onClick={(e) => { e.stopPropagation(); open(d.id); }}>
                          <OpenIcon />
                        </button>
                        <button className="act del" title="Delete" onClick={(e) => onDelete(e, d)}>
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
