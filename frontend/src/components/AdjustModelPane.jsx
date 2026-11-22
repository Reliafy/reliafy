import { useEffect, useRef, useState } from "react";
import { getModel, linkPositionModel } from "../api.js";
import TablePane from "./TablePane.jsx";
import AdjustModelPanel from "./AdjustModelPanel.jsx";
import Field from "./ui/Field.jsx";
import { Radio } from "./ui/Controls.jsx";
import Loading from "./ui/Loading.jsx";

// Adjust for conditions… on a model row of the Explorer's Modelling tab, in the table area (the tree
// kept beside it). The model is adjusted by a hazard ratio for the conditions at this position and
// saved as a new model (AdjustModelPanel); then it takes the row's place here (the default) or sits
// beside it. The original model is unchanged, and so is every other position and RBD that uses it.
//
//   position {id, name}   link  the model row (its model_id, failure_mode_ids)
//   onDone(link, text), onDirty, onSaving, phone, headingRef, onClose: TablePane's (paneProps)
export default function AdjustModelPane({ position, link, phone = false, headingRef = null, onClose, onDone, onDirty, onSaving }) {
  const [model, setModel] = useState(null);
  const [error, setError] = useState(null);
  const [replace, setReplace] = useState(true);
  const linked = useRef(null); // the new row, once linked
  useEffect(() => {
    let live = true;
    getModel(link.model_id).then((m) => live && setModel(m), (e) => live && setError(e.message));
    return () => { live = false; };
  }, [link.model_id]);
  const name = link.model?.name || link.name || "the model";
  const linkIt = async (doc) => {
    const made = await linkPositionModel(position.id, {
      model_id: doc.id, model_type: "model", failure_mode_ids: link.failure_mode_ids || [],
      ...(replace ? { replace_link_id: link.id } : {}),
    });
    return { made, text: replace
      ? `${doc.name} now takes ${name}'s place at ${position.name}. ${name} is unchanged.`
      : `${doc.name} is on ${position.name} beside ${name}.` };
  };
  return (
    <TablePane title="Adjust for conditions" subject={position.name} phone={phone} headingRef={headingRef} onClose={onClose}>
      {error && <p className="field-error adj" role="alert">{error}</p>}
      {!model && !error && <Loading />}
      {model && (
        <AdjustModelPanel model={model} onCancel={onClose} onDirty={onDirty} onSaving={onSaving}
                          saveLabel={replace ? "Save and use it here" : "Save and add it here"}
                          extraSave={async (doc) => {
                            const got = await linkIt(doc);
                            linked.current = got.made;
                            return got.text;
                          }}
                          onSaved={(_doc, text) => onDone(linked.current, text)}>
          <Field label={`At ${position.name}`} as="fieldset">
            <Radio name="adj-where" checked={replace} onChange={() => setReplace(true)}
                   label={`Use it here in place of ${name}`} />
            <Radio name="adj-where" checked={!replace} onChange={() => setReplace(false)}
                   label={`Add it beside ${name}`} />
          </Field>
        </AdjustModelPanel>
      )}
    </TablePane>
  );
}
