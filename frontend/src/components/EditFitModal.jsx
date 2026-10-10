import { useEffect, useMemo, useState } from "react";
import Modal from "./Modal.jsx";
import ColumnMapper from "./ColumnMapper.jsx";
import Covariates from "./Covariates.jsx";
import Units from "./Units.jsx";
import DistributionStep from "./DistributionStep.jsx";
import CoxOptions from "./CoxOptions.jsx";
import { getDataset, getDistributions, updateModelFit } from "../api.js";
import { EMPTY_MAPPING, columnFacts, dataStepProblems } from "../lifeData.js";
import { TvcToggle } from "./TvcColumns.jsx";
import { tvcMapping, tvcProblems } from "../tvcData.js";
import { groupProblem, withGroup } from "../moreModels.js";

// Edit a saved model's fit spec and refit in place: same dataset, same id.
// Prefilled from the stored spec; anything referencing the model (RCM
// evidence, RBD blocks, fleets) sees the updated fit.
export default function EditFitModal({ model, onClose, onUpdated }) {
  const spec = model.spec || {};
  const [columns, setColumns] = useState(null);
  // The censor inversion and status-word map are stored with the fit options
  // (spec.options) but edited alongside the column they apply to, so they
  // ride on the mapping here.
  const { c_invert: savedInvert, c_map: savedMap, cox: savedCox, ...savedOptions } = spec.options || {};
  const [mapping, setMapping] = useState({
    ...EMPTY_MAPPING, ...(spec.mapping || {}), c_invert: !!savedInvert, c_map: savedMap || null,
  });
  const [facts, setFacts] = useState({});
  // Covariates that change over time (#60): the saved item column says so.
  const [tvc, setTvc] = useState(spec.mapping?.i ? (spec.mapping.xl ? "intervals" : "timeline") : null);
  const [nRows, setNRows] = useState(0);
  const [unit, setUnit] = useState(spec.unit || "");
  const [covariates, setCovariates] = useState(spec.covariates || []);
  const [covUnits, setCovUnits] = useState(spec.covariate_units || {}); // #265
  const [advanced, setAdvanced] = useState(!!spec.formula);
  const [formula, setFormula] = useState(spec.formula || "");
  const [distributions, setDistributions] = useState([]);
  const [distribution, setDistribution] = useState(spec.distribution_id || model.distribution_id || "weibull");
  const [fitOpts, setFitOpts] = useState(savedOptions);
  const [coxOpts, setCoxOpts] = useState(savedCox || {}); // Cox PH: ties, strata, cluster (#61)
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getDistributions().then((d) => setDistributions(d.distributions)).catch(() => {});
    getDataset(model.dataset_id)
      .then((d) => {
        setColumns(d.preview_columns || []);
        setNRows(d.n_rows || 0);
        setFacts(columnFacts({
          columns: d.preview_columns || [], preview: d.preview || [], n_unique: d.n_unique,
          dtypes: d.dtypes, blanks: d.blanks, values: d.values,
        }));
      })
      .catch(() => setError("Couldn't load the model's dataset — it may have been deleted."));
  }, [model.dataset_id]);

  const hasCovariates = advanced ? !!formula.trim() : covariates.length > 0;
  // Covariates over time (#60) take the regressions that can fit them.
  const options = distributions.filter((d) => !!d.covariates === hasCovariates && (!tvc || d.tvc !== false));
  // A shared-frailty model's Group by column (#179) is saved in the mapping.
  const selectedOpt = distributions.find((d) => d.id === distribution);
  const groupBlock = groupProblem(selectedOpt, mapping.group);
  // The Data step's checks, in plain words (#291).
  const problems = !columns ? [] : tvc ? tvcProblems(mapping, facts, tvc, hasCovariates ? 1 : 0)
    : dataStepProblems(mapping, facts, nRows);
  const mappingValid = problems.length === 0;

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
    () => new Set(Object.values(mapping).filter((v) => typeof v === "string" && v)),
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
        mapping: withGroup(mapping, selectedOpt, mapping.group),
        covariates: hasCovariates && !advanced ? covariates : [],
        covariateUnits: hasCovariates && !advanced ? covUnits : {},
        formula: hasCovariates && advanced ? formula : null,
        unit,
        fitOptions: hasCovariates ? (distribution === "cox_ph" ? { cox: coxOpts } : null) : fitOpts,
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
          <button onClick={onRefit} disabled={loading || !mappingValid || !distribution || !!groupBlock}
                  title={groupBlock || undefined}>
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
          <ColumnMapper columns={columns} mapping={mapping} onChange={setMapping} facts={facts} timeVarying={tvc} />
          {problems.length > 0 && (
            <ul className="ds-problems" role="status">
              {problems.map((p) => <li key={p}>{p}</li>)}
            </ul>
          )}
          <Units value={unit} onChange={setUnit} />
          <TvcToggle
            layout={tvc}
            onChange={(layout) => {
              setTvc(layout);
              setMapping((m) => tvcMapping(m, layout, columns, facts, nRows));
            }}
          />
          <Covariates
            columns={columns}
            selected={covariates}
            onToggle={toggleCovariate}
            advanced={advanced}
            onSetAdvanced={setAdvanced}
            formula={formula}
            onSetFormula={setFormula}
            disabledColumns={mappedColumns}
            units={covUnits}
            onSetUnit={(col, u) => setCovUnits((prev) => ({ ...prev, [col]: u }))}
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
              columns={columns}
              usedColumns={new Set([...mappedColumns, ...covariates])}
              group={mapping.group || ""}
              onGroup={(g) => setMapping((m) => ({ ...m, group: g }))}
            />
            {hasCovariates && distribution === "cox_ph" && (
              <CoxOptions
                value={coxOpts}
                onChange={setCoxOpts}
                columns={columns.filter((c) => !mappedColumns.has(c) && (advanced || !covariates.includes(c)))}
              />
            )}
          </div>
        </>
      )}
      {error && <div className="error">{error}</div>}
    </Modal>
  );
}
