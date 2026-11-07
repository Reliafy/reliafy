import { unitInText } from "./unitText.js";

// The time unit of a Strategy tool's model: shown, not asked for, when the
// model has one (a saved model brings its unit); a field only when it hasn't
// (parameters typed in), so results always carry the model's unit.
export default function StrategyUnit({ model, unit, onUnit }) {
  if (model?.unit) {
    return (
      <div className="calc-t">
        <span>Unit</span>
        <span className="strategy-unit-fixed" title="The model's time unit" style={{ color: "var(--ink)", fontSize: "var(--fs-14)", padding: "0.45rem 0" }}>{unitInText(model.unit)} (the model's)</span>
      </div>
    );
  }
  return (
    <label className="calc-t">
      <span>Unit of the model's times</span>
      <input type="text" placeholder="e.g. hours" value={unit} onChange={(e) => onUnit(e.target.value)} />
    </label>
  );
}
