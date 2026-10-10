// Covariate selection for proportional-hazards models. Two modes:
//   - simple: tick CSV columns to use as covariates (Z)
//   - advanced: write a formulaic formula (e.g. "age + sex + age:sex")
// The two are mutually exclusive. ``folded``: inside a disclosure that already
// names them, so no heading or rule of its own. ``units``/``onSetUnit`` (optional, #265)
// give each ticked covariate a unit ("°C", "kN"), shown with its calculator
// input and coefficient.
export default function Covariates({
  columns,
  selected,
  onToggle,
  advanced,
  onSetAdvanced,
  formula,
  onSetFormula,
  disabledColumns,
  units,
  onSetUnit,
  folded = false,
}) {
  const isMapped = (col) => !!disabledColumns && disabledColumns.has(col);
  return (
    <div className={"cov" + (folded ? " cov-folded" : "")}>
      <div className="cov-head">
        {!folded && <span className="map-group-title-text">Covariates (optional)</span>}
        <label className="cov-adv-toggle">
          <input
            type="checkbox"
            checked={advanced}
            onChange={(e) => onSetAdvanced(e.target.checked)}
          />
          Advanced formula
        </label>
      </div>

      <p className="cov-hint">
        Add covariates to fit a regression model (proportional-hazards or
        accelerated-failure-time). Leave empty to fit a plain distribution. For
        categorical (text) columns, use the advanced formula.
      </p>

      {advanced ? (
        <div className="cov-formula">
          <input
            type="text"
            placeholder="e.g. age + sex + age:temperature"
            value={formula}
            onChange={(e) => onSetFormula(e.target.value)}
          />
          <span className="map-help">
            A{" "}
            <a
              href="https://matthewwardrop.github.io/formulaic/"
              target="_blank"
              rel="noreferrer"
            >
              formulaic
            </a>{" "}
            formula over your columns. Categoricals are expanded automatically.
          </span>
        </div>
      ) : (
        <div className="cov-chips">
          {/* The time, status and count columns are never covariates (#291). */}
          {columns.filter((col) => !isMapped(col)).map((col) => (
            <label key={col} className={"cov-chip" + (selected.includes(col) ? " on" : "")}>
              <input
                type="checkbox"
                checked={selected.includes(col)}
                onChange={() => onToggle(col)}
              />
              {col}
            </label>
          ))}
        </div>
      )}
      {!advanced && onSetUnit && selected.length > 0 && (
        <div className="cov-units">
          <span className="map-help">Units (optional) — shown with each covariate's input and coefficient.</span>
          {selected.map((col) => (
            <label className="cov-unit" key={col}>
              <span>{col}</span>
              <input
                type="text"
                maxLength={24}
                placeholder="e.g. °C"
                value={(units || {})[col] || ""}
                onChange={(e) => onSetUnit(col, e.target.value)}
              />
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
