import PartTypePicker from "./PartTypePicker.jsx";
import "../views/Predictions.css";
import { partTypeMode } from "../predictions.js";

// One parts-list line's type, three ways: a handbook part type (the picker), a rate of the
// user's own for a part the handbook doesn't have (a battery: shown as user-given), or "Not
// electronic" ticked, which leaves the line out of the total (an airframe, a propeller; the
// result names what was left out). The three pieces are exported so the same controls show
// stacked in one cell (PartTypeCell: the Predictions builder) or in a column each (the Explorer's
// prediction pane): a change to one shows in both.
//
//   record    the chosen library record or null      rate      the user's rate (per 10⁶ h), "" for none
//   rateMode  whether the rate box shows             excluded  whether the line is left out
//   onChange  ({ record?, rate?, rateMode?, excluded? })        name      the line's name, for labels

// The handbook part type: the picker; "Give a rate of your own instead" in its list switches to the rate.
export function PartTypeChoice({ name, record, onChange, onUseRate = null }) {
  return (
    <PartTypePicker value={record} label={`Handbook part type of ${name}`}
                    onChange={(rec) => onChange({ record: rec })}
                    onUseRate={() => { onChange({ record: null, rateMode: true }); onUseRate?.(); }} />
  );
}

// A rate of the user's own, per 10⁶ h. `onBack`: the × back to a handbook part type (in a cell);
// `disabled` with `why` when the line can't take one (a column beside a chosen part type).
export function OwnRate({ name, rate = "", onChange, onBack = null, id, disabled = false, why = "", placeholder = "Rate", unit = "per 10⁶ h · user-given" }) {
  return (
    <div className="ptc-rate">
      <input id={id} type="number" inputMode="decimal" min="0" step="any" value={rate ?? ""} placeholder={placeholder}
             disabled={disabled} title={why || undefined}
             aria-label={`Your own failure rate for ${name}, per million hours`}
             onChange={(e) => onChange({ rate: e.target.value, rateMode: true })} />
      <span className="ptc-unit">{unit}</span>
      {onBack && (
        <button type="button" className="ptp-clear" aria-label={`Use a handbook part type for ${name} instead`}
                title="Use a handbook part type instead"
                onClick={() => onBack()}>×</button>
      )}
    </div>
  );
}

// "Not electronic": ticked, the line is left out of the total (its part type and rate cleared).
export function NotElectronic({ name, excluded, onChange, children = "Not electronic" }) {
  return (
    <label className="ptc-exclude" title="Not an electronic part (an airframe, a propeller): the handbook has no rate for it, so it's left out of the total and the result says so.">
      <input type="checkbox" checked={Boolean(excluded)} aria-label={children ? undefined : `${name} is not electronic: leave it out`}
             onChange={(e) => onChange(e.target.checked
               ? { excluded: true, record: null, rate: "", rateMode: false }
               : { excluded: false })} />
      {children}
    </label>
  );
}

export default function PartTypeCell({ name, record, rate = "", rateMode = false, excluded = false, onChange }) {
  const mode = partTypeMode({ record, rate, rateMode, excluded });
  return (
    <div className="ptc">
      {mode === "excluded" ? (
        <span className="lib-date">Not electronic: left out of the total</span>
      ) : mode === "rate" ? (
        <OwnRate name={name} rate={rate} onChange={onChange} onBack={() => onChange({ rate: "", rateMode: false })} />
      ) : (
        <PartTypeChoice name={name} record={record} onChange={onChange} />
      )}
      <NotElectronic name={name} excluded={excluded} onChange={onChange} />
    </div>
  );
}
