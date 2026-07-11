import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import DegradationResultView from "../components/DegradationResultView.jsx";
import TrackedItemsPanel, { healthBadge, rulText } from "../components/TrackedItemsPanel.jsx";
import RulChart from "../components/RulChart.jsx";
import {
  getDegradationModel,
  deleteTrackedItem,
  addTrackedMeasurement,
} from "../api.js";

// One saved degradation model: the fitted paths + life model, the fleet of
// tracked items, and the selected item's RUL outlook with an inline
// add-measurement form.
export default function DegradationModelPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [model, setModel] = useState(null);
  const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [mt, setMt] = useState("");
  const [my, setMy] = useState("");
  const [adding, setAdding] = useState(false);
  const [measureError, setMeasureError] = useState(null);

  const refresh = useCallback(() => {
    getDegradationModel(id)
      .then((m) => {
        setModel(m);
        setSelectedId((cur) => cur && m.items.some((it) => it.id === cur) ? cur : (m.items[0]?.id ?? null));
      })
      .catch((e) => setError(e.message));
  }, [id]);
  useEffect(() => refresh(), [refresh]);

  if (error) {
    return (
      <div className="app">
        <header><h1>Degradation model</h1></header>
        <div className="card error">{error}</div>
      </div>
    );
  }
  if (!model) return <div className="app"><div className="card empty">Loading…</div></div>;

  const items = model.items || [];
  const selected = items.find((it) => it.id === selectedId) || null;
  const unit = model.results?.unit || "";
  const mUnit = model.results?.measurement_unit || "";

  const onDeleteItem = async (it) => {
    const msg = it.is_sample
      ? `Remove the sample item “${it.name}” from your view?`
      : `Delete tracked item “${it.name}”?`;
    if (!window.confirm(msg)) return;
    await deleteTrackedItem(model.id, it.id);
    refresh();
  };

  const onAddMeasurement = async () => {
    if (!selected || mt === "" || my === "") return;
    setAdding(true);
    setMeasureError(null);
    try {
      await addTrackedMeasurement(model.id, selected.id, Number(mt), Number(my));
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
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/modelling/degradation")}>Degradation</button> /{" "}
            <b>{model.name}</b>
          </div>
          <h1>
            {model.name}
            {model.is_sample && <span className="sample-tag" style={{ verticalAlign: "middle" }}>Sample</span>}
          </h1>
          <p>
            {model.path_model} degradation toward {model.threshold}
            {mUnit ? ` ${mUnit}` : ""} · {model.n_units} historical items
            {unit ? ` · time in ${unit}` : ""}
          </p>
        </div>
      </header>

      <DegradationResultView results={model.results} />

      <TrackedItemsPanel
        model={model}
        items={items}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onChanged={() => refresh()}
        onDelete={onDeleteItem}
      />

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
            threshold={model.results?.threshold}
            unit={unit}
            measurementUnit={mUnit}
          />
          {!selected.is_sample && (
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
          {selected.is_sample && (
            <p className="muted-line">Sample items are read-only — register your own item to add measurements.</p>
          )}
          {measureError && <div className="error">{measureError}</div>}
        </div>
      )}
    </div>
  );
}
