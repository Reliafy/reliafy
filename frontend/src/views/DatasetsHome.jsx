import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { listDatasets, deleteDataset, renameDataset } from "../api.js";
import NewDatasetModal from "../components/NewDatasetModal.jsx";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import { PlusIcon, itemName } from "../components/LibRows.jsx";
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

const LEAVE_PX = 60;

// How far (px) a point is outside the box around the given elements (0 inside).
function outsideBy(els, x, y) {
  const rs = [...els].map((el) => el.getBoundingClientRect());
  if (!rs.length) return Infinity;
  const left = Math.min(...rs.map((r) => r.left)), right = Math.max(...rs.map((r) => r.right));
  const top = Math.min(...rs.map((r) => r.top)), bottom = Math.max(...rs.map((r) => r.bottom));
  return Math.max(left - x, x - right, top - y, y - bottom, 0);
}

// Each row's ⋯ menu: every fit for this data, the data (open, rename) and delete.
function RowMenu({ d, onRename, onDelete }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const options = fitOptions(d);
  // Open until the mouse is well clear of it (more than LEAVE_PX past the menu
  // and its button), a click elsewhere, or Escape. Crossing the gap to an item
  // never closes it.
  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    const far = (e) => {
      if (e.pointerType !== "mouse" || !ref.current) return;
      if (outsideBy(ref.current.querySelectorAll(".ds-more, .ds-menu"), e.clientX, e.clientY) > LEAVE_PX) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("touchstart", away);
    document.addEventListener("keydown", esc);
    document.addEventListener("pointermove", far);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("touchstart", away);
      document.removeEventListener("keydown", esc);
      document.removeEventListener("pointermove", far);
    };
  }, [open]);
  const act = (fn) => (e) => { e.stopPropagation(); setOpen(false); fn(); };
  return (
    <td className="lib-actions">
      <div className="ds-acts" ref={ref} onClick={(e) => e.stopPropagation()}>
        <button type="button" className="ds-more" aria-haspopup="menu" aria-expanded={open} aria-label="More actions"
          onClick={() => setOpen((o) => !o)}>
          <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><circle cx="3.5" cy="8" r="1.3" /><circle cx="8" cy="8" r="1.3" /><circle cx="12.5" cy="8" r="1.3" /></svg>
        </button>
        {open && (
          <div className="ds-menu" role="menu">
            <div className="ds-menu-h">Fit a model</div>
            {options.map((o) => <button type="button" key={o.label} role="menuitem" onClick={act(() => navigate(o.to))}>{o.label}</button>)}
            <div className="ds-menu-sep" />
            <div className="ds-menu-h">Data</div>
            <button type="button" role="menuitem" onClick={act(() => navigate(datasetPath(d.id)))}>Open and view the data</button>
            {!d.read_only && <button type="button" role="menuitem" onClick={act(() => onRename(d))}>Rename</button>}
            <div className="ds-menu-sep" />
            <button type="button" role="menuitem" className="ds-menu-del" onClick={act(() => onDelete(d))}>
              {d.read_only ? "Remove from my view" : "Delete"}
            </button>
          </div>
        )}
      </div>
    </td>
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

  const onRename = async (d) => {
    const name = window.prompt("Dataset name", d.name);
    if (!name || !name.trim() || name.trim() === d.name) return;
    try {
      await renameDataset(d.id, name.trim());
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
          <th key="d">Dataset</th>,
          <th key="h" className="lib-opt" style={{ width: 270 }}>Holds</th>,
          <th key="r" className="ds-units-h">Size</th>,
          <th key="tu" className="lib-opt" style={{ width: 90 }}>Time unit</th>,
          <th key="t" className="lib-opt" style={{ width: 100 }}>Added</th>,
          <th key="a" style={{ width: 48 }}><span className="sr-only">Actions</span></th>,
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
            <td className="ds-units">
              {d.summary || `${(d.n_rows ?? 0).toLocaleString()} rows`}
              {d.n_models > 0 && <div className="ds-used">Used by {d.n_models} model{d.n_models === 1 ? "" : "s"}</div>}
            </td>
            <td className="lib-opt ds-tu">{d.time_unit ? `${d.time_unit}s` : <span className="ds-tu-none">—</span>}</td>
            <td className="lib-date lib-opt">{relativeTime(d.created_at)}</td>
            <RowMenu d={d} onRename={onRename} onDelete={onDelete} />
          </tr>
        )}
      />

      {newOpen && (
        <NewDatasetModal onClose={() => setNewOpen(false)} onCreated={onCreated} />
      )}
    </div>
  );
}
