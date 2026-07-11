import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import TrackedItemsPanel, { healthBadge, rulText } from "../components/TrackedItemsPanel.jsx";
import RulChart from "../components/RulChart.jsx";
import Select from "../components/Select.jsx";
import {
  listDegradationModels,
  getDegradationModel,
  deleteTrackedItem,
  addTrackedMeasurement,
} from "../api.js";

// Fleet monitoring, moved out of Modelling: pick a degradation model, manage
// its tracked items, and watch each item's RUL outlook. The model itself
// (paths, life model) still lives under Modelling → Degradation.
export default function StrategyTracking() {
  const { modelId } = useParams();
  const navigate = useNavigate();
  const [models, setModels] = useState(null);
  const [model, setModel] = useState(null);
  const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [mt, setMt] = useState("");
  const [my, setMy] = useState("");
  const [adding, setAdding] = useState(false);
  const [measureError, setMeasureError] = useState(null);

  useEffect(() => {
    listDegradationModels()
      .then((d) => {
        const list = d.models || [];
        setModels(list);
        if (!modelId && list.length > 0) {
          navigate(`/strategy/tracking/${list[0].id}`, { replace: true });
        }
      })
      .catch((e) => setError(e.message));
  }, [modelId, navigate]);

  const refresh = useCallback(() => {
    if (!modelId) return;
    getDegradationModel(modelId)
      .then((m) => {
        setModel(m);
        setSelectedId((cur) => cur && m.items.some((it) => it.id === cur) ? cur : (m.items[0]?.id ?? null));
      })
      .catch((e) => setError(e.message));
  }, [modelId]);
  useEffect(() => { setModel(null); refresh(); }, [refresh]);

  const items = model?.items || [];
  const selected = items.find((it) => it.id === selectedId) || null;
  const unit = model?.results?.unit || "";
  const mUnit = model?.results?.measurement_unit || "";

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
            <button className="crumb-link" onClick={() => navigate("/strategy")}>Strategy</button> / <b>Degradation tracking</b>
          </div>
          <h1>Degradation tracking</h1>
          <p>
            Monitor individual assets against a degradation model and predict
            when each will cross its failure threshold.
          </p>
        </div>
        {models && models.length > 0 && model && (
          <label className="login-field" style={{ minWidth: 260 }}>
            <span>Degradation model</span>
            <Select
              value={modelId || ""}
              onChange={(id) => navigate(`/strategy/tracking/${id}`)}
              options={models.map((m) => ({ value: m.id, label: m.name }))}
            />
          </label>
        )}
      </header>

      {error && <div className="card error">{error}</div>}

      {models === null ? (
        <div className="card empty">Loading…</div>
      ) : models.length === 0 ? (
        <div className="card empty">
          <h2>No degradation models</h2>
          <p>
            Degradation tracking needs a degradation model to predict against.{" "}
            <Link to="/modelling/degradation">Create one under Modelling → Degradation</Link>.
          </p>
        </div>
      ) : !model ? (
        <div className="card empty">Loading…</div>
      ) : (
        <>
          <p className="muted-line" style={{ margin: "0 0 0.2rem" }}>
            Tracking against{" "}
            <Link to={`/modelling/degradation/${model.id}`} className="evidence-link">{model.name}</Link>
            {" "}— {model.path_model} degradation toward {model.threshold}
            {mUnit ? ` ${mUnit}` : ""}{unit ? ` · time in ${unit}` : ""}.
          </p>

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
        </>
      )}
    </div>
  );
}
