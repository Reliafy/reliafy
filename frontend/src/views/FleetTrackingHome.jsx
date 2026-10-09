import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import Modal from "../components/Modal.jsx";
import Select from "../components/Select.jsx";
import { listTrackedFleets, createTrackedFleet, deleteTrackedFleet, listDegradationModels } from "../api.js";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { PlusIcon, RowActions, SampleGroups, itemName } from "../components/LibRows.jsx";
import { unitInText } from "../components/unitText.js";


const fmt = (v) =>
  v === null || v === undefined ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 });

// Health-chip strip for one tracked fleet (mirrors the item badges).
function HealthChips({ tracking }) {
  if (!tracking) return <span className="lib-date">—</span>;
  const parts = [
    ["replace", tracking.replace, "danger", "replace now"],
    ["plan", tracking.plan, "warning", "plan replacement"],
    ["healthy", tracking.healthy, "success", "healthy"],
    ["monitoring", tracking.monitoring, "neutral", "monitoring"],
  ].filter(([, n]) => n > 0);
  if (!parts.length) return <span className="lib-date">No items yet</span>;
  return (
    <span className="chip-row">
      {parts.map(([key, n, tone, label]) => (
        <Chip key={key} tone={tone}>{n} {label}</Chip>
      ))}
    </span>
  );
}

// Index of tracked fleets: one row per degradation model with its live
// health rollup. Opening a row goes to that model's tracking page.
export default function FleetTrackingHome() {
  const navigate = useNavigate();
  const [fleets, setFleets] = useState(null);
  const [models, setModels] = useState([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [pickedId, setPickedId] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(null);

  const refresh = useCallback(() => {
    listTrackedFleets()
      .then((d) => setFleets(d.fleets || []))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);

  const openCreate = async () => {
    setName("");
    setPickedId("");
    setCreateError(null);
    setModalOpen(true);
    try {
      const { models: all } = await listDegradationModels();
      setModels(all || []);
    } catch {
      setModels([]);
    }
  };

  const startTracking = async () => {
    if (!name.trim() || !pickedId) return;
    setCreating(true);
    setCreateError(null);
    try {
      const fleet = await createTrackedFleet(name.trim(), pickedId);
      navigate(`/fleet/tracking/${fleet.id}`);
    } catch (err) {
      setCreateError(err.message);
    } finally {
      setCreating(false);
    }
  };

  const onDelete = async (f) => {
    const msg = f.is_sample
      ? `Remove the sample “${itemName(f)}” from your workspace? It stays available to other users and you won't see it again.`
      : `Delete fleet “${f.name}” and its tracked items?`;
    if (!window.confirm(msg)) return;
    try {
      await deleteTrackedFleet(f.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const open = (id) => navigate(`/fleet/tracking/${id}`);
  const visible = (fleets || []).filter((f) => matches(query, f.name, f.model_name, f.id));

  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Fleet" }]}
        title="Degradation tracking"
        meta="Each item's remaining life against a degradation model; open a fleet to log inspections."
        primary={<button onClick={openCreate}><PlusIcon /> New tracked fleet</button>}
      />

      {error && <div className="card error">{error}</div>}

      {fleets === null ? (
        <div className="card empty">Loading…</div>
      ) : fleets.length === 0 ? (
        <div className="card empty">
          <h2>Nothing tracked yet</h2>
          <p>
            Name a fleet, pick the degradation model it runs against, and
            register the items you have in service — or{" "}
            <Link to="/modelling/degradation" className="evidence-link">fit a model</Link> first.
          </p>
          <button style={{ marginTop: "1rem" }} onClick={openCreate}>
            <PlusIcon /> New tracked fleet
          </button>
        </div>
      ) : (
        <>
          <div className="tablebar">
            {query && (
              <span className="count">
                {visible.length} of {fleets.length} tracked fleet{fleets.length === 1 ? "" : "s"}
              </span>
            )}
            <span className="grow" />
            <ListSearch value={query} onChange={setQuery} placeholder="Search tracked fleets…" />
          </div>
          <div className="lib">
            <table className="lib-table">
              <thead>
                <tr>
                  <th style={{ width: "26%" }}>Tracked fleet</th>
                  <th className="lib-opt" style={{ width: "20%" }}>Model</th>
                  <th className="lib-opt" style={{ width: 70 }}>Items</th>
                  <th>Health</th>
                  <th className="lib-opt" style={{ width: 160 }}>Next predicted failure</th>
                  <th className="lib-opt">Updated</th>
                  <th><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                <SampleGroups rows={visible} cols={7} render={(f) => (
                  <tr key={f.id} className="lib-row" onClick={() => open(f.id)}>
                    <td>
                      <div className="lib-name">
                        {itemName(f)}
                        {f.shared_by && <Chip title={`Shared by ${f.shared_by}`}>Shared</Chip>}
                      </div>
                    </td>
                    <td className="lib-date lib-opt">
                      {f.model_name
                        ? itemName({ name: f.model_name, is_sample: f.is_sample || String(f.model_id).startsWith("sample-") })
                        : "—"}
                    </td>
                    <td className="lib-n lib-opt">{f.n_items}</td>
                    <td><HealthChips tracking={f.tracking} /></td>
                    <td className="lib-n lib-opt">
                      {f.tracking?.next_crossing != null
                        ? `${fmt(f.tracking.next_crossing)}${f.unit ? ` ${unitInText(f.unit)}` : ""}`
                        : "—"}
                    </td>
                    <td className="lib-date lib-opt">{relativeTime(f.updated_at || f.created_at)}</td>
                    <RowActions item={f} onOpen={() => open(f.id)} onDelete={() => onDelete(f)} />
                  </tr>
                )} />
              </tbody>
            </table>
          </div>
        </>
      )}
      {modalOpen && (
        <Modal
          title="New tracked fleet"
          className="modal-sm"
          onClose={() => setModalOpen(false)}
          footer={
            <>
              <button className="secondary" onClick={() => setModalOpen(false)}>Cancel</button>
              <button onClick={startTracking} disabled={creating || !name.trim() || !pickedId}>
                {creating ? "Creating…" : "Start tracking"}
              </button>
            </>
          }
        >
          {createError && <div className="card error">{createError}</div>}
          <div className="rcm-form">
            <label className="login-field">
              <span>Fleet name</span>
              <input
                type="text"
                autoFocus
                value={name}
                placeholder="e.g. Sydney trucks — brake pads"
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && startTracking()}
              />
            </label>
            <label className="login-field">
              <span>Degradation model</span>
              <Select
                value={pickedId}
                onChange={setPickedId}
                placeholder="Choose a model…"
                options={models.map((m) => ({
                  value: m.id,
                  label: m.name,
                  hint: `${m.path_model || ""} · threshold ${m.threshold}${m.measurement_unit ? " " + m.measurement_unit : ""}`,
                }))}
              />
            </label>
            <p className="muted-line">
              One model can back any number of fleets. Don't have a model yet?{" "}
              <Link to="/modelling/degradation" className="evidence-link" onClick={() => setModalOpen(false)}>
                Fit a degradation model
              </Link>{" "}
              from your inspection history first.
            </p>
          </div>
        </Modal>
      )}
    </div>
  );
}
