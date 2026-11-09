import { useEffect, useRef, useState } from "react";
import { evaluateLibraryRecord } from "../api.js";
import Field from "./ui/Field.jsx";
import { TextInput } from "./ui/Controls.jsx";
import CovariateInputs from "./CovariateInputs.jsx";
import { cycleWord, fmtRate, perCycle, resultLine, unitShort, valuesForServer } from "../covariate.js";
import "./CovariateCalculator.css";

// A covariate model's inputs and its rate under them (NSWC-11): the record page's "Try it" and a
// prediction line's "Conditions…" are this one component (the same components rule). Each input
// shows its unit, its default (and where that comes from) and the handbook's limits; a value past a
// limit says which, and the page, as it's typed. The rate is the server's, asked a moment after
// each change: in total and for each part or failure mode, with the handbook's warnings.
//
//   recordId  the record           inputs    the record's covariate inputs (detail.covariate.inputs)
//   unit      its rate unit        values    {input key: text}     onChange(values)
//   cycles    (per-cycle rates, when given with onCycles) the cycles an hour typed; onCycles(text)
//   onResult  (result or null)     the latest evaluation, for a caller that shows it elsewhere

export default function CovariateCalculator({ recordId, inputs = [], unit, values = {}, onChange, cycles = null, onCycles = null, onResult = null, idPrefix = "cov" }) {
  const [answer, setAnswer] = useState(null); // {ok, result, warnings} | {ok:false, problems}
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  const sent = JSON.stringify(valuesForServer(values, inputs));

  useEffect(() => {
    const mine = ++seq.current;
    setBusy(true);
    const t = setTimeout(() => {
      evaluateLibraryRecord(recordId, JSON.parse(sent)).then((d) => {
        if (mine !== seq.current) return;
        setBusy(false);
        setError(null);
        setAnswer(d);
        onResult?.(d.ok ? d.result : null);
      }, (e) => {
        if (mine !== seq.current) return;
        setBusy(false);
        setError(e.message);
      });
    }, 250);
    return () => clearTimeout(t);
  }, [recordId, sent]); // eslint-disable-line react-hooks/exhaustive-deps

  const cyc = perCycle(unit) && onCycles;
  const cph = Number(cycles);
  const perHour = answer?.ok && cyc && cph > 0 ? answer.result.total * cph : null;

  return (
    <div className="cov">
      <div className="cov-inputs">
        <CovariateInputs inputs={inputs} values={values} onChange={onChange} idPrefix={idPrefix} />
        {cyc && (
          <fieldset className="cov-group">
            <legend className="cov-legend">How often it works</legend>
            <Field id={`${idPrefix}-cycles`} label={`${cycleWord(unit) === "operations" ? "Operations" : "Cycles"} an hour`}
                   help={`Its rate is ${unitShort(unit)}: the prediction needs how many ${cycleWord(unit)} it makes an hour to give a rate per hour.`}
                   error={String(cycles ?? "").trim() !== "" && !(cph > 0) ? "A number more than 0." : null}>
              <span className="cov-num">
                <TextInput inputMode="decimal" value={cycles ?? ""} placeholder="Needed" onChange={(e) => onCycles(e.target.value)} />
                <span className="cov-unit">per hour</span>
              </span>
            </Field>
          </fieldset>
        )}
      </div>
      <div className="cov-out" role="status" aria-live="polite">
        {error && <p className="field-error">{error}</p>}
        {!answer && !error && <p className="rim-tquiet">Working it out…</p>}
        {answer && !answer.ok && (
          <div className="cov-problems">
            <p className="cov-head">{answer.problems.some((p) => p.includes(" is needed")) ? "Needs these before it gives a rate:" : "Can’t give a rate for these inputs:"}</p>
            <ul>{answer.problems.map((p) => <li key={p}>{p}</li>)}</ul>
          </div>
        )}
        {answer?.ok && (
          <>
            <p className="cov-big"><b>{fmtRate(answer.result.total)}</b> {unitShort(answer.result.unit).replace("per ", "failures per ")}{busy ? <span className="rw-sum"> · updating…</span> : null}</p>
            {perHour != null && <p className="cov-sub">= <b>{fmtRate(perHour)}</b> failures per 10⁶ h at {fmtRate(cph)} {cycleWord(unit)} an hour</p>}
            {cyc && !(cph > 0) && <p className="cov-sub">Give the {cycleWord(unit)} an hour to turn it into a rate per hour.</p>}
            {answer.result.modes.length > 1 && (
              <ul className="cov-modes">
                {answer.result.modes.map((m) => (
                  <li key={m.key}><span>{m.name}{m.count !== 1 ? ` (×${m.count})` : ""}{m.scale != null ? ` (× ${fmtRate(m.scale)} ${m.scale_label || "an hour"})` : ""}</span><span className="num">{fmtRate(m.rate)}</span></li>
                ))}
              </ul>
            )}
            {answer.result.modes.length === 1 && answer.result.modes[0].factors?.length > 0 && (
              <p className="cov-sub">{answer.result.modes[0].base.symbol} {fmtRate(answer.result.modes[0].base.value)} × {answer.result.modes[0].factors.map((f) => `${f.symbol} ${fmtRate(f.value)}`).join(" × ")}</p>
            )}
            {answer.warnings?.length > 0 && (
              <div className="cov-warnings">
                <p className="cov-head">Outside the handbook’s limits or flagged by its cautions, so treat it with care:</p>
                <ul>{answer.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
              </div>
            )}
            <span className="sr-only">{resultLine(answer.result)}</span>
          </>
        )}
      </div>
    </div>
  );
}
