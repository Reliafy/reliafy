import { useEffect, useRef, useState } from "react";
import { rbdRepairableBlock } from "../api.js";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import Chip from "./ui/Chip.jsx";
import Field from "./ui/Field.jsx";
import { formatNumber } from "../format.js";
import { unitAbbr } from "./rbdModelText.js";
import { readRule } from "../rbdReplacement.js";
import "./RbdBlockOptions.css";

// "Repairs and replacement" (#367): a block on a fitted repairable model — how the unit fails
// between replacements — and when it's replaced with a new one. The server says whether the model
// can wear out (then a rule is required), the best rule for the block's costs (pre-filled once,
// marked Suggested) and how the long-run availability is worked out: exact or numerical is free,
// simulated is Pro, read from RePyability's own routes. Stored on the block as
// ``replacement: {rule: "none" | "age" | "repairs", age?, repairs?, duration?, cost?, suggested?}``.

const RULES = [
  { value: "age", label: "At an age", title: "Replace it with a new one when it reaches this age." },
  { value: "repairs", label: "After repairs", title: "Repair it this many times, then replace it at the next failure." },
  { value: "none", label: "Never", title: "Repair it for ever: only for a model that never wears out." },
];

// ``block``: the block as it stands in the dialog ({label, model, repair, instant_repair, costs});
// ``initial``: its saved rule; ``onChange({value, valid})``: the rule, or null for none.
export default function RbdRepairsReplacement({ block, initial, unit = "", onChange }) {
  const [rule, setRule] = useState(initial?.rule || "");
  const [age, setAge] = useState(initial?.age ?? "");
  const [repairs, setRepairs] = useState(initial?.repairs ?? "");
  const [duration, setDuration] = useState(initial?.duration ?? "");
  const [cost, setCost] = useState(initial?.cost ?? "");
  const [suggested, setSuggested] = useState(!!initial?.suggested);
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);
  const prefilled = useRef(!!initial?.rule);
  const seq = useRef(0);
  const u = unitAbbr(unit);

  const read = readRule(rule || "none", age, repairs, duration, cost);
  const value = rule ? (read.valid ? { ...read.value, ...(suggested ? { suggested: true } : {}) } : null) : null;
  const required = info?.rule_required;
  const missing = required && (!rule || rule === "none");
  const valid = read.valid && !missing;

  useEffect(() => {
    onChange({ value, valid });
  }, [rule, age, repairs, duration, cost, suggested, required]); // eslint-disable-line react-hooks/exhaustive-deps

  const apply = (r) => {
    setRule(r.rule);
    if (r.rule === "age") setAge(String(r.age));
    if (r.rule === "repairs") setRepairs(String(r.repairs));
    setSuggested(true);
  };

  // Ask the server about the block as it stands (debounced; the latest answer wins).
  const key = JSON.stringify([block, value]);
  useEffect(() => {
    if (!block?.model) return undefined;
    const n = ++seq.current;
    const t = setTimeout(() => {
      rbdRepairableBlock({ id: "block", type: "component", data: { ...block, replacement: value } }, unit)
        .then((out) => {
          if (n !== seq.current) return;
          setInfo(out);
          setError(null);
          // Decision 2 (15 Nov): a newly picked model starts on the optimiser's rule, marked Suggested.
          if (!prefilled.current && out.rule_offered) {
            prefilled.current = true;
            if (out.suggestion?.available) apply(out.suggestion.rule);
            else if (!out.rule_required) setRule("none");
          }
        })
        .catch((e) => { if (n === seq.current) { setError(e.message); setInfo(null); } });
    }, 250);
    return () => clearTimeout(t);
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const edit = (setter) => (e) => { setter(e.target.value); setSuggested(false); };
  const m = info?.model;
  const params = (m?.params || []).map((p) => `${p.name} ${formatNumber(p.value, { sig: 4 })}`).join(" · ");

  return (
    <section className="rbd-dlg-sec rbd-rr" aria-label="Repairs and replacement">
      <h3>Repairs and replacement</h3>
      {error && <p className="rbd-rr-problem" role="alert">! {error}</p>}
      {m && (
        <p className="rbd-rr-model">
          <b>{m.name}</b> <span className="muted">· {m.form_name}{params ? ` · ${params}` : ""}{u ? ` (${u})` : ""}</span>
        </p>
      )}
      {info && (
        <p className={"rbd-rr-verdict" + (info.verdict.never_wears_out ? " is-ok" : " is-warn")}>
          <span aria-hidden="true">{info.verdict.never_wears_out ? "✓ " : "! "}</span>{info.verdict.text}
        </p>
      )}
      {info && !info.rule_offered ? (
        <p className="hint">A constant rate never wears out, so it needs no replacement rule.</p>
      ) : (
        <>
          <Field label="Replace it with a new one"
                 error={missing ? "This model wears out: choose when it's replaced (or use the best rule)." : null}>
            <ChoiceChips label="Replace it with a new one" options={RULES} value={rule}
                         onChange={(v) => { setRule(v); setSuggested(false); }} />
          </Field>
          {rule === "age" && (
            <div className="param-fields">
              <label className="param-field">
                <span>Replace at age{u ? ` (${u})` : ""}</span>
                <input type="number" inputMode="decimal" step="any" min="0" value={age} aria-label="Replace at age"
                       onChange={edit(setAge)} />
              </label>
              <label className="param-field">
                <span>Replacement takes{u ? ` (${u})` : ""} <span className="muted">optional</span></span>
                <input type="number" inputMode="decimal" step="any" min="0" value={duration} placeholder="0"
                       aria-label="Planned replacement time" onChange={edit(setDuration)} />
              </label>
              <label className="param-field">
                <span>Replacement costs <span className="muted">optional</span></span>
                <input type="number" inputMode="decimal" step="any" min="0" value={cost}
                       placeholder="From Costs" aria-label="Planned replacement cost" onChange={edit(setCost)} />
              </label>
            </div>
          )}
          {rule === "repairs" && (
            <div className="param-fields">
              <label className="param-field">
                <span>Repairs before replacing</span>
                <input type="number" inputMode="numeric" step="1" min="0" value={repairs} aria-label="Repairs before replacing"
                       onChange={edit(setRepairs)} />
              </label>
            </div>
          )}
          {!read.valid && rule && <p className="rbd-rr-problem" role="alert">! {read.error}</p>}
          <div className="rbd-rr-suggest">
            {suggested && <Chip tone="accent">Suggested</Chip>}
            {info?.suggestion?.available ? (
              <>
                <span className="muted">
                  {suggested ? info.suggestion.words.replace(/^Suggested: /, "").replace(/^./, (c) => c.toUpperCase())
                    : info.suggestion.words}.
                </span>
                <button type="button" className="secondary sm" onClick={() => apply(info.suggestion.rule)}>
                  Find the best replacement rule
                </button>
              </>
            ) : info?.suggestion?.reason && info.rule_required ? (
              <span className="muted">{info.suggestion.reason}</span>
            ) : null}
          </div>
        </>
      )}
      {info?.band_note && <p className="hint">{info.band_note}</p>}
      {info?.route && (
        <p className="rbd-rr-route">
          <Chip tone={info.route.price === "pro" ? "warning" : "neutral"}>{info.route.words}</Chip>{" "}
          <span className="muted">
            {info.route.price === "pro"
              ? "Its long-run availability is simulated: a repair doesn't make it as good as new."
              : "Its long-run availability is worked out without simulation."}
          </span>
        </p>
      )}
      {(info?.problems || []).filter((p) => !(missing && p.includes("replacement needed"))).map((p) => (
        <p key={p} className="rbd-rr-problem" role="alert">! {p}</p>
      ))}
    </section>
  );
}
