import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { relativeTime } from "../instrument.js";
import { TYPE_LABEL, TYPE_FILTERS, deleteAnyModel, loadAllModels } from "../allModels.js";
import Chip from "../components/ui/Chip.jsx";
import { PlusIcon, RowActions, itemName } from "../components/LibRows.jsx";
import { SectionHeader, SectionList } from "../components/SectionPage.jsx";
import { useActivation } from "../components/FirstRun.jsx";
import UnsavedFitReminder from "../components/UnsavedFitReminder.jsx";

export const MODELLING_HELP = { walkthrough: "fit", guide: "fit-your-first-model" };

// The Modelling section's landing page: every saved model — life data,
// recurrent, accelerated life, degradation, condition monitoring — in one
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

  const onDelete = async (row) => {
    const msg = row.is_sample
      ? `Remove the sample “${itemName(row)}” from your workspace? It stays available to other users and you won't see it again.`
      : `Delete “${row.name}”?`;
    if (!window.confirm(msg)) return;
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
        title="Modelling"
        purpose="Every model you've fitted: life data, recurrent events, accelerated life, degradation and remaining life from condition readings."
        help={MODELLING_HELP}
        primary={<button onClick={() => navigate("/modelling/new")}><PlusIcon /> New model</button>}
      />

      {/* A fit left without saving, with its one-click save (#434). */}
      <UnsavedFitReminder />

      {error && <div className="card error">{error}</div>}

      <SectionList
        rows={rows}
        noun={["model", "models"]}
        placeholder="Search by name, type, or ID…"
        // Searchable on name, detail, type — and the id, so an ID copied from
        // a model page (or an API response) pastes straight in.
        fields={(r) => [r.name, r.detail, TYPE_LABEL[r.type]]}
        types={TYPE_FILTERS}
        typeOf={(r) => r.type}
        help={MODELLING_HELP}
        empty={{
          title: "No saved models yet",
          body: "Fit a model to life data, repairs, an accelerated test, wear readings or condition readings, and save it to see it here.",
          action: <button onClick={() => navigate("/modelling/new")}><PlusIcon /> New model</button>,
        }}
        head={[
          <th key="m" style={{ width: "36%" }}>Model</th>,
          <th key="t" className="lib-opt" style={{ width: 150 }}>Type</th>,
          <th key="d">Detail</th>,
          <th key="s" className="lib-opt">Saved</th>,
          <th key="a"><span className="sr-only">Actions</span></th>,
        ]}
        render={(r) => (
          <tr key={`${r.type}-${r.id}`} className="lib-row" onClick={() => navigate(r.to)}>
            <td>
              <div className="lib-name">
                {itemName(r)}
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
            <RowActions item={r} onOpen={() => navigate(r.to)} onDelete={() => onDelete(r)} />
          </tr>
        )}
      />
    </div>
  );
}
