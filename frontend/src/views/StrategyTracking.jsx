import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import TrackedItemsPanel, { healthBadge, rulText } from "../components/TrackedItemsPanel.jsx";
import RulChart from "../components/RulChart.jsx";
import {
  getTrackedFleet,
  renameTrackedFleet,
  deleteTrackedItem,
  addTrackedMeasurement,
} from "../api.js";

// One tracked fleet: its items against the fleet's degradation model, each
// with a live RUL outlook. Several fleets can share one model.
export default function StrategyTracking() {
  const { fleetId } = useParams();
  const navigate = useNavigate();
  const [fleet, setFleet] = useState(null);
  const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [mt, setMt] = useState("");
  const [my, setMy] = useState("");
  const [adding, setAdding] = useState(false);
  const [measureError, setMeasureError] = useState(null);

  const refresh = useCallback(() => {
    if (!fleetId) {
      navigate("/fleet/tracking", { replace: true });
      return;
    }
    getTrackedFleet(fleetId)
      .then((f) => {
        setFleet(f);
        setSelectedId((cur) =>
          cur && (f.items || []).some((it) => it.id === cur) ? cur : (f.items?.[0]?.id ?? null)
        );
      })
      .catch((e) => setError(e.message));
  }, [fleetId, navigate]);
  useEffect(() => { setFleet(null); refresh(); }, [refresh]);

  if (error && !fleet) return <div className="app"><div className="card error">{error}</div></div>;
  if (!fleet) return <div className="app"><div className="card empty">Loading…</div></div>;

  const model = fleet.model || null;
  const items = fleet.items || [];
  const selected = items.find((it) => it.id === selectedId) || null;
  const unit = model?.results?.unit || "";
  const mUnit = model?.results?.measurement_unit || "";

  // TrackedItemsPanel expects a model-like object; carry the fleet's
  // writability so the register affordance behaves.
  const panelModel = model
    ? { ...model, read_only: fleet.read_only, is_sample: fleet.is_sample }
    : null;

  const onRename = async () => {
    const name = window.prompt("Fleet name", fleet.name);
    if (!name || !name.trim() || name.trim() === fleet.name) return;
    try {
      const updated = await renameTrackedFleet(fleetId, name.trim());
      setFleet((f) => ({ ...f, name: updated.name }));
    } catch (err) {
      setError(err.message);
    }
  };

  const onDeleteItem = async (it) => {
    const msg = it.is_sample
      ? `Remove the sample item “${it.name}” from your view?`
      : `Delete tracked item “${it.name}”?`;
    if (!window.confirm(msg)) return;
    await deleteTrackedItem(it.model_id, it.id);
    refresh();
  };

  const onAddMeasurement = async () => {
    if (!selected || mt === "" || my === "") return;
    setAdding(true);
    setMeasureError(null);
    try {
      await addTrackedMeasurement(selected.model_id, selected.id, Number(mt), Number(my));
      setMt("");
      setMy("");
      refresh();
    } catch (err) {
      setMeasureError(err.message);
    } finally {
      setAdding(false);
    }
  };

  const badge = selected ? healthBadge(selected.prediction) : null;

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/fleet")}>Fleet</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/fleet/tracking")}>Degradation tracking</button> /{" "}
            <b>{fleet.name}</b>
          </div>
          <h1>
            {fleet.name}
            {fleet.is_sample && <span className="sample-tag" style={{ verticalAlign: "middle" }}>Sample</span>}
          </h1>
          <p>
            {model ? (
              <>
                Against{" "}
                <Link to={`/modelling/degradation/${model.id}`} className="evidence-link">{model.name}</Link>
                {" "}— {model.path_model} degradation toward {model.threshold}
                {mUnit ? ` ${mUnit}` : ""}{unit ? ` · time in ${unit}` : ""}
              </>
            ) : (
              "The linked degradation model is unavailable."
            )}
            {fleet.updated_by ? ` · last edited by ${fleet.updated_by}` : ""}
          </p>
        </div>
        {!fleet.read_only && (
          <button className="secondary" onClick={onRename}>Rename</button>
        )}
      </header>

      {error && <div className="card error">{error}</div>}
      {fleet.is_sample && (
        <div className="card note">
          This is a shared sample fleet — items you register here are yours but
          live alongside the sample. For real assets,{" "}
          <Link to="/fleet/tracking">create your own fleet</Link>.
        </div>
      )}

      {panelModel && (
        <TrackedItemsPanel
          model={panelModel}
          fleetId={fleet.id}
          items={items}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onChanged={() => refresh()}
          onDelete={onDeleteItem}
        />
      )}

      {selected && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <div className="bill-head">
            <h2 style={{ margin: 0 }}>
              {selected.name}
              {badge && <span className={`health-badge ${badge.cls}`} style={{ marginLeft: 10 }}>{badge.label}</span>}
            </h2>
            <span className="muted-line" style={{ margin: 0 }}>
              Remaining life: <b>{rulText(selected.prediction, unit)}</b>
            </span>
          </div>
          {selected.prediction?.method === "error" && (
            <p className="muted-line">
              Not enough data to predict yet ({selected.prediction.detail}) — add
              more measurements below.
            </p>
          )}
          <RulChart
            item={selected}
            threshold={model?.results?.threshold}
            unit={unit}
            measurementUnit={mUnit}
          />
          {!(selected.read_only ?? selected.is_sample) && (
            <div className="row" style={{ gap: "0.6rem", alignItems: "flex-end" }}>
              <label className="login-field" style={{ flex: 1 }}>
                <span>New reading — time{unit ? ` (${unit})` : ""}</span>
                <input type="number" step="any" value={mt} onChange={(e) => setMt(e.target.value)} />
              </label>
              <label className="login-field" style={{ flex: 1 }}>
                <span>Measurement{mUnit ? ` (${mUnit})` : ""}</span>
                <input type="number" step="any" value={my} onChange={(e) => setMy(e.target.value)} />
              </label>
              <button onClick={onAddMeasurement} disabled={adding || mt === "" || my === ""}>
                {adding ? "Predicting…" : "Add & re-predict"}
              </button>
            </div>
          )}
          {(selected.read_only ?? selected.is_sample) && (
            <p className="muted-line">{selected.is_sample ? "Sample items are read-only — register your own item to add measurements." : "This item is read-only in your workspace."}</p>
          )}
          {measureError && <div className="error">{measureError}</div>}
        </div>
      )}
    </div>
  );
}
