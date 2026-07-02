// Covariate selection for proportional-hazards models. Two modes:
//   - simple: tick CSV columns to use as covariates (Z)
//   - advanced: write a formulaic formula (e.g. "age + sex + age:sex")
// The two are mutually exclusive.
export default function Covariates({
  columns,
  selected,
  onToggle,
  advanced,
  onSetAdvanced,
  formula,
  onSetFormula,
}) {
  return (
    <div className="cov">
      <div className="cov-head">
        <span className="map-group-title-text">Covariates (optional)</span>
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
        Add covariates to fit a proportional-hazards model. Leave empty to fit a
        plain distribution. For categorical (text) columns, use the advanced
        formula.
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
          {columns.map((col) => (
            <label
              key={col}
              className={"cov-chip" + (selected.includes(col) ? " on" : "")}
            >
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
    </div>
  );
}
