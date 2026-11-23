import { useEffect, useRef, useState } from "react";
import { clearModeResponse, setModeResponse } from "../api.js";
import { saveErrorText } from "../confirm.js";
import { RESPONSE_WORDS, responseBody, responseFields, responseNote, responseValue } from "../failureCosts.js";
import { PanelField } from "./PanelField.jsx";
import { StepLabel } from "./RcmModeTasks.jsx";

// A failure mode's response, in the RCM tab's step 2 (forecast plan steps 3 and 4, Nov 2026): kind
// "failure", "If it fails anyway" (its corrective response), on every failure mode; kind "found", "If an
// inspection finds it" (its follow-on), on a mode with a check. Each is a task raised by that event
// (backend/maintenance/responses.py): what's done, its labour, its cost each time and the spare it fits.
// The forecast's failure lines take their hours, spares and cost from it; with none, it says so (a
// visible gap, never filled in). `focus`: opened from the forecast's "Not counted · Add" (?respond=).
// Grid rows of the panel's step grid (`rw-sg`), like FailureCostRows.
export default function ModeResponseRows({ modeId, kind = "failure", response, readOnly = false, focus = false, onChanged, onSaid }) {
  const words = RESPONSE_WORDS[kind];
  const [open, setOpen] = useState(!!response || focus);
  const [saved, setSaved] = useState({});
  const first = useRef(null);
  useEffect(() => { setOpen(!!response || focus); }, [modeId, kind, !!response, focus]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (focus && first.current) {
      first.current.scrollIntoView?.({ block: "center" });
      first.current.querySelector("input, textarea")?.focus();
    }
  }, [focus, open]);
  const save = (key, raw) => {
    const res = responseBody(key, raw);
    if (res.error) return res.error;
    return setModeResponse(modeId, kind, res.body).then((out) => {
      setSaved((s) => ({ ...s, [key]: (s[key] || 0) + 1 }));
      onChanged?.(out);
      onSaid?.(`Saved: ${words.title.toLowerCase()}.`);
      return true;
    }, (e) => saveErrorText(e, { offline: navigator.onLine === false }));
  };
  const remove = () => clearModeResponse(modeId, kind).then(() => {
    onChanged?.(null);
    setOpen(false);
    onSaid?.(`Removed: ${words.title.toLowerCase()}.`);
  }, () => onSaid?.("Couldn't remove it: try again."));
  return (
    <>
      <StepLabel>{words.title}</StepLabel>
      <div className="rw-sc fcost mresp" ref={first} data-kind={kind}>
        {!open ? (
          <p className="fcost-note">
            <span className="mresp-gap">! {words.none}</span>{" "}
            {!readOnly && <button type="button" className="link" onClick={() => setOpen(true)}>{words.add}</button>}
          </p>
        ) : (
          <>
            <div className="fcost-fields">
              {responseFields().map((f) => (
                <PanelField key={`${modeId}:${kind}:${f.key}`} label={f.label} help={f.help} type={f.type} suffix={f.suffix}
                            optional={f.optional} value={responseValue(response, f.key)} readOnly={readOnly}
                            placeholder={f.key === "cost" && response?.cost_each != null && response.cost_source !== "typed"
                              ? `From its LSA: ${response.cost_each}` : f.key === "name" ? "e.g. Replace the spindle" : null}
                            saved={saved[f.key] || 0} onCommit={(raw) => save(f.key, raw)} />
              ))}
            </div>
            <p className="fcost-note">
              {response ? responseNote(response) : "Type what's done first: the rest are kept as you leave each field."}
              {response && !readOnly && <> <button type="button" className="link" onClick={remove}>Remove</button></>}
            </p>
          </>
        )}
      </div>
    </>
  );
}
