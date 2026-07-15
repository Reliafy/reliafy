import { useEffect, useMemo, useState } from "react";
import Modal from "./Modal.jsx";
import ColumnMapper from "./ColumnMapper.jsx";
import Covariates from "./Covariates.jsx";
import Units from "./Units.jsx";
import DistributionStep from "./DistributionStep.jsx";
import { getDataset, getDistributions, updateModelFit } from "../api.js";

const EMPTY_MAPPING = { x: "", c: "", n: "", xl: "", xr: "", tl: "", tr: "" };

// Edit a saved model's fit spec and refit in place: same dataset, same id.
// Prefilled from the stored spec; anything referencing the model (RCM
// evidence, RBD blocks, fleets) sees the updated fit.
export default function EditFitModal({ model, onClose, onUpdated }) {
  const spec = model.spec || {};
  const [columns, setColumns] = useState(null);
  const [mapping, setMapping] = useState({ ...EMPTY_MAPPING, ...(spec.mapping || {}) });
  const [unit, setUnit] = useState(spec.unit || "");
  const [covariates, setCovariates] = useState(spec.covariates || []);
  const [advanced, setAdvanced] = useState(!!spec.formula);
  const [formula, setFormula] = useState(spec.formula || "");
  const [distributions, setDistributions] = useState([]);
  const [distribution, setDistribution] = useState(spec.distribution_id || model.distribution_id || "weibull");
  const [fitOpts, setFitOpts] = useState(spec.options || {});
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getDistributions().then((d) => setDistributions(d.distributions)).catch(() => {});
    getDataset(model.dataset_id)
      .then((d) => setColumns(d.preview_columns || []))
      .catch(() => setError("Couldn't load the model's dataset — it may have been deleted."));
  }, [model.dataset_id]);

  const hasCovariates = advanced ? !!formula.trim() : covariates.length > 0;
  const options = distributions.filter((d) => !!d.covariates === hasCovariates);
  const mappingValid = mapping.x ? !mapping.xl && !mapping.xr : !!mapping.xl && !!mapping.xr;

  // Keep the selection valid when toggling between plain/covariate modes.
  useEffect(() => {
    if (options.length && !options.some((o) => o.id === distribution)) {
      setDistribution(options[0].id);
    }
  }, [options, distribution]);

  const toggleCovariate = (col) =>
    setCovariates((prev) => (prev.includes(col) ? prev.filter((c) => c !== col) : [...prev, col]));

  // Columns mapped to a survival field can't also be covariates.
  const mappedColumns = useMemo(
    () => new Set(Object.values(mapping).filter(Boolean)),
    [mapping]
  );
  useEffect(() => {
    setCovariates((prev) =>
      prev.some((c) => mappedColumns.has(c)) ? prev.filter((c) => !mappedColumns.has(c)) : prev
    );
  }, [mappedColumns]);

  const onRefit = async () => {
    setLoading(true);
    setError(null);
    try {
      const updated = await updateModelFit(model.id, {
        distribution,
        mapping,
        covariates: hasCovariates && !advanced ? covariates : [],
        formula: hasCovariates && advanced ? formula : null,
        unit,
        fitOptions: hasCovariates ? null : fitOpts,
      });
      onUpdated(updated);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={`Edit fit — ${model.name}`}
      onClose={onClose}
      locked={loading}
      footer={
        <div className="row" style={{ margin: 0, marginLeft: "auto" }}>
          <button className="secondary" onClick={onClose} disabled={loading}>Cancel</button>
          <button onClick={onRefit} disabled={loading || !mappingValid || !distribution}>
            {loading ? "Refitting…" : "Refit & update"}
          </button>
        </div>
      }
    >
      <p className="muted-line" style={{ marginTop: 0 }}>
        Refits from the model's saved dataset. The model keeps its id — every
        analysis that references it will use the updated fit.
      </p>
      {columns === null && !error && <p className="muted-line">Loading dataset…</p>}
      {columns && (
        <>
          <ColumnMapper columns={columns} mapping={mapping} onChange={setMapping} />
          <Units value={unit} onChange={setUnit} />
          <Covariates
            columns={columns}
            selected={covariates}
            onToggle={toggleCovariate}
            advanced={advanced}
            onSetAdvanced={setAdvanced}
            formula={formula}
            onSetFormula={setFormula}
            disabledColumns={mappedColumns}
          />
          <div style={{ marginTop: "0.9rem" }}>
            <DistributionStep
              options={options}
              value={distribution}
              onChange={(id) => {
                setDistribution(id);
                setFitOpts({});
              }}
              fitOpts={fitOpts}
              onFitOpts={setFitOpts}
            />
          </div>
        </>
      )}
      {error && <div className="error">{error}</div>}
    </Modal>
  );
}
