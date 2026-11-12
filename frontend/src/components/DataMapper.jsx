import Select from "./Select.jsx";
import StatusMeanings from "./StatusMeanings.jsx";
import usePhone from "../usePhone.js";
import { formatCell } from "../format.js";
import { isNumeric, guessUnit } from "../datasetGuess.js";
import {
  UNITLESS, countProblem, isUnitless, lateEntryWords, roleGroups, roleName, rolesOf, setRole, unitColumnWords, unitCounts,
} from "../lifeData.js";
import { COMMON_UNITS } from "./Units.jsx";

// The Data step's one table: each column's role is chosen in its heading,
// with what that role needs right under it (the time unit, what each status
// value means, a covariate's unit) and anything wrong with it, over the
// sheet's first rows. Nothing else maps a column, so a column has one role
// and one place to change it.
//
// ``idColumn`` names each unit ("Seal"): for the words only ("80 seals"),
// never sent with the fit. ``onChange({ mapping, covariates, idColumn },
// { col, role, meanings })``: ``meanings`` when a status value's meaning was
// set by hand. ``issues``: [{ col, text }] (lifeData.dataStepIssues);
// ``notes``: [{ col, text }] that don't stop the fit (lifeData.dataStepNotes);
// ``asides``: { col: node } shown under a column's heading (a question to
// answer). On a phone the role pickers stack above the rows, which scroll
// inside their card.

function UnitPick({ value, onChange, id }) {
  const none = isUnitless(value);
  return (
    <div className="dm-unit">
      <input
        className="units-input"
        type="text"
        list={id}
        aria-label="Time unit"
        value={none ? "" : value || ""}
        disabled={none}
        placeholder={none ? "No unit" : "Unit, e.g. Hours"}
        onChange={(e) => onChange(e.target.value)}
      />
      <datalist id={id}>
        {COMMON_UNITS.map((u) => <option value={u} key={u} />)}
      </datalist>
      <label className="ds-unitless">
        <input type="checkbox" checked={none} onChange={(e) => onChange(e.target.checked ? UNITLESS : "")} />
        No unit
      </label>
    </div>
  );
}

