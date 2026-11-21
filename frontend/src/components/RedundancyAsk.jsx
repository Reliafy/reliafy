import ChoiceChips from "./ui/ChoiceChips.jsx";
import Field from "./ui/Field.jsx";
import { Select } from "./ui/Controls.jsx";
import { HOW, setKey, setNames } from "../redundancyAsk.js";
import "./RedundancyAsk.css";

// Asked before an RBD is built from a structure: for each set of positions inside that look like
// units of one job and aren't marked as a redundancy set, how they work together. Nothing is
// assumed: the build waits for an answer to each. Parallel and standby answers are saved on the
// tree as redundancy sets (shown there, and used by every rebuild).
//   sets [{position_ids, names}]   answers {[key]: {how, k}}   onChange(answers)   tried: show what's missing
export default function RedundancyAsk({ sets, answers, onChange, disabled = false, tried = false }) {
  if (!sets?.length) return null;
  const set = (s, patch) => onChange({ ...answers, [setKey(s)]: { ...(answers[setKey(s)] || {}), ...patch } });
  return (
    <div className="rask" role="group" aria-label="How look-alike positions work together">
      <p className="rask-lede">These look like units of one job. Say how they work together, so the diagram
        isn't wired as if every one were needed.</p>
      {sets.map((s) => {
        const a = answers[setKey(s)] || {};
        const n = s.position_ids.length;
        return (
          <div className="rask-set" key={setKey(s)}>
            <Field label={setNames(s)} error={tried && !a.how ? "Choose one." : null}>
              <ChoiceChips label={setNames(s)} options={HOW} value={a.how || ""} disabled={disabled}
                           onChange={(how) => set(s, { how })} />
            </Field>
            {a.how && a.how !== "series" && n > 2 && (
              <Field label={a.how === "standby" ? "How many run at once" : "How many are needed"}>
                <Select value={String(a.k || 1)} disabled={disabled} onChange={(e) => set(s, { k: Number(e.target.value) })}>
                  {Array.from({ length: n - 1 }, (_, i) => i + 1).map((k) => (
                    <option key={k} value={k}>{k} of {n}</option>
                  ))}
                </Select>
              </Field>
            )}
          </div>
        );
      })}
    </div>
  );
}
