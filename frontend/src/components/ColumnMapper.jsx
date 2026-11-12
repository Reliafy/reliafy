import Select from "./Select.jsx";
import StatusMeanings from "./StatusMeanings.jsx";
import { COMMON_UNITS } from "./Units.jsx";
import { guessUnit } from "../datasetGuess.js";
import {
  UNITLESS, countProblem, isUnitless, issueRow, lateEntryWords, setMappingField, statusCodesOnly, unitColumnWords,
} from "../lifeData.js";
import { TVC_STATUS } from "./TvcColumns.jsx";

// The Data step's selectors, one per SurPyval input, each with its label (i,
// x, xl, xr, c, n, tl, tr, m) and a few plain words, for every flow that maps
// columns: non-repairable life, repairable, accelerated life, condition and
// life (both tables) and degradation. The words never assume time: x is the
// value when a unit failed or was removed, in hours, cycles, km, volts…
//
//   i   [column]                                    which item each row belongs to
//   x   [column]                                    unit [hours]
//       where x is blank, a range: xl [column] to xr [column]
//   m   [column]                                    unit [mm]
//   c   [column]  0 = failed, 1 = running   [ ] my column uses 1 = failed
//   n   [column]
//   tl  [column]  late entry: observed only from this value
//   tr  [column]  observed only up to this value
//   failure mode [column]
//
// ``rows``: which rows a flow shows, in order (LIFE_ROWS by default); a fit
// that doesn't take an input never shows its row. ``range``: x's range
// (xl to xr) inside the x row. ``keys``: the mapping field behind a row where
// a flow names it differently ({ i: "id", x: "age", m: "value", e: "mode" }).
// ``words``: a flow's own plain words for a row; ``none``: its "— none —".
// x and the range are read per row: x filled is an exact value, x blank its
// range (only a range, with no x, is inspection data). ``issues`` / ``notes``:
// [{ col, text, row? }], each shown by the row it concerns (``row``, or
// lifeData.issueRow). ``asides``: { row: [node] }, a question to answer
// there; ``warning``: a node shown loud on the x row. ``facts`` (column →
// dtype, values…) lets c show its codes and how words were read
// (``meanings``: false where the fit takes 0/1 codes only; ``invertible``:
// false where it can't flip a 1 = failed column). ``lifeRules``: false for a
// flow whose mapping isn't a life mapping (lifeData's rules don't apply).
// ``timeVarying`` ("intervals" | "timeline", #60): an item column and each
// row's times take x's place, with no count or late entry. ``top``: a row
// shown first, the "dataset" selector that splits a sheet (DatasetSplit.jsx).
export const LIFE_ROWS = ["x", "c", "n", "tl", "tr", "e"];

const WORDS = {
  i: "which item each row belongs to",
  x: "the value when it failed or was removed",
  m: "the measured value",
  c: "failed or still running",
  n: "how many units the row stands for",
  tl: "late entry: observed only from this value",
  tr: "observed only up to this value",
  e: "optional, competing risks",
};
const LABELS = { e: "failure mode" };

