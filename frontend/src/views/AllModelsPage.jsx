import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getLibrarySources, getLibraryUsed } from "../api.js";
import { LIBRARY_PATH, recordPath, sourcePath } from "../libraryModels.js";
import { relativeTime } from "../instrument.js";
import { TYPE_LABEL, TYPE_FILTERS, deleteAnyModel, loadAllModels } from "../allModels.js";
import Chip from "../components/ui/Chip.jsx";
import { PlusIcon, RowActions, RowLink, itemName, rowOpen } from "../components/LibRows.jsx";
import { SectionHeader, SectionList } from "../components/SectionPage.jsx";
import { StorageCapNotice } from "../components/StorageCap.jsx";
import { useActivation } from "../components/FirstRun.jsx";
import UnsavedFitReminder from "../components/UnsavedFitReminder.jsx";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { deleteOrRemoveConfirm } from "../confirm.js";

export const MODELLING_HELP = { walkthrough: "fit", guide: "fit-your-first-model" };

// The Models section's landing page: every saved model — life data,
// recurrent, accelerated life, degradation, condition and life — in one
// list, filterable by type. Each type's own list is a child page.
export default function AllModelsPage() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    loadAllModels().then(setRows).catch((e) => setError(e.message));
  }, []);
  useEffect(() => load(), [load]);
  useActivation(rows);

  const confirm = useConfirm();
  const onDelete = async (row) => {
    if (!(await confirm(deleteOrRemoveConfirm(row, "model", { name: itemName(row) })))) return;
    try {
      await deleteAnyModel(row);
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="app">
      <SectionHeader
        title="Models"
        purpose="Every model you've fitted: non-repairable, repairable, accelerated life, degradation, and condition and life."
        help={MODELLING_HELP}
        primary={<button onClick={() => navigate("/models/new")}><PlusIcon /> New model</button>}
      />

      {/* A fit left without saving, with its one-click save (#434). */}
      <UnsavedFitReminder />

      {error && <div className="card error">{error}</div>}
      {/* The Free limit counts every saved model kind (the server's "models"). */}
      <StorageCapNotice kind="models" one="saved model" many="saved models" refreshKey={rows} />

      <SectionList
        rows={rows}
        noun={["model", "models"]}
        placeholder="Search models…"
        // Searchable on name, detail, type — and the id, so an ID copied from
        // a model page (or an API response) pastes straight in.
        fields={(r) => [r.name, r.detail, TYPE_LABEL[r.type]]}
        types={TYPE_FILTERS}
        typeOf={(r) => r.type}
        help={MODELLING_HELP}
        empty={{
          title: "No saved models yet",
          body: "Fit a model to life data, repairs, an accelerated test, wear readings or condition readings, and save it to see it here.",
          action: <button onClick={() => navigate("/models/new")}><PlusIcon /> New model</button>,
        }}
        head={[
          <th key="m" style={{ width: "36%" }}>Model</th>,
          <th key="t" className="lib-opt" style={{ width: 150 }}>Type</th>,
          <th key="d">Detail</th>,
          <th key="s" className="lib-opt">Saved</th>,
          <th key="a"><span className="sr-only">Actions</span></th>,
        ]}
        render={(r) => (
          <tr key={`${r.type}-${r.id}`} className="lib-row" onClick={rowOpen(navigate, r.to)}>
            <td>
              <div className="lib-name">
                <RowLink to={r.to}>{itemName(r)}</RowLink>
                {r.shared_by && <Chip title={`Shared by ${r.shared_by}`}>Shared</Chip>}
                {r.noMax && (
                  <Chip tone="warning" title="These data don't pin down the model: its numbers aren't estimates.">
                    No finite maximum
                  </Chip>
                )}
              </div>
            </td>
            <td className="lib-opt">{TYPE_LABEL[r.type]}</td>
            <td><Chip dot={r.color}>{r.detail}</Chip></td>
            <td className="lib-date lib-opt">{relativeTime(r.created_at)}</td>
            <RowActions item={r} to={r.to} onDelete={() => onDelete(r)} />
          </tr>
        )}
      />
      <LibraryList />
    </div>
  );
}

// After Yours and Samples: the data library (published rates and probabilities, each with its
// uncertainty: models to use as they are or as priors), its sources with their record counts, and
// the records used lately.
function LibraryList() {
  const [sources, setSources] = useState(null);
  const [used, setUsed] = useState([]);
  useEffect(() => {
    getLibrarySources().then((d) => setSources(d.sources || []), () => setSources([]));
    getLibraryUsed().then((d) => setUsed(d.records || []), () => {});
  }, []);
  if (!sources?.length) return null;
  const mine = sources.filter((s) => s.mine);
  const published = sources.filter((s) => !s.mine);
  return (
    <section className="card" aria-labelledby="models-library">
      <div className="maint-head">
        <h2 id="models-library">Libraries</h2>
        <Link to={LIBRARY_PATH}>All libraries</Link>
      </div>
      <p className="hint">Published failure rates and probabilities with their uncertainty, and libraries of your own data and models.</p>
      {mine.length > 0 && (
        <>
          <h3 className="lib-h">Yours</h3>
          <ul className="lib-list">
            {mine.map((s) => (
              <li key={s.id}><Link to={sourcePath(s.id)}>{s.name}</Link> <span className="lib-date">{s.records} {s.records === 1 ? "record" : "records"}</span></li>
            ))}
          </ul>
          <h3 className="lib-h">Published</h3>
        </>
      )}
      <ul className="lib-list">
        {published.map((s) => (
          <li key={s.id}><Link to={sourcePath(s.id)}>{s.name}</Link> <span className="lib-date">{s.records} records</span></li>
        ))}
      </ul>
      {used.length > 0 && (
        <>
          <h3 className="lib-h">Used lately</h3>
          <ul className="lib-list">
            {used.map((u) => (
              <li key={u.record_id}><Link to={recordPath(u.record_id)}>{u.label}</Link> <span className="lib-date">{u.source} · as <Link to={`/models/m/${u.model.id}`}>{u.model.name}</Link></span></li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
