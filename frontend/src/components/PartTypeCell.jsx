import PartTypePicker from "./PartTypePicker.jsx";
import "../views/Predictions.css";

// One parts-list line's type, three ways: a handbook part type (the picker), a rate of the
// user's own for a part the handbook doesn't have (a battery: shown as user-given), or "Not
// electronic" ticked, which leaves the line out of the total (an airframe, a propeller; the
// result names what was left out).
//
//   record    the chosen library record or null      rate      the user's rate (per 10⁶ h), "" for none
//   rateMode  whether the rate box shows             excluded  whether the line is left out
//   onChange  ({ record?, rate?, rateMode?, excluded? })        name      the line's name, for labels
export default function PartTypeCell({ name, record, rate = "", rateMode = false, excluded = false, onChange }) {
  const usingRate = !excluded && (rateMode || String(rate ?? "") !== "");
  return (
    <div className="ptc">
      {excluded ? (
        <span className="lib-date">Not electronic: left out of the total</span>
      ) : usingRate ? (
        <div className="ptc-rate">
          <input type="number" inputMode="decimal" min="0" step="any" value={rate ?? ""} placeholder="Rate"
                 aria-label={`Your own failure rate for ${name}, per million hours`}
                 onChange={(e) => onChange({ rate: e.target.value })} />
          <span className="ptc-unit">per 10⁶ h · user-given</span>
          <button type="button" className="ptp-clear" aria-label={`Use a handbook part type for ${name} instead`}
                  title="Use a handbook part type instead"
                  onClick={() => onChange({ rate: "", rateMode: false })}>×</button>
        </div>
      ) : (
        <PartTypePicker value={record} label={`Handbook part type of ${name}`}
                        onChange={(rec) => onChange({ record: rec })}
                        onUseRate={() => onChange({ record: null, rateMode: true })} />
      )}
      <label className="ptc-exclude" title="Not an electronic part (an airframe, a propeller): the handbook has no rate for it, so it's left out of the total and the result says so.">
        <input type="checkbox" checked={Boolean(excluded)}
               onChange={(e) => onChange(e.target.checked
                 ? { excluded: true, record: null, rate: "", rateMode: false }
                 : { excluded: false })} />
        Not electronic
      </label>
    </div>
  );
}
