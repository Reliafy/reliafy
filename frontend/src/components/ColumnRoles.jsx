import Select from "./Select.jsx";
import { isNumeric } from "../datasetGuess.js";
import { assignRole, columnRoles, countProblem, roleChoices, roleLabel, roleSummary } from "../lifeData.js";

// Every column and what it's for (#434): the fields above pick a column per
// role; this lists each column with its role, so one that isn't a time, a
// status or a count (a cost, an id) has a home: "Ignore this column", or a
// covariate where the model takes them (``covariates``). A count must be
// whole numbers, so a column of decimals can't be made one. Its heading is
// the summary: how many columns are used, and how many ignored.
export default function ColumnRoles({ columns, mapping, covariates, facts = {}, onChange,
                                      timeVarying = null, covariatesAllowed = false, failureMode = false }) {
  const roles = columnRoles(columns, mapping, covariates);
  const { used, ignored } = roleSummary(roles);
  const choices = roleChoices({ timeVarying, covariates: covariatesAllowed, failureMode });

  const optionsFor = (col) => {
    const role = roles[col];
    // A role set elsewhere (a group column, say) stays shown while it's this column's.
    const list = choices.includes(role) ? choices : [...choices.slice(0, -1), role, ""];
    return list.map((r) => {
      if (r === "") return { value: "", label: "Ignore this column" };
      const why = r === "n" ? countProblem(facts[col])
        : r === "cov" && !isNumeric(facts[col]?.dtype) ? "text: use a formula" : null;
      const hint = why === "decimals" ? "has decimals" : why;
      return { value: r, label: roleLabel(r, timeVarying), ...(why && r !== role ? { hint, disabled: true } : {}) };
    });
  };

  return (
    <div className="col-roles">
      <p className="col-roles-h" role="status">
        <span className="ds-label">Columns</span>
        <span className="col-roles-sum">
          {" · "}<b>{used.length}</b> used{used.length > 0 && <>: {used.map((u) => `${u.col} (${roleLabel(u.role, timeVarying).toLowerCase()})`).join(", ")}</>}
          {" · "}
          <b>{ignored.length}</b> ignored{ignored.length > 0 && <>: {ignored.join(", ")}</>}
        </span>
      </p>
      <ul className="col-roles-list">
        {columns.map((col) => (
          <li key={col} className={"col-role" + (roles[col] ? "" : " ignored")}>
            <span className="col-role-name" title={col}>
              {col}
              {facts[col]?.sample != null && <span className="col-role-eg">e.g. {String(facts[col].sample)}</span>}
            </span>
            <Select
              value={roles[col]}
              ariaLabel={`What “${col}” is`}
              onChange={(role) => {
                const next = assignRole(mapping, covariates, col, role, facts);
                onChange(next, { col, role });
              }}
              options={optionsFor(col)}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}
