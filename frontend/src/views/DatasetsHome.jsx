import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { listDatasets, deleteDataset } from "../api.js";
import NewDatasetModal from "../components/NewDatasetModal.jsx";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { PlusIcon, RowActions, SampleGroups, itemName } from "../components/LibRows.jsx";

const FileIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 3v5h5M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" />
  </svg>
);

// Landing page for the Datasets section: list uploaded CSVs, upload new, open
// or delete. Datasets are content-addressed, so re-uploading a file reuses it.
export default function DatasetsHome() {
  const navigate = useNavigate();
  const location = useLocation();
  const [datasets, setDatasets] = useState(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState(null);
  const [newOpen, setNewOpen] = useState(false);

  // Open the New-dataset flow directly when a link asks for it.
  useEffect(() => {
    if (location.state?.openUpload) {
      window.history.replaceState({}, "");
      setNewOpen(true);
    }
  }, [location.state]);

  const refresh = useCallback(() => {
    listDatasets()
      .then((d) => setDatasets(d.datasets))
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => refresh(), [refresh]);

  const onCreated = (ds) => {
    setNewOpen(false);
    refresh();
    navigate(`/datasets/d/${ds.id}`);
  };

  const onDelete = async (d) => {
    const msg = d.is_sample
      ? `Remove the sample “${itemName(d)}” from your workspace? It stays available to other users and you won't see it again.`
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
  const visible = (datasets || []).filter((d) => matches(query, d.name, d.id));

  return (
    <div className="app">
      <PageHeader
        title="Datasets"
        meta="Stored once and reused by every model fitted from them."
        primary={<button onClick={() => setNewOpen(true)}><PlusIcon /> New dataset</button>}
      />

      {error && <div className="card error">{error}</div>}

      {loading ? (
        <div className="card empty">Loading…</div>
      ) : datasets.length === 0 ? (
        <div className="card empty">
          <h2>No datasets yet</h2>
          <p>Upload a CSV or Excel file, paste from a spreadsheet, type data into a form, or fit a model to create one.</p>
          <button style={{ marginTop: "1rem" }} onClick={() => setNewOpen(true)}>
            <PlusIcon /> New dataset
          </button>
        </div>
      ) : (
        <>
          <div className="tablebar">
            <span className="count">{visible.length} of {datasets.length} datasets</span>
            <span className="grow" />
            <ListSearch value={query} onChange={setQuery} placeholder="Search datasets…" />
          </div>

          <div className="lib">
            <table className="lib-table">
              <thead>
                <tr>
                  <th style={{ width: "44%" }}>Dataset</th>
                  <th style={{ width: 90 }}>Rows</th>
                  <th className="lib-opt" style={{ width: 100 }}>Columns</th>
                  <th className="lib-opt" style={{ width: 100 }}>Models</th>
                  <th className="lib-opt">Added</th>
                  <th><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                <SampleGroups rows={visible} cols={6} render={(d) => (
                  <tr key={d.id} className="lib-row" onClick={() => open(d.id)}>
                    <td>
                      <div className="ds-name">
                        <span className="ds-ic"><FileIcon /></span>
                        <span className="lib-name">{itemName(d)}{d.shared_by && <Chip title={`Shared by ${d.shared_by}`}>Shared</Chip>}</span>
                      </div>
                    </td>
                    <td className="lib-n">{(d.n_rows ?? 0).toLocaleString()}</td>
                    <td className="lib-n lib-opt">{d.n_columns}</td>
                    <td className="lib-n lib-opt">{d.n_models}</td>
                    <td className="lib-date lib-opt">{relativeTime(d.created_at)}</td>
                    <RowActions item={d} onOpen={() => open(d.id)} onDelete={() => onDelete(d)} />
                  </tr>
                )} />
              </tbody>
            </table>
          </div>
        </>
      )}

      {newOpen && (
        <NewDatasetModal onClose={() => setNewOpen(false)} onCreated={onCreated} />
      )}
    </div>
  );
}
