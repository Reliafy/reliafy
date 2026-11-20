import { useCallback, useEffect, useState } from "react";
import { createdState } from "../libraries.js";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { listDatasets, deleteDataset, renameDataset } from "../api.js";
import NewDatasetModal from "../components/NewDatasetModal.jsx";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import { PlusIcon, RowActions, itemName, rowOpen } from "../components/LibRows.jsx";
import { SectionHeader, SectionList } from "../components/SectionPage.jsx";
import { datasetPath } from "../navigation.js";
import { fitOptions } from "../datasetFit.js";
import "../components/Datasets.css";
import { StorageCapNotice } from "../components/StorageCap.jsx";
import { useAskText, useConfirm } from "../components/ConfirmProvider.jsx";
import { changedText, deleteOrRemoveConfirm, renamePrompt } from "../confirm.js";

const HELP = { guide: "fit-your-first-model" };

const FileIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 3v5h5M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" />
  </svg>
);

// Each row's ⋯ menu (the shared row menu): open the data, every fit for it,
// rename, then delete.
const fitLabel = (label) => `Fit a ${label.charAt(0).toLowerCase()}${label.slice(1)}`;
function DatasetRowActions({ d, onRename, onDelete }) {
  const navigate = useNavigate();
  return (
    <RowActions item={d} to={datasetPath(d.id)} onDelete={() => onDelete(d)} actions={[
      ...fitOptions(d).map((o) => ({ id: `fit:${o.to}`, label: fitLabel(o.label), onSelect: () => navigate(o.to) })),
      !d.read_only && { id: "rename", label: "Rename…", onSelect: () => onRename(d) },
    ]} />
  );
}

// Modelling › Data: the datasets, uploaded, pasted or typed in; open, add or
// delete. Datasets are content-addressed, so re-uploading a file reuses it.
export default function DatasetsHome() {
  const navigate = useNavigate();
  const location = useLocation();
  const [datasets, setDatasets] = useState(null);
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

  // Identical data opens the dataset you already had; its page says so and
  // offers the name just typed.
  const onCreated = (ds, typedName) => {
    setNewOpen(false);
    refresh();
    navigate(datasetPath(ds.id), createdState(ds, typedName));
  };

  const confirm = useConfirm();
  const askText = useAskText();
  const onDelete = async (d) => {
    if (!(await confirm(deleteOrRemoveConfirm(d, "dataset", { name: itemName(d) })))) return;
    try {
      await deleteDataset(d.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const onRename = async (d) => {
    const name = changedText(await askText(renamePrompt({ kind: "dataset", name: d.name })), d.name);
    if (!name) return;
    try {
      await renameDataset(d.id, name);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };
  const newDataset = <button onClick={() => setNewOpen(true)}><PlusIcon /> New dataset</button>;

  return (
    <div className="app">
      <SectionHeader
        section="data"
        title="Data"
        purpose="Your datasets, stored once and reused by every model fitted from them."
        help={HELP}
        primary={newDataset}
      />

      {error && <div className="card error">{error}</div>}
      <StorageCapNotice kind="datasets" one="saved dataset" many="saved datasets" refreshKey={datasets} />

      <SectionList
        rows={datasets}
        noun={["dataset", "datasets"]}
        className="ds-lib"
        tagsOf={(d) => d.tags}
        help={HELP}
        empty={{
          title: "No datasets yet",
          body: "Upload a CSV or Excel file, paste from a spreadsheet, type data into a form, or fit a model to create one.",
          action: newDataset,
        }}
        head={[
          <th key="d">Dataset</th>,
          <th key="h" className="lib-opt" style={{ width: 270 }}>Holds</th>,
          <th key="r" className="ds-units-h">Size</th>,
          <th key="tu" className="lib-opt" style={{ width: 90 }}>Time unit</th>,
          <th key="t" className="lib-opt" style={{ width: 100 }}>Added</th>,
          <th key="a" style={{ width: 48 }}><span className="sr-only">Actions</span></th>,
        ]}
        render={(d) => (
          <tr key={d.id} className="lib-row" onClick={rowOpen(navigate, datasetPath(d.id))}>
            <td>
              <div className="ds-name">
                <span className="ds-ic"><FileIcon /></span>
                {/* A real link, so the row opens from the keyboard too. */}
                <Link className="lib-name ds-row-link lib-link" to={datasetPath(d.id)} onClick={(e) => e.stopPropagation()}>
                  {itemName(d)}
                </Link>
                {d.shared_by && <Chip title={`Shared by ${d.shared_by}`}>Shared</Chip>}
              </div>
            </td>
            <td className="lib-opt">
              <div className="ds-tags">{(d.tags || []).map((t) => <Chip key={t}>{t}</Chip>)}</div>
            </td>
            <td className="ds-units">
              {d.summary || `${(d.n_rows ?? 0).toLocaleString()} rows`}
              {d.n_models > 0 && <div className="ds-used">Used by {d.n_models} model{d.n_models === 1 ? "" : "s"}</div>}
            </td>
            <td className="lib-opt ds-tu">{d.time_unit ? `${d.time_unit}s` : <span className="ds-tu-none">—</span>}</td>
            <td className="lib-date lib-opt">{relativeTime(d.created_at)}</td>
            <DatasetRowActions d={d} onRename={onRename} onDelete={onDelete} />
          </tr>
        )}
      />

      {newOpen && (
        <NewDatasetModal onClose={() => setNewOpen(false)} onCreated={onCreated} onSplit={refresh} libraryChoice />
      )}
    </div>
  );
}
