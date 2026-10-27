import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { getDataset, deleteDataset, removeMeasurements, renameDataset, splitDataset } from "../api.js";
import PreviewTable from "../components/PreviewTable.jsx";
import CompareGroups from "../components/CompareGroups.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { DatasetPartModal } from "../components/DatasetPartInput.jsx";
import Tabs from "../components/ui/Tabs.jsx";
import { distColor, relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { itemName } from "../components/LibRows.jsx";
import { dtypeLabel, nameSaysDistribution } from "../datasetGuess.js";
import { datasetMeta, datasetParts, splitText } from "../datasetFit.js";
import "../components/Datasets.css";
import { useAskText, useConfirm } from "../components/ConfirmProvider.jsx";
import { deleteOrRemoveConfirm, renamePrompt } from "../confirm.js";

// Where each kind of model fitted to a dataset opens.
const MODEL_PATH = {
  alt_models: "/models/alt/",
  recurrent_models: "/models/recurrent/",
  degradation_models: "/models/degradation/",
};
const KIND_LABEL = { "ALT model": "ALT", "recurrent model": "Repairable", "degradation model": "Degradation" };

// The next step for this data: condition and life when the dataset holds
// its units' lives with their readings, a non-repairable model, or — when
// the rows are unit histories — the recurrent or degradation fit.
function fitAction(ds, parts) {
  const id = encodeURIComponent(ds.id);
  if (parts.life && (parts.measurements || parts.combined)) {
    return { label: "Fit a condition and life model", to: `/models/joint/new?dataset=${id}` };
  }
  const kind = ds.profile?.repeated_units?.kind;
  if (kind === "recurrent") return { label: "Fit a recurrent model", to: `/models/recurrent/new?dataset=${id}` };
  if (kind === "degradation" || parts.readingsOnly) return { label: "Fit a degradation model", to: `/models/degradation?dataset=${id}` };
  return { label: "Fit a model", to: `/models/new?dataset=${id}` };
}

const PART_TABS = [
  { id: "life", label: "Life data", title: "One row per unit: its age at failure or now, and whether it failed" },
  { id: "measurements", label: "Measurements", title: "Readings taken on the units at ages: unit, age, value" },
];

// Detail view for one dataset: its two parts as tabs (the life data, and the
// measurements: readings on the same units), each a preview of the rows
// with every column's type under its name, and the models fitted from it.
export default function DatasetPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [ds, setDs] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null); // "split" | "remove"
  const [partModal, setPartModal] = useState(null); // { part, replacing }
  const [keepOne, setKeepOne] = useState(false);
  // Creating a dataset whose data you already had opens that one: say so,
  // and offer the name you just typed (location state from the New flow).
  const [reused, setReused] = useState(() => (location.state?.reused ? location.state : null));
  // ?compare=<column> opens "Compare groups" split by that column (the MCP
  // life_data_analysis compare_groups action links here); ?part= picks the tab.
  const [params, setParams] = useSearchParams();
  const compareBy = params.get("compare");
  const comparing = compareBy !== null;
  const part = params.get("part") === "measurements" ? "measurements" : "life";
  const setParam = (key, value) => {
    const next = new URLSearchParams(params);
    if (value == null) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  };
  const setComparing = (on) => setParam("compare", on ? "" : null);
  const setPart = (p) => setParam("part", p === "life" ? null : p);

  useEffect(() => {
    setDs(null);
    setError(null);
    getDataset(id).then(setDs).catch((e) => setError(e.message));
  }, [id]);

  // The notice is for this visit only, not a reload.
  useEffect(() => {
    if (location.state?.reused) window.history.replaceState({}, "");
  }, [location.state]);

  const confirm = useConfirm();
  const askText = useAskText();
  const onDelete = async () => {
    if (!(await confirm(deleteOrRemoveConfirm(ds, "dataset", { name: itemName(ds) })))) return;
    try {
      await deleteDataset(id);
      navigate("/data");
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
  const onRename = async () => rename(await askText(renamePrompt({ kind: "dataset", name: ds.name })));

  const onSplit = async () => {
    setBusy("split"); setError(null);
    try {
      setDs(await splitDataset(id));
      setPart("measurements");
    } catch (e) { setError(e.message); } finally { setBusy(null); }
  };
  const onRemoveMeasurements = async () => {
    if (!(await confirm({
      title: "Remove the measurements?",
      body: "The readings come off this dataset; its life data stays. A model fitted to the readings keeps it from happening.",
      confirmLabel: "Remove measurements", destructive: true,
    }))) return;
    setBusy("remove"); setError(null);
    try { setDs(await removeMeasurements(id)); setPart("life"); }
    catch (e) { setError(e.message); } finally { setBusy(null); }
  };

  const parts = datasetParts(ds);
  const fit = ds && fitAction(ds, parts);
  // Compare treats each row as a unit, so it's not offered for unit histories
  // (a ?compare= link still opens it, with a warning).
  const canCompare = ds && parts.life && ds.n_columns >= 2 && !ds.profile?.repeated_units;
  const offerName = reused?.name && ds && !ds.read_only && reused.name !== ds.name ? reused.name : null;
  const nModels = ds ? ds.models.length + (ds.other_models || []).length : 0;
  const writable = ds && !ds.read_only;
  const split = ds && writable && !keepOne && ds.profile?.split;
  const shown = parts[part];
  const types = shown ? Object.fromEntries(Object.entries(shown.types).map(([c, t]) => [c, dtypeLabel(t)])) : {};
  const modelPath = (m) => (m.kind === "joint" ? `/models/joint/${m.id}` : `/models/m/${m.id}`);

  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Data", to: "/data" }]}
        title={ds ? itemName(ds) : "Dataset"}
        badges={ds?.is_sample && <Chip>Sample</Chip>}
        meta={ds && (
          <>
            {datasetMeta(ds)}
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
            {writable && !parts.readingsOnly && (
              <button className="ovm-item" onClick={() => setPartModal({ part: "measurements", replacing: !!parts.measurements })}>
                {parts.measurements ? "Replace measurements" : "Add measurements"}
              </button>
            )}
            {writable && parts.measurements && !parts.readingsOnly && (
              <button className="ovm-item" onClick={onRemoveMeasurements} disabled={busy === "remove"}>Remove measurements</button>
            )}
            {writable && parts.readingsOnly && (
              <button className="ovm-item" onClick={() => setPartModal({ part: "life", replacing: false })}>Add life data</button>
            )}
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

      {error && <div className="card error" role="alert">{error}</div>}

      {ds && (
        <>
          {comparing && (
            <CompareGroups dataset={ds} splitBy={compareBy || null} onClose={() => setComparing(false)} />
          )}

          {split && (
            <div className="card note ds-split-note" role="status">
              <p style={{ margin: 0 }}>{splitText(split)}</p>
              <div className="ds-part-actions">
                <button type="button" onClick={onSplit} disabled={!!busy}>{busy === "split" ? "Splitting…" : "Split it"}</button>
                <button type="button" className="secondary" onClick={() => setKeepOne(true)} disabled={!!busy}>Keep as one table</button>
              </div>
            </div>
          )}

          <div className="ds-grid">
            <div className="ds-main">
              <Tabs tabs={PART_TABS} value={part} onChange={setPart} label="Parts of the dataset" className="ds-tabs" idPrefix="ds" />
              <div id="ds-panel" role="tabpanel" aria-labelledby={`ds-tab-${part}`}>
                {shown ? (
                  <>
                    <div className="ds-section-h">
                      {shown.preview.length < shown.n_rows
                        ? `Preview · first ${shown.preview.length} of ${shown.n_rows.toLocaleString()} rows · ${shown.n_columns} column${shown.n_columns === 1 ? "" : "s"}`
                        : `${shown.n_rows.toLocaleString()} row${shown.n_rows === 1 ? "" : "s"} · ${shown.n_columns} column${shown.n_columns === 1 ? "" : "s"}`}
                      {part === "measurements" && parts.readingsOnly && " · readings alone"}
                      {part === "life" && parts.combined && " · readings in the same table"}
                    </div>
                    <PreviewTable columns={shown.columns} rows={shown.preview} types={types} className="ds-preview" />
                  </>
                ) : part === "measurements" && parts.combined ? (
                  <div className="ds-part-empty">
                    <p>
                      <strong>The readings are in the one table</strong> with the life data: a reading on every row, each
                      unit's outcome on one of its rows. Split the table to keep them here as the dataset's own
                      measurements.
                    </p>
                    {writable ? (
                      <button type="button" onClick={onSplit} disabled={!!busy}>{busy === "split" ? "Splitting…" : "Split the table"}</button>
                    ) : (
                      <p className="muted-line">This dataset is read-only; a condition and life model reads the table as it is.</p>
                    )}
                  </div>
                ) : part === "measurements" ? (
                  <div className="ds-part-empty">
                    <p>
                      <strong>No measurements yet.</strong> Readings taken on these units over time (vibration, wear, oil
                      debris) go here: one row per reading, with the unit's id, its age when read and the value. With them,
                      a <Link to="/guides/condition-based-risk">condition and life model</Link> gives each running unit its
                      own risk.
                    </p>
                    {writable ? (
                      <button type="button" onClick={() => setPartModal({ part: "measurements", replacing: false })}>Add measurements</button>
                    ) : (
                      <p className="muted-line">This dataset is read-only, so none can be added here.</p>
                    )}
                  </div>
                ) : (
                  <div className="ds-part-empty">
                    <p>
                      <strong>No life data yet.</strong> This dataset holds readings alone. Add one row per unit (its id, its age
                      at failure or now, and whether it failed) and the readings become its measurements, ready for a{" "}
                      <Link to="/guides/condition-based-risk">condition and life model</Link>.
                    </p>
                    {writable ? (
                      <button type="button" onClick={() => setPartModal({ part: "life", replacing: false })}>Add life data</button>
                    ) : (
                      <p className="muted-line">This dataset is read-only, so none can be added here.</p>
                    )}
                  </div>
                )}
              </div>
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
                        onClick={() => navigate(modelPath(m))}
                      >
                        <span className="ds-model-name" title={itemName(m)}>{itemName(m)}</span>
                        {m.kind === "joint" ? (
                          <Chip>Condition and life</Chip>
                        ) : (!nameSaysDistribution(itemName(m), m.distribution) || m.kind === "regression") && (
                          /* The distribution, unless the name already says it. */
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

      {partModal && ds && (
        <DatasetPartModal
          datasetId={ds.id}
          part={partModal.part}
          replacing={partModal.replacing}
          onClose={() => setPartModal(null)}
          onDone={(updated) => { setPartModal(null); setDs(updated); setPart(partModal.part === "life" ? "life" : "measurements"); }}
        />
      )}
    </div>
  );
}