export default function DataMapper({
  columns, rows = [], facts = {}, mapping, covariates = [], idColumn = "", onChange,
  unit, onUnitChange, covUnits = {}, onCovUnit, timeVarying = null, covariatesAllowed = false,
  failureMode = false, issues = [], notes = [], asides = {},
}) {
  const phone = usePhone();
  const roles = rolesOf(columns, mapping, covariates, idColumn);
  const groups = roleGroups({ timeVarying, covariates: covariatesAllowed, failureMode });
  // The unit sits with the first time column: the single time, or the earliest.
  const unitCol = mapping.x || mapping.xl || mapping.xr;

  const optionsFor = (col) => {
    const role = roles[col];
    const option = (r) => {
      const why = r === "n" ? countProblem(facts[col])
        : r === "cov" && !isNumeric(facts[col]?.dtype) ? "text: use a formula"
        : r === "u" && !unitCounts(col, facts) ? "not time units" : null;
      const hint = why === "decimals" ? "has decimals" : why;
      return { value: r, label: roleName(r, timeVarying), ...(why && r !== role ? { hint, disabled: true } : {}) };
    };
    // A role set elsewhere (a group column, say) stays shown while it's this column's.
    const known = [...groups.common, ...groups.more];
    const extra = role && !known.includes(role) ? [role] : [];
    return [
      ...[...groups.common, ...extra].map(option),
      ...(groups.more.length ? [{ heading: "Less common" }, ...groups.more.map(option)] : []),
    ];
  };

  const pick = (col, role) => {
    const next = setRole({ mapping, covariates, idColumn }, col, role, facts);
    // A unit guessed from the old time column follows the new one.
    if (role === "x" && onUnitChange && (!unit || unit === guessUnit(mapping.x))) onUnitChange(guessUnit(col));
    onChange(next, { col, role });
  };

  // What a column's role needs, under its picker.
  const detail = (col) => {
    const role = roles[col];
    const out = [];
    if (col === unitCol && onUnitChange) {
      out.push(<UnitPick key="unit" value={unit} onChange={onUnitChange} id={`dm-units-${columns.indexOf(col)}`} />);
    }
    if (role === "c") {
      out.push(
        <StatusMeanings key="status" column={col} values={facts[col]?.values} blanks={facts[col]?.blanks || 0}
                        mapping={mapping} onChange={(m) => onChange({ mapping: m, covariates, idColumn }, { col, role, meanings: true })} />,
      );
    } else if (role === "e") {
      out.push(<span key="e" className="ds-hint">{facts[col]?.blanks ? "A blank mode is a unit still running." : "Each failure's mode, fitted as competing risks."}</span>);
    } else if (role === "n") {
      out.push(<span key="n" className="ds-hint">How many units share the row.</span>);
    } else if (role === "u") {
      const w = unitColumnWords(mapping, facts, unit);
      if (w?.note) out.push(<span key="u" className="ds-hint">{w.note}</span>);
    } else if (role === "tl") {
      out.push(<span key="tl" className="ds-hint">{lateEntryWords(col, facts)}</span>);
    } else if (role === "id") {
      out.push(<span key="id" className="ds-hint">Names each unit. Not used in the fit.</span>);
    } else if (role === "cov" && onCovUnit) {
      out.push(
        <input key="cov" className="dm-cov-unit" type="text" maxLength={24} aria-label={`Unit of ${col} (optional)`}
               placeholder="Unit (optional), e.g. °C" value={covUnits[col] || ""}
               onChange={(e) => onCovUnit(col, e.target.value)} />,
      );
    }
    for (const i of issues.filter((x) => x.col === col)) {
      out.push(<p key={i.text} className="dm-issue" role="status">{i.text}</p>);
    }
    for (const n of notes.filter((x) => x.col === col)) {
      out.push(<p key={n.text} className="dm-issue dm-note" role="status">{n.text}</p>);
    }
    if (asides[col]) out.push(<div key="aside" className="dm-aside">{asides[col]}</div>);
    return out;
  };

  const head = (col) => (
    <>
      <span className="dm-name" title={col}>{col}</span>
      <Select
        value={roles[col]}
        ariaLabel={`What “${col}” is`}
        className="dm-role"
        onChange={(role) => pick(col, role)}
        options={optionsFor(col)}
      />
      {detail(col)}
    </>
  );
  const hasIssue = (col) => issues.some((i) => i.col === col) || !!asides[col];
  const cellClass = (col) => ["dm-col", roles[col] ? "" : "ignored", hasIssue(col) ? "issue" : ""].filter(Boolean).join(" ");

  const body = rows.length > 0 && (
    <tbody>
      {rows.map((row, r) => (
        <tr key={r}>
          {columns.map((col, j) => {
            const cell = row[j];
            const shown = formatCell(cell);
            return (
              <td key={col} className={roles[col] ? undefined : "ignored"}
                  title={cell != null && shown !== String(cell) ? String(cell) : undefined}>
                {shown}
              </td>
            );
          })}
        </tr>
      ))}
    </tbody>
  );

  if (phone) {
    return (
      <div className="dm dm-phone">
        <ul className="dm-stack" aria-label="What each column is">
          {columns.map((col) => (
            <li key={col} className={cellClass(col)}>
              {head(col)}
              {facts[col]?.sample != null && <span className="dm-eg">e.g. {String(facts[col].sample)}</span>}
            </li>
          ))}
        </ul>
        {body && (
          <div className="dm-scroll">
            <table className="preview-table dm-table">
              <thead><tr>{columns.map((col) => <th key={col} className={roles[col] ? undefined : "ignored"}>{col}</th>)}</tr></thead>
              {body}
            </table>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="dm">
      <div className="dm-scroll">
        <table className="preview-table dm-table">
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col} scope="col" className={cellClass(col)}>
                  <div className="dm-head">{head(col)}</div>
                </th>
              ))}
            </tr>
          </thead>
          {body}
        </table>
      </div>
    </div>
  );
}
