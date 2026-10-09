import { useCallback, useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import Modal from "../components/Modal.jsx";
import Select from "../components/Select.jsx";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { listFleets, createFleet, deleteFleet, listModels, listAltModels, listRecurrentModels } from "../api.js";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { PlusIcon, RowActions, SampleGroups, itemName } from "../components/LibRows.jsx";


// Fleet forecasts, the Fleet section's root: one row per fleet with its live
// expected-failure headline.
export default function FleetForecasts() {
  const navigate = useNavigate();
  const [fleets, setFleets] = useState(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState(null);
  const [capHit, setCapHit] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [modelId, setModelId] = useState("");
  const [models, setModels] = useState([]);
  // "life": first failures / with replacement; "recurrent": repairable items,
  // every failure counted (#235).
  const [modelKind, setModelKind] = useState("life");
  const [recurrentModels, setRecurrentModels] = useState([]);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(null);

  const refresh = useCallback(() => {
    listFleets()
      .then((d) => setFleets(d.fleets || []))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);

  const openCreate = async () => {
    setCreateError(null);
    setModalOpen(true);
    // Replaceable equipment: life distributions, regression models and ALT
    // models (#234) — a regression or ALT fleet forecasts each item at its own
    // covariates or stress; picker values carry the kind, "alt:<id>" for an
    // ALT model. Repairable equipment: recurrent-event models (#235).
    const [life, alt, rec] = await Promise.all([
      listModels().then((d) => d.models || []).catch(() => []),
      listAltModels().then((d) => d.models || []).catch(() => []),
      listRecurrentModels().then((d) => d.models || []).catch(() => []),
    ]);
    const plain = life.filter((m) => m.kind === "distribution" && m.distribution);
    const regression = life.filter((m) => m.kind === "regression");
    const asOpt = (m, value, hint) => ({ value, label: m.name, hint });
    setModels([
      ...(plain.length ? [{ heading: "Life distributions" }] : []),
      ...plain.map((m) => asOpt(m, m.id, m.distribution)),
      ...(regression.length ? [{ heading: "Regression models — each item at its own covariates" }] : []),
      ...regression.map((m) => asOpt(m, m.id, m.distribution)),
      ...(alt.length ? [{ heading: "ALT models — each item at its own stress" }] : []),
      ...alt.map((m) => asOpt(m, `alt:${m.id}`, [m.distribution, m.life_model].filter(Boolean).join(" · "))),
    ]);
    setRecurrentModels(rec.map((m) => asOpt(m, m.id, m.model)));
  };

  const onCreate = async () => {
    if (!name.trim() || !modelId) return;
    setCreating(true);
    setCreateError(null);
    try {
      const alt = modelKind !== "recurrent" && modelId.startsWith("alt:");
      const fleet = await createFleet(
        name.trim(), alt ? modelId.slice(4) : modelId, modelKind === "recurrent" ? "recurrent" : alt ? "alt" : "life");
      navigate(`/fleet/forecasts/${fleet.id}`);
    } catch (err) {
      if (err.code === "cap") {
        setModalOpen(false);
        setCapHit(true);
      } else {
        setCreateError(err.message);
      }
    } finally {
      setCreating(false);
    }
  };

  const onDelete = async (f) => {
    const msg = f.is_sample
      ? `Remove the sample “${itemName(f)}” from your workspace? It stays available to other users and you won't see it again.`
      : `Delete fleet “${f.name}”?`;
    if (!window.confirm(msg)) return;
    try {
      await deleteFleet(f.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const open = (id) => navigate(`/fleet/forecasts/${id}`);
  const visible = (fleets || []).filter((f) => matches(query, f.name, f.id));

  return (
    <div className="app">
      <PageHeader
        title="Failure forecasts"
        meta="How many failures a fleet will see over a horizon, from your fitted models."
        primary={<button onClick={openCreate}><PlusIcon /> New forecast</button>}
      />

      {error && <div className="card error">{error}</div>}
      {capHit && (
        <div className="card upgrade-nudge">
          <p>
            You've reached the free-plan limit of 1 failure forecast.{" "}
            <Link to="/billing">Upgrade to Pro</Link> for unlimited fleets.
          </p>
        </div>
      )}

      {fleets === null ? (
        <div className="card empty">Loading…</div>
      ) : fleets.length === 0 ? (
        <div className="card empty">
          <h2>No fleet forecasts</h2>
          <p>Create one from a saved life model and list the items you have in service.</p>
          <button style={{ marginTop: "1rem" }} onClick={openCreate}>
            <PlusIcon /> New forecast
          </button>
        </div>
      ) : (
        <>
          <div className="tablebar">
            <span className="count">{visible.length} of {fleets.length} forecasts</span>
            <span className="grow" />
            <ListSearch value={query} onChange={setQuery} placeholder="Search forecasts…" />
          </div>
          <div className="lib">
            <table className="lib-table">
              <thead>
                <tr>
                  <th style={{ width: "34%" }}>Forecast</th>
                  <th className="lib-opt" style={{ width: 80 }}>Items</th>
                  <th>Expected failures</th>
                  <th className="lib-opt">Updated</th>
                  <th><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                <SampleGroups rows={visible} cols={5} render={(f) => (
                  <tr key={f.id} className="lib-row" onClick={() => open(f.id)}>
                    <td>
                      <div className="lib-name">
                        {itemName(f)}
                        {f.shared_by && <Chip title={`Shared by ${f.shared_by}`}>Shared</Chip>}
                      </div>
                    </td>
                    <td className="lib-n lib-opt">{f.n_items}</td>
                    <td className="lib-date">{f.headline}</td>
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
          title="New failure forecast"
          locked={creating}
          onClose={() => setModalOpen(false)}
          footer={
            <>
              <button className="secondary" onClick={() => setModalOpen(false)} disabled={creating}>
                Cancel
              </button>
              <button onClick={onCreate} disabled={creating || !name.trim() || !modelId}>
                {creating ? "Creating…" : "Create forecast"}
              </button>
            </>
          }
        >
          {createError && <div className="card error">{createError}</div>}
          <div className="rcm-form">
            <label className="login-field">
              <span>Name</span>
              <input
                type="text"
                autoFocus
                value={name}
                placeholder="e.g. Delivery trucks — bearings, next 12 months"
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && onCreate()}
              />
            </label>
            <label className="login-field">
              <span>Equipment</span>
              <Select
                value={modelKind}
                onChange={(v) => { setModelKind(v); setModelId(""); }}
                options={[
                  { value: "life", label: "Replaceable — a life, regression or ALT model",
                    hint: "Failures until each item is replaced (first failures, or with replacement)." },
                  { value: "recurrent", label: "Repairable — a recurrent model",
                    hint: "Each item is repaired and fails again: every repeat failure counted." },
                ]}
              />
            </label>
            <label className="login-field">
              <span>{modelKind === "recurrent" ? "Recurrent model" : "Model"}</span>
              <Select
                value={modelId}
                onChange={setModelId}
                placeholder="Choose a saved model…"
                options={modelKind === "recurrent" ? recurrentModels : models}
              />
            </label>
            <p className="muted-line">
              {modelKind === "recurrent"
                ? "The forecast counts each item's repeat failures from its age (time since new) under this model — fit one under Modelling › Recurrent events first if you don't have one yet."
                : "The forecast evaluates this model at each item's age (and, for a regression or ALT model, at each item's own conditions) — fit one under Modelling first if you don't have one yet."}
            </p>
          </div>
        </Modal>
      )}
    </div>
  );
}
