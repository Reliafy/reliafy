import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { getDataset, deleteDataset } from "../api.js";
import PreviewTable from "../components/PreviewTable.jsx";
import CompareGroups from "../components/CompareGroups.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { distColor, parseTimestamp } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { itemName } from "../components/LibRows.jsx";

// Detail view for one dataset: schema, a preview of the rows, and the models
// fitted from it.
export default function DatasetPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [ds, setDs] = useState(null);
  const [error, setError] = useState(null);
  // ?compare=<column> opens "Compare groups" split by that column (the MCP
  // compare_groups tool links here).
  const [params, setParams] = useSearchParams();
  const compareBy = params.get("compare");
  const comparing = compareBy !== null;
  const setComparing = (on) => {
    const next = new URLSearchParams(params);
    if (on) next.set("compare", "");
    else next.delete("compare");
    setParams(next, { replace: true });
  };

  useEffect(() => {
    setDs(null);
    setError(null);
    getDataset(id).then(setDs).catch((e) => setError(e.message));
  }, [id]);

  const onDelete = async () => {
    if (!window.confirm(`Delete dataset “${ds.name}”?`)) return;
    try {
      await deleteDataset(id);
      navigate("/datasets");
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Datasets", to: "/datasets" }]}
        title={ds ? itemName(ds) : "Dataset"}
        badges={ds?.is_sample && <Chip>Sample</Chip>}
        meta={ds && (
          <>
            {ds.n_rows.toLocaleString()} rows · {ds.n_columns} column{ds.n_columns === 1 ? "" : "s"} · added{" "}
            {parseTimestamp(ds.created_at).toLocaleString()}
          </>
        )}
        actions={ds && ds.n_columns >= 2 && !comparing && (
          <button className="secondary" onClick={() => setComparing(true)}>Compare groups</button>
        )}
        id={ds?.id}
        menu={ds && (
          <>
            <ShareButton
              collection="datasets"
              artifactId={ds.id}
              name={ds.name}
              readOnly={ds.read_only}
              className="ovm-item"
            />
            <button className="ovm-item danger" onClick={onDelete}>
              {ds.read_only ? "Remove from my view" : "Delete"}
            </button>
          </>
        )}
      />

      {error && <div className="card error">{error}</div>}

      {ds && (
        <>
          {comparing && (
            <CompareGroups dataset={ds} splitBy={compareBy || null} onClose={() => setComparing(false)} />
          )}

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
                      <span className="ds-model-name">{itemName(m)}</span>
                      <Chip dot={distColor(m.distribution)}>
                        {String(m.distribution || "").replace(/\s*\(.*$/, "").replace(/\s+PH$/, "")}
                        {m.kind === "regression" && " · PH"}
                      </Chip>
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
