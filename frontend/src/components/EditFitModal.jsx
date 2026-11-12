import { useEffect, useMemo, useState } from "react";
import Modal from "./Modal.jsx";
import DataMapper from "./DataMapper.jsx";
import DistributionStep from "./DistributionStep.jsx";
import CoxOptions from "./CoxOptions.jsx";
import { getDataset, getDistributions, updateModelFit } from "../api.js";
import { EMPTY_MAPPING, columnFacts, dataStepIssues, dataStepNotes, guessUnitNames } from "../lifeData.js";
import { TvcToggle } from "./TvcColumns.jsx";
import { tvcMapping, tvcProblems } from "../tvcData.js";
import { frailtyFitOptions, groupProblem, withGroup } from "../moreModels.js";

// Edit a saved model's fit spec and refit in place: same dataset, same id.
// Prefilled from the stored spec; anything referencing the model (RCM
// evidence, RBD blocks, fleets) sees the updated fit.
export default function EditFitModal({ model, onClose, onUpdated }) {
  const spec = model.spec || {};
  const [columns, setColumns] = useState(null);
  const [rows, setRows] = useState([]);
  // The column naming each unit: for the words only, never saved.
  const [idColumn, setIdColumn] = useState("");
  // The censor inversion and status-word map are stored with the fit options
  // (spec.options) but edited alongside the column they apply to, so they
  // ride on the mapping here.
  // So does the column of per-row units (``u_col``).
  const { c_invert: savedInvert, c_map: savedMap, cox: savedCox, u_col: savedUnits, ...savedOptions } = spec.options || {};
  const [mapping, setMapping] = useState({
    ...EMPTY_MAPPING, ...(spec.mapping || {}), c_invert: !!savedInvert, c_map: savedMap || null, u: savedUnits || "",
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
        const cols = d.preview_columns || [];
        const f = columnFacts({
          columns: cols, preview: d.preview || [], n_unique: d.n_unique,
          dtypes: d.dtypes, blanks: d.blanks, values: d.values, whole: d.whole, nonpositive: d.nonpositive,
        });
        setColumns(cols);
        setRows((d.preview || []).slice(0, 5));
        setNRows((d.n_rows || 0) - (d.blank_rows || 0));
        setFacts(f);
        if (!spec.mapping?.i) setIdColumn(guessUnitNames(cols, f, d.n_rows || 0, mapping, spec.covariates || []));
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
  const issues = !columns ? [] : tvc ? tvcProblems(mapping, facts, tvc, hasCovariates ? 1 : 0).map((text) => ({ col: null, text }))
    : dataStepIssues(mapping, facts, nRows, unit);
  const problems = issues.map((i) => i.text);
  // Problems about no one column show under the table; the rest in their column's heading.
  const general = issues.filter((i) => !i.col || !(columns || []).includes(i.col)).map((i) => i.text);
  const mappingValid = problems.length === 0;

  // Keep the selection valid when toggling between plain/covariate modes.
  useEffect(() => {
    if (options.length && !options.some((o) => o.id === distribution)) {
      setDistribution(options[0].id);
    }
  }, [options, distribution]);

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
        fitOptions: hasCovariates
          ? (distribution === "cox_ph" ? { cox: coxOpts } : frailtyFitOptions(selectedOpt, fitOpts))
          : fitOpts,
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
                  title={groupBlock || (!mappingValid ? "Settle the notes under the columns first" : undefined)}>
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
          <DataMapper
            columns={columns}
            rows={rows}
            facts={facts}
            mapping={mapping}
            covariates={advanced ? [] : covariates}
            idColumn={idColumn}
            unit={unit}
            onUnitChange={setUnit}
            covUnits={covUnits}
            onCovUnit={(col, u) => setCovUnits((prev) => ({ ...prev, [col]: u }))}
            timeVarying={tvc}
            covariatesAllowed={!advanced}
            issues={issues}
            notes={tvc ? [] : dataStepNotes(mapping, facts)}
            onChange={(next) => {
              setMapping(next.mapping);
              if (!advanced) setCovariates(next.covariates);
              setIdColumn(next.idColumn);
            }}
          />
          {general.length > 0 && (
            <ul className="ds-problems" role="status">
              {general.map((p) => <li key={p}>{p}</li>)}
            </ul>
          )}
          {!mappingValid && general.length === 0 && (
            <p className="hint" role="status">Settle the notes under the columns to refit.</p>
          )}
          <TvcToggle
            layout={tvc}
            onChange={(layout) => {
              setTvc(layout);
              setMapping((m) => tvcMapping(m, layout, columns, facts, nRows));
            }}
          />
          <label className="cov-adv-toggle">
            <input type="checkbox" checked={advanced} onChange={(e) => setAdvanced(e.target.checked)} />
            Covariates as a formula
          </label>
          {advanced && (
            <div className="cov-formula">
              <input type="text" aria-label="Covariate formula" placeholder="e.g. load + speed + site"
                     value={formula} onChange={(e) => setFormula(e.target.value)} />
            </div>
          )}
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
