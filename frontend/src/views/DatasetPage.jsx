import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { getDataset, deleteDataset, renameDataset } from "../api.js";
import PreviewTable from "../components/PreviewTable.jsx";
import CompareGroups from "../components/CompareGroups.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { distColor, relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { itemName } from "../components/LibRows.jsx";
import { dtypeLabel, nameSaysDistribution } from "../datasetGuess.js";
import "../components/Datasets.css";

// Where each kind of model fitted to a dataset opens.
const MODEL_PATH = {
  alt_models: "/modelling/alt/",
  recurrent_models: "/modelling/recurrent/",
  degradation_models: "/modelling/degradation/",
};
const KIND_LABEL = { "ALT model": "ALT", "recurrent model": "Recurrent", "degradation model": "Degradation" };

// The next step for this data: a life model, or — when the rows are unit
// histories — the recurrent or degradation fit.
function fitAction(ds) {
  const kind = ds.profile?.repeated_units?.kind;
  if (kind === "recurrent") return { label: "Fit a recurrent model", to: `/modelling/recurrent/new?dataset=${encodeURIComponent(ds.id)}` };
  if (kind === "degradation") return { label: "Fit a degradation model", to: "/modelling/degradation" };
  return { label: "Fit a model", to: `/modelling/new?dataset=${encodeURIComponent(ds.id)}` };
}

// Detail view for one dataset: a preview of the rows (each column's type under
// its name), and the models fitted from it.
export default function DatasetPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [ds, setDs] = useState(null);
  const [error, setError] = useState(null);
  // Creating a dataset whose data you already had opens that one: say so,
  // and offer the name you just typed (location state from the New flow).
  const [reused, setReused] = useState(() => (location.state?.reused ? location.state : null));
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

  // The notice is for this visit only, not a reload.
  useEffect(() => {
    if (location.state?.reused) window.history.replaceState({}, "");
  }, [location.state]);

  const onDelete = async () => {
    if (!window.confirm(`Delete dataset “${ds.name}”?`)) return;
    try {
      await deleteDataset(id);
      navigate("/datasets");
    } catch (e) {
      setError(e.message);
    }
  };

  const rename = async (name) => {
    if (!name || !name.trim() || name.trim() === ds.name) return;
    try {
      const updated = await renameDataset(id, name.trim());
      setDs((d) => ({ ...d, name: updated.name }));
      setReused(null);
    } catch (e) {
      setError(e.message);
    }
  };
  const onRename = () => rename(window.prompt("Dataset name", ds.name));

  const fit = ds && fitAction(ds);
  // Compare treats each row as a unit, so it's not offered for unit histories
  // (a ?compare= link still opens it, with a warning).
  const canCompare = ds && ds.n_columns >= 2 && !ds.profile?.repeated_units;
  const types = Object.fromEntries((ds?.columns || []).map((c) => [c.name, dtypeLabel(c.dtype)]));
  const offerName = reused?.name && ds && !ds.read_only && reused.name !== ds.name ? reused.name : null;
  const nModels = ds ? ds.models.length + (ds.other_models || []).length : 0;

  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Datasets", to: "/datasets" }]}
        title={ds ? itemName(ds) : "Dataset"}
        badges={ds?.is_sample && <Chip>Sample</Chip>}
        meta={ds && (
          <>
            {ds.n_rows.toLocaleString()} rows · {ds.n_columns} column{ds.n_columns === 1 ? "" : "s"}
            {!ds.is_sample && <> · added {relativeTime(ds.created_at)}</>}
          </>
        )}
        primary={fit && (
          // While comparing, Compare is the view's next step.
          <button className={comparing ? "secondary" : undefined} onClick={() => navigate(fit.to)}>
            {fit.label}
          </button>
        )}
        actions={canCompare && !comparing && (
          <button className="secondary" onClick={() => setComparing(true)}>Compare groups</button>
        )}
        id={ds?.id}
        menu={ds && (
          <>
            {!ds.read_only && <button className="ovm-item" onClick={onRename}>Rename</button>}
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
      >
        {reused && ds && (
          <p className="ds-reused" role="status">
            You already had this data, so it opened here.
            {offerName && (
              <button className="link" onClick={() => rename(offerName)}>Rename it “{offerName}”</button>
            )}
          </p>
        )}
      </PageHeader>

      {error && <div className="card error">{error}</div>}

      {ds && (
        <>
          {comparing && (
            <CompareGroups dataset={ds} splitBy={compareBy || null} onClose={() => setComparing(false)} />
          )}

          <div className="ds-grid">
            <div className="ds-main">
              <div className="ds-section-h">
                {ds.preview.length < ds.n_rows ? `Preview · first ${ds.preview.length} rows` : "Data"}
              </div>
              <PreviewTable columns={ds.preview_columns} rows={ds.preview} types={types} className="ds-preview" />
            </div>

            <aside className="ds-aside">
              <div className="gof-card">
                <div className="gofh">Models from this dataset</div>
                {nModels === 0 ? (
                  <div className="ds-empty-aside">No models fitted yet.</div>
                ) : (
                  <>
                    {ds.models.map((m) => (
                      <button
                        key={m.id}
                        className="ds-model-row"
                        onClick={() => navigate(`/modelling/m/${m.id}`)}
                      >
                        <span className="ds-model-name" title={itemName(m)}>{itemName(m)}</span>
                        {/* The distribution, unless the name already says it. */}
                        {(!nameSaysDistribution(itemName(m), m.distribution) || m.kind === "regression") && (
                          <Chip dot={distColor(m.distribution)}>
                            {String(m.distribution || "").replace(/\s*\(.*$/, "").replace(/\s+PH$/, "")}
                            {m.kind === "regression" && " · PH"}
                          </Chip>
                        )}
                      </button>
                    ))}
                    {(ds.other_models || []).map((m) => (
                      <button
                        key={m.id}
                        className="ds-model-row"
                        onClick={() => navigate(`${MODEL_PATH[m.collection]}${m.id}`)}
                      >
                        <span className="ds-model-name" title={itemName(m)}>{itemName(m)}</span>
                        <Chip>{KIND_LABEL[m.kind] || m.kind}</Chip>
                      </button>
                    ))}
                  </>
                )}
              </div>
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
