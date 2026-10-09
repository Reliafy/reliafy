import { useState } from "react";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { distColor, relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import { RowActions, SampleGroups, itemName } from "../components/LibRows.jsx";
import { distLabel } from "../allModels.js";

// The saved life-data models: search, then the table — your own models first,
// then the shared samples under one heading.
export default function ModelLibrary({ models, loading, onOpen, onDelete }) {
  const [query, setQuery] = useState("");
  if (loading) {
    return <div className="card empty">Loading…</div>;
  }
  if (!models.length) {
    return (
      <div className="card empty">
        <h2>No saved models</h2>
        <p>Fit a model and save it to see it here.</p>
      </div>
    );
  }

  const visible = models.filter((m) => matches(query, m.name, m.distribution, m.id));

  return (
    <>
      <div className="tablebar">
        <span className="count">{visible.length} of {models.length} models</span>
        <span className="grow" />
        <ListSearch value={query} onChange={setQuery} placeholder="Search models…" />
      </div>

      <div className="lib">
        <table className="lib-table">
          <thead>
            <tr>
              <th style={{ width: "40%" }}>Model</th>
              <th>Distribution</th>
              <th className="lib-opt" style={{ width: 80 }}>n</th>
              <th className="lib-opt">Saved</th>
              <th><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            <SampleGroups rows={visible} cols={5} render={(m) => (
              <tr key={m.id} className="lib-row" onClick={() => onOpen(m.id)}>
                <td>
                  <div className="lib-name">
                    {itemName(m)}
                    {m.shared_by && <Chip title={`Shared by ${m.shared_by}`}>Shared</Chip>}
                  </div>
                </td>
                <td>
                  <Chip dot={distColor(m.distribution)}>
                    {distLabel(m.distribution)}
                    {m.kind === "regression" && " · PH"}
                  </Chip>
                </td>
                <td className="lib-n lib-opt">{(m.n ?? 0).toLocaleString()}</td>
                <td className="lib-date lib-opt">{relativeTime(m.created_at)}</td>
                <RowActions item={m} onOpen={() => onOpen(m.id)} onDelete={() => onDelete(m)} />
              </tr>
            )} />
          </tbody>
        </table>
      </div>
    </>
  );
}
