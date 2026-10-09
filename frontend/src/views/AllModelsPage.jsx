import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { relativeTime } from "../instrument.js";
import { FirstRunStrip } from "../components/FirstRun.jsx";
import { useFirstRun } from "../firstRun.js";
import { TYPE_LABEL, deleteAnyModel, loadAllModels } from "../allModels.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { PlusIcon, RowActions, SampleGroups, itemName } from "../components/LibRows.jsx";

// Every saved model — life data, accelerated life, recurrent, degradation — in
// one list. Rows link to the right detail page; the type-specific lists live
// under each section.
export default function AllModelsPage() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");
  // No models, datasets or diagrams of their own yet (samples don't count).
  const firstRun = useFirstRun(rows ? rows.some((r) => !r.is_sample) : undefined);

  const load = useCallback(() => {
    loadAllModels().then(setRows).catch((e) => setError(e.message));
  }, []);
  useEffect(() => load(), [load]);

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

  const loading = rows === null;
  // Searchable on name, detail, type — and the id, so an ID copied from a model
  // page (or an API response) pastes straight in and finds its row.
  const visible = (rows || []).filter((r) =>
    matches(query, r.name, r.detail, TYPE_LABEL[r.type], r.id)
  );

  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Modelling", to: "/modelling" }]}
        title="All models"
        meta="Life data, accelerated life, recurrent events and degradation, in one list."
        primary={<button onClick={() => navigate("/modelling/new")}><PlusIcon /> New model</button>}
      />

      <FirstRunStrip info={firstRun} />

      {error && <div className="card error">{error}</div>}

      {loading ? (
        <div className="card empty">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="card empty">
          <h2>No saved models</h2>
          <p>Fit a model and save it to see it here.</p>
        </div>
      ) : (
        <>
          <div className="tablebar">
            <span className="count">{visible.length} of {rows.length} models</span>
            <span className="grow" />
            <ListSearch value={query} onChange={setQuery} placeholder="Search by name, type, or ID…" />
          </div>

          <div className="lib">
            <table className="lib-table">
              <thead>
                <tr>
                  <th style={{ width: "36%" }}>Model</th>
                  <th className="lib-opt" style={{ width: 150 }}>Type</th>
                  <th>Detail</th>
                  <th className="lib-opt">Saved</th>
                  <th><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                <SampleGroups rows={visible} cols={5} render={(r) => (
                  <tr key={r.id} className="lib-row" onClick={() => navigate(r.to)}>
                    <td>
                      <div className="lib-name">
                        {itemName(r)}
                        {r.shared_by && <Chip title={`Shared by ${r.shared_by}`}>Shared</Chip>}
                        {r.noMax && (
                          <Chip tone="warning"
                                title="These data don't pin down the model: its numbers aren't estimates.">
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
                )} />
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
