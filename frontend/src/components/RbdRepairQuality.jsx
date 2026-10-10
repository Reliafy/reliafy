import { useEffect, useState } from "react";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import "./RbdBlockOptions.css";

// How good a repairable block's repairs are (#68): as good as new (the
// default), or imperfect by Kijima's virtual age — I: a repair takes away
// part of the wear since the last repair; II: part of all the wear so far —
// with a restoration factor q, and optionally replacement at the N-th
// failure since the block was renewed. Stored on the block as
// ``repair_quality: {model: "kijima1" | "kijima2", q, replace_after?}``.

const MODELS = [
  { value: "perfect", label: "As good as new",
    hint: "Every repair leaves the block as good as new." },
  { value: "kijima1", label: "Kijima I",
    hint: "Each repair removes part of the wear since the last repair. q = 0 is as good as new, q = 1 as bad as old." },
  { value: "kijima2", label: "Kijima II",
    hint: "Each repair removes part of all the wear so far. q = 0 is as good as new, q = 1 as bad as old." },
];

const ordinal = (n) => {
  const s = n % 100 >= 11 && n % 100 <= 13 ? "th" : { 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th";
  return `${n}${s}`;
};

export function repairQualitySummary(rq) {
  if (!rq || !rq.model || rq.model === "perfect") return "As good as new";
  const name = rq.model === "kijima1" ? "Kijima I" : "Kijima II";
  const n = Number(rq.replace_after);
  return `${name}, q = ${rq.q}${n >= 1 ? ` · replaced at the ${ordinal(n)} failure` : ""}`;
}

// ``onChange({value, valid})``: value null for perfect repair.
export default function RbdRepairQuality({ initial, onChange }) {
  const [model, setModel] = useState(initial?.model || "perfect");
  const [q, setQ] = useState(initial?.q ?? 0.5);
  const [n, setN] = useState(initial?.replace_after ?? "");

  const qNum = Number(q);
  const nNum = Number(n);
  const imperfect = model !== "perfect";
  const validQ = !imperfect || (q !== "" && Number.isFinite(qNum) && qNum >= 0 && qNum <= 1);
  const hasN = n !== "" && n != null;
  const validN = !imperfect || !hasN || (Number.isInteger(nNum) && nNum >= 1 && nNum <= 1000 && qNum > 0);
  const valid = validQ && validN;

  useEffect(() => {
    const value = imperfect
      ? { model, q: qNum, ...(hasN && validN ? { replace_after: nNum } : {}) }
      : null;
    onChange({ value: valid ? value : null, valid });
  }, [model, q, n]); // eslint-disable-line react-hooks/exhaustive-deps

  const summary = repairQualitySummary(imperfect ? { model, q: qNum, replace_after: hasN ? nNum : null } : null);
  return (
    <details className="rbd-dlg-fold rbd-rq" open={imperfect || undefined}>
      <summary>
        Repair quality <span className="muted"> · {summary}</span>
      </summary>
      <div className="rbd-dlg-fold-body">
        <SegmentedControl label="Repair quality" value={model} onChange={setModel}
                          options={MODELS.map(({ value, label }) => ({ value, label }))} />
        <p className="hint">{MODELS.find((m) => m.value === model).hint}</p>
        {imperfect && (
          <>
            <div className="param-fields">
              <label className="param-field" title="0 as good as new, 1 as bad as old (a minimal repair).">
                <span>Restoration factor q</span>
                <input type="number" step="any" min="0" max="1" value={q} aria-label="Restoration factor q"
                       onChange={(e) => setQ(e.target.value)} />
              </label>
              <label className="param-field" title="Replace the unit, as new, at this failure since it was renewed. Leave blank to always repair.">
                <span>Replace at failure no.</span>
                <input type="number" step="1" min="1" value={n} placeholder="Never" aria-label="Replace at failure number"
                       onChange={(e) => setN(e.target.value)} />
              </label>
            </div>
            {!validQ && <p className="hint">q must be from 0 to 1.</p>}
            {validQ && !validN && (
              <p className="hint">
                {qNum > 0 ? "The failure number must be a whole number, 1 or more." : "Replacing at a failure needs q above 0."}
              </p>
            )}
            <p className="hint">
              A block repaired this way has no exact long-run figures: its availability and costs are simulated.
              A replacement charges the replacement cost, every failure the repair cost.
            </p>
          </>
        )}
      </div>
    </details>
  );
}