export default function ColumnMapper({
  columns, mapping, onChange, unit, onUnitChange, facts = {}, timeVarying = null, failureMode = false,
  issues = [], notes = [], asides = {}, warning = null,
  rows = null, range = true, keys = {}, words = {}, none = {}, meanings: showMeanings = true,
  mUnit, onMUnitChange, codeWords = "0 = failed, 1 = running", invertible = true, lifeRules = null, top = null,
}) {
  const shown = rows || (failureMode ? LIFE_ROWS : LIFE_ROWS.filter((r) => r !== "e"));
  const k = (role) => keys[role] || role;
  const val = (role) => mapping[k(role)] || "";
  const options = (label) => [{ value: "", label }, ...columns];
  const hasRange = range && !!(val("xl") || val("xr"));
  // The life rules (status meanings guessed, issueRow) unless a flow says otherwise.
  const lifeKeys = lifeRules ?? !Object.keys(keys).length;

  const setField = (role, value) => {
    const field = k(role);
    // Life mappings: status meanings guessed afresh, no groups without modes (lifeData).
    const next = lifeKeys ? setMappingField(mapping, field, value, facts) : { ...mapping, [field]: value };
    // A unit guessed from the old value column follows the new one.
    const first = role === "x" || (role === "xl" && !val("x"));
    if (first && onUnitChange && (!unit || unit === guessUnit(val(role)))) onUnitChange(guessUnit(value));
    onChange(next);
  };

  // A count holds whole numbers (#434): a column of text or decimals is
  // shown, but can't be picked, with the reason beside it.
  const countOptions = (label) => [
    { value: "", label },
    ...columns.map((col) => {
      const why = countProblem(facts[col]);
      return why ? { value: col, label: col, hint: why === "text" ? "text" : "has decimals", disabled: col !== val("n") } : col;
    }),
  ];

  const pick = (role, noneLabel, aria) => (
    <Select value={val(role)} onChange={(v) => setField(role, v)} ariaLabel={aria || role}
            className="xcn-pick" options={role === "n" && facts[columns[0]] ? countOptions(noneLabel) : options(noneLabel)} />
  );

  // What a row says beneath it: problems (stop the fit), notes, questions.
  const rowOf = (x) => x.row || (lifeKeys ? issueRow(x, mapping) : "x");
  const below = (row) => {
    const out = [];
    for (const i of issues.filter((x) => rowOf(x) === row)) {
      out.push(<p key={`i${i.text}`} className="xcn-issue" role="status">{i.text}</p>);
    }
    for (const n of notes.filter((x) => rowOf(x) === row)) {
      out.push(<p key={`n${n.text}`} className="xcn-issue xcn-note" role="status">{n.text}</p>);
    }
    for (const a of asides[row] || []) out.push(a);
    return out.length ? <div className="xcn-below">{out}</div> : null;
  };

  const unitBox = (value, onSet, id, aria, placeholder) => onSet && (
    <span className="xcn-unit">
      <span className="xcn-words">unit</span>
      <input className="units-input" type="text" list={id} aria-label={aria}
             value={isUnitless(value) ? "" : value || ""} disabled={isUnitless(value)}
             placeholder={isUnitless(value) ? "No unit" : placeholder}
             onChange={(e) => onSet(e.target.value)} />
      <datalist id={id}>{COMMON_UNITS.map((u) => <option value={u} key={u} />)}</datalist>
      <label className="ds-unitless">
        <input type="checkbox" checked={isUnitless(value)} onChange={(e) => onSet(e.target.checked ? UNITLESS : "")} />
        no unit
      </label>
    </span>
  );
  const xUnit = unitBox(unit, onUnitChange, "xcn-units", "Unit of the values", "hours, cycles, km…");
  // A column of per-row units (hrs / days), guessed or picked from a question.
  const perRow = !timeVarying && mapping.u ? unitColumnWords(mapping, facts, unit) : null;

  const key = (role, text) => (
    <span className="xcn-key">
      <code>{LABELS[role] || role}</code>
      {text && <span className="xcn-words">{text}</span>}
    </span>
  );
  const say = (role) => words[role] ?? WORDS[role];

  // c: 0 = failed, 1 = still running, with the flip for a 1 = failed column.
  const cCol = val("c");
  const codesOnly = cCol && statusCodesOnly(facts[cCol]?.values);
  const codes = () => {
    if (!cCol || !codesOnly || !invertible) {
      return cCol && showMeanings && !codesOnly ? null : <span className="xcn-words">{codeWords}</span>;
    }
    return (
      <>
        <span className="xcn-words">{codeWords}</span>
        <label className="xcn-tick">
          <input type="checkbox" checked={!!mapping.c_invert}
                 onChange={(e) => onChange({ ...mapping, c_invert: e.target.checked, c_map: null }, { meanings: true })} />
          my column uses 1 = failed
        </label>
      </>
    );
  };
  // A status column of words: how each was read, one short line.
  const meanings = () => {
    if (!cCol || codesOnly || !showMeanings || !facts[cCol]) return null;
    return (
      <div className="xcn-sub">
        <span className="xcn-words">0 = failed, 1 = running. Read as:</span>
        <StatusMeanings compact column={cCol} values={facts[cCol]?.values} blanks={facts[cCol]?.blanks || 0}
                        mapping={mapping} onChange={(m) => onChange(m, { meanings: true })} />
      </div>
    );
  };

  if (timeVarying) {
    // Covariates that change over time (#60): the item, each row's times, the status.
    return (
      <div className="xcn">
        <div className="xcn-row">
          {key("i", "the pump, motor or unit each row belongs to")}
          <div className="xcn-fields">{pick("i", "— pick a column —", "Item")}{xUnit}</div>
          {below("x")}
        </div>
        <div className="xcn-row">
          {timeVarying === "intervals" ? (
            <>
              {key("xl", "where the row starts")}
              <div className="xcn-fields">
                {pick("xl", "— pick a column —", "Start of the row")}
                <code>xr</code><span className="xcn-words">where it ends</span>
                {pick("xr", "— pick a column —", "End of the row")}
              </div>
            </>
          ) : (
            <>
              {key("x", "when the row's values take effect")}
              <div className="xcn-fields">{pick("x", "— pick a column —", "Value of the row")}</div>
            </>
          )}
        </div>
        <div className="xcn-row">
          {key("c", TVC_STATUS[timeVarying])}
          <div className="xcn-fields">{pick("c", "— none: every item failed —", "c")}{codes()}</div>
          {meanings()}
          {below("c")}
        </div>
      </div>
    );
  }

  const ROW = {
    i: () => (
      <div className="xcn-row" key="i">
        {key("i", say("i"))}
        <div className="xcn-fields">{pick("i", none.i || "— pick a column —", "i")}</div>
        {below("i")}
      </div>
    ),
    x: () => (
      <div className="xcn-row" key="x">
        {key("x", say("x"))}
        <div className="xcn-fields">
          {pick("x", hasRange ? "— none: every row is a range —" : none.x || "— pick a column —", "x")}
          {xUnit}
        </div>
        {range && (
          <div className="xcn-sub xcn-range">
            <span className="xcn-words">where x is blank, a range:</span>
            <span className="xcn-pair">
              <code>xl</code>{pick("xl", "— none —", "xl, the last value it was seen working")}
              <span className="xcn-words">to</span>
              <code>xr</code>{pick("xr", "— none —", "xr, the value it was found failed")}
            </span>
            <span className="xcn-words xcn-hint">xl: last seen working · xr: found failed (blank: still running)</span>
          </div>
        )}
        {perRow?.note && (
          <p className="xcn-note-line">
            {perRow.note}{" "}
            <button type="button" className="link" onClick={() => onChange({ ...mapping, u: "" })}>Don't convert</button>
          </p>
        )}
        {warning}
        {below("x")}
      </div>
    ),
    m: () => (
      <div className="xcn-row" key="m">
        {key("m", say("m"))}
        <div className="xcn-fields">
          {pick("m", none.m || "— pick a column —", "m")}
          {unitBox(mUnit, onMUnitChange, "xcn-m-units", "Unit of m", "mm, %, mm/s…")}
        </div>
        {below("m")}
      </div>
    ),
    c: () => (
      <div className="xcn-row" key="c">
        {key("c", say("c"))}
        <div className="xcn-fields">
          {pick("c", hasRange ? "— none: read from the values —" : none.c || "— none: every row failed —", "c")}
          {codes()}
        </div>
        {meanings()}
        {below("c")}
      </div>
    ),
    n: () => (
      <div className="xcn-row" key="n">
        {key("n", say("n"))}
        <div className="xcn-fields">{pick("n", none.n || "— none —", "n")}</div>
        {below("n")}
      </div>
    ),
    tl: () => (
      <div className="xcn-row" key="tl">
        {key("tl", say("tl"))}
        <div className="xcn-fields">
          {pick("tl", none.tl || "— none —", "tl")}
          {val("tl") && facts[val("tl")] && <span className="xcn-words">{lateEntryWords(val("tl"), facts)}</span>}
        </div>
        {below("tl")}
      </div>
    ),
    tr: () => (
      <div className="xcn-row" key="tr">
        {key("tr", say("tr"))}
        <div className="xcn-fields">
          {pick("tr", none.tr || "— none —", "tr")}
          {val("tr") && <span className="xcn-words">same unit as x; a blank is no limit on that row</span>}
        </div>
        {below("tr")}
      </div>
    ),
    e: () => (
      <div className="xcn-row" key="e">
        {key("e", say("e"))}
        <div className="xcn-fields">
          {pick("e", none.e || "— none —", "Failure mode")}
          {val("e") && facts[val("e")]?.blanks > 0 && (
            <span className="xcn-words">a blank mode is a unit still running</span>
          )}
        </div>
        {below("e")}
      </div>
    ),
  };

  return <div className="xcn">{top}{shown.map((r) => ROW[r]())}</div>;
}
