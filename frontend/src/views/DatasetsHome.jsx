import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { listDatasets, deleteDataset } from "../api.js";
import NewDatasetModal from "../components/NewDatasetModal.jsx";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import { PlusIcon, RowActions, itemName } from "../components/LibRows.jsx";
import { SectionHeader, SectionList } from "../components/SectionPage.jsx";
import { datasetPath } from "../sections.js";
import { fitOptions } from "../datasetFit.js";
import "../components/Datasets.css";

const HELP = { guide: "fit-your-first-model" };

const FileIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 3v5h5M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" />
  </svg>
);

// One control: "Fit" opens the usual fit; the chevron (only when there's a
// choice) lists every fit for this data.
function FitButton({ d }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const options = fitOptions(d);
  const go = (to) => (e) => { e.stopPropagation(); navigate(to); };
  return (
    <div className="ds-fit" onClick={(e) => e.stopPropagation()} onMouseLeave={() => setOpen(false)}>
      <button type="button" className="ds-fit-go" title={options[0].label} onClick={go(options[0].to)}>Fit</button>
      {options.length > 1 && (
        <button type="button" className="ds-fit-more" aria-haspopup="menu" aria-expanded={open}
          aria-label="More ways to fit" onClick={() => setOpen((o) => !o)}>
          <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true"><path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </button>
      )}
      {open && (
        <div className="ds-fit-menu" role="menu">
          {options.map((o) => <button type="button" key={o.label} role="menuitem" onClick={go(o.to)}>{o.label}</button>)}
        </div>
      )}
    </div>
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
    navigate(datasetPath(ds.id), ds.reused ? { state: { reused: true, name: typedName || null } } : undefined);
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

  const open = (id) => navigate(datasetPath(id));
  const newDataset = <button onClick={() => setNewOpen(true)}><PlusIcon /> New dataset</button>;

  return (
    <div className="app">
      <SectionHeader
        section="modelling"
        title="Data"
        purpose="Your datasets, stored once and reused by every model fitted from them."
        help={HELP}
        primary={newDataset}
      />

      {error && <div className="card error">{error}</div>}

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
          <th key="d" style={{ width: "32%" }}>Dataset</th>,
          <th key="h" className="lib-opt" style={{ width: "30%" }}>Holds</th>,
          <th key="r" style={{ width: 200 }}>Units</th>,
          <th key="u" className="lib-opt" style={{ width: 170 }}><span className="sr-only">Used by</span></th>,
          <th key="f" style={{ width: 80 }}><span className="sr-only">Fit</span></th>,
          <th key="t" className="lib-opt">Added</th>,
          <th key="a"><span className="sr-only">Actions</span></th>,
        ]}
        render={(d) => (
          <tr key={d.id} className="lib-row" onClick={() => open(d.id)}>
            <td>
              <div className="ds-name">
                <span className="ds-ic"><FileIcon /></span>
                {/* A real link, so the row opens from the keyboard too. */}
                <Link className="lib-name ds-row-link" to={datasetPath(d.id)} onClick={(e) => e.stopPropagation()}>
                  {itemName(d)}
                </Link>
                {d.shared_by && <Chip title={`Shared by ${d.shared_by}`}>Shared</Chip>}
              </div>
            </td>
            <td className="lib-opt">
              <div className="ds-tags">{(d.tags || []).map((t) => <Chip key={t}>{t}</Chip>)}</div>
            </td>
            <td className="ds-units">{d.summary || `${(d.n_rows ?? 0).toLocaleString()} rows`}</td>
            <td className="lib-opt">
              {d.n_models > 0 && (
                <span className="ds-used">Used by {d.n_models} model{d.n_models === 1 ? "" : "s"}</span>
              )}
            </td>
            <td><FitButton d={d} /></td>
            <td className="lib-date lib-opt">{relativeTime(d.created_at)}</td>
            {/* The row opens the dataset, so no separate Open button. */}
            <RowActions item={d} onDelete={() => onDelete(d)} />
          </tr>
        )}
      />

      {newOpen && (
        <NewDatasetModal onClose={() => setNewOpen(false)} onCreated={onCreated} />
      )}
    </div>
  );
}
