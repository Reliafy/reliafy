import { useState } from "react";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import { RowActions, SampleGroups, itemName } from "../components/LibRows.jsx";

// Growth verdict → chip tone: green is the good verdict, red the bad one.
const GROWTH = {
  improving: { label: "Improving", tone: "success" },
  stable: { label: "Stable", tone: "neutral" },
  deteriorating: { label: "Deteriorating", tone: "danger" },
};

// Saved recurrent-event models, laid out like the life-data model list.
export default function RecurrentLibrary({ models, loading, onOpen, onDelete }) {
  const [query, setQuery] = useState("");
  if (loading) return <div className="card empty">Loading…</div>;
  if (!models.length) {
    return (
      <div className="card empty">
        <h2>No saved models</h2>
        <p>Fit a recurrent model and save it to see it here.</p>
      </div>
    );
  }

  const visible = models.filter((m) => matches(query, m.name, m.model, m.growth, m.id));

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
              <th style={{ width: "36%" }}>Model</th>
              <th>Growth</th>
              <th className="lib-opt" style={{ width: 90 }}>Systems</th>
              <th className="lib-opt" style={{ width: 90 }}>Failures</th>
              <th className="lib-opt">Saved</th>
              <th><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            <SampleGroups rows={visible} cols={6} render={(m) => {
              const g = GROWTH[m.growth] || { label: m.growth || "—", tone: "neutral" };
              return (
                <tr key={m.id} className="lib-row" onClick={() => onOpen(m.id)}>
                  <td>
                    <div className="lib-name">
                      {itemName(m)}
                      {m.shared_by && <Chip title={`Shared by ${m.shared_by}`}>Shared</Chip>}
                    </div>
                  </td>
                  <td><Chip tone={g.tone}>{g.label}</Chip></td>
                  <td className="lib-n lib-opt">{(m.n_systems ?? 0).toLocaleString()}</td>
                  <td className="lib-n lib-opt">{m.n_events != null ? m.n_events.toLocaleString() : "—"}</td>
                  <td className="lib-date lib-opt">{relativeTime(m.created_at)}</td>
                  <RowActions item={m} onOpen={() => onOpen(m.id)} onDelete={() => onDelete(m)} />
                </tr>
              );
            }} />
          </tbody>
        </table>
      </div>
    </>
  );
}
