import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getDataset, deleteDataset } from "../api.js";
import PreviewTable from "../components/PreviewTable.jsx";
import CopyId from "../components/CopyId.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { distColor, parseTimestamp } from "../instrument.js";

// Detail view for one dataset: schema, a preview of the rows, and the models
// fitted from it.
export default function DatasetPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [ds, setDs] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setDs(null);
    setError(null);
    getDataset(id).then(setDs).catch((e) => setError(e.message));
  }, [id]);

  const onDelete = async () => {
    if (!window.confirm(`Delete dataset “${ds.name}”?`)) return;
    try {
      await deleteDataset(id);
      navigate("/datasets/list");
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/datasets")}>Datasets</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/datasets/list")}>Files</button> /{" "}
            <b>{ds ? ds.name : "Dataset"}</b>
          </div>
          <div className="title-row">
            <h1>{ds ? ds.name : "Dataset"}</h1>
          </div>
          {ds && (
            <p>
              {ds.n_rows.toLocaleString()} rows · {ds.n_columns} columns · added{" "}
              {parseTimestamp(ds.created_at).toLocaleString()}
            </p>
          )}
          {ds && <CopyId id={ds.id} />}
        </div>
        {ds && (
          <div className="head-actions">
            <ShareButton
              collection="datasets"
              artifactId={ds.id}
              name={ds.name}
              readOnly={ds.read_only}
            />
            <button className="secondary" onClick={onDelete}>
              {ds.read_only ? "Remove from my view" : "Delete"}
            </button>
          </div>
        )}
      </header>

      {error && <div className="card error">{error}</div>}

      {ds && (
        <>
          <div className="stats">
            <div className="stat"><div className="k">Rows</div><div className="v">{ds.n_rows.toLocaleString()}</div></div>
            <div className="stat"><div className="k">Columns</div><div className="v">{ds.n_columns}</div></div>
            <div className="stat"><div className="k">Linked models</div><div className="v">{ds.n_models}</div></div>
            <div className="stat"><div className="k">Checksum</div><div className="v sm mono" title={ds.checksum}>{ds.checksum.slice(0, 10)}</div></div>
          </div>

          <div className="ds-grid">
            <div className="ds-main">
              <div className="ds-section-h">Preview · first {ds.preview.length} rows</div>
              <PreviewTable columns={ds.preview_columns} rows={ds.preview} />

              <div className="ds-section-h" style={{ marginTop: 22 }}>Columns</div>
              <div className="ds-cols">
                {(ds.columns || []).map((c) => (
                  <div className="ds-col" key={c.name}>
                    <span className="ds-col-name mono">{c.name}</span>
                    <span className="ds-col-type mono">{c.dtype}</span>
                  </div>
                ))}
              </div>
            </div>

            <aside className="ds-aside">
              <div className="gof-card">
                <div className="gofh">Models from this dataset</div>
                {ds.models.length === 0 ? (
                  <div className="ds-empty-aside">No models fitted yet.</div>
                ) : (
                  ds.models.map((m) => (
                    <button
                      key={m.id}
                      className="ds-model-row"
                      onClick={() => navigate(`/modelling/m/${m.id}`)}
                    >
                      <span className="ds-model-name">{m.name}</span>
                      <span className="dpill">
                        <span className="dot" style={{ background: distColor(m.distribution) }} />
                        {String(m.distribution || "").replace(/\s*\(.*$/, "").replace(/\s+PH$/, "")}
                        {m.kind === "regression" && <span className="phflag">PH</span>}
                      </span>
                    </button>
                  ))
                )}
              </div>
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
