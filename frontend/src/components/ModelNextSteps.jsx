import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Modal from "./Modal.jsx";
import Select from "./Select.jsx";
import { getModel, listRbds } from "../api.js";
import { STEP_LABELS, STEP_WHAT, nextStepLink, nextStepsFor, plainName, savedModelRef, stepsFor } from "../modelNext.js";

// "Use this model" (#294): the tools a fitted non-repairable model feeds, each opened
// with the model chosen. One quiet button in the panel beside the plot
// (``variant="button"``) that opens a dialog listing them, each with what you
// get there, the same as the model page's main button (``variant="primary"``),
// or items for the saved model's ⋯ menu (``variant="menu"``). A
// saved model is ``modelId``; a fit not saved yet passes ``onUse``
// (() => Promise<saved id>), which saves it first.
// ``skip`` leaves steps out.

// Open a step: resolve the model's id (saving a fresh fit), then navigate.
export function useNextStep({ result, modelId = null, onUse = null }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [rbdOpen, setRbdOpen] = useState(false);

  const resolve = async () => modelId || (onUse ? await onUse() : null);

  const go = async (step, rbdId = null) => {
    setError(null);
    setBusy(step);
    try {
      const id = await resolve();
      if (!id) throw new Error("Save the model first.");
      if (step === "rbd") {
        const full = await getModel(id);
        navigate(rbdId ? `/systems/b/${rbdId}` : "/systems/b", { state: { addModel: savedModelRef({ ...full, id }) } });
      } else {
        navigate(nextStepLink(step, id, { unit: result?.unit || "" }));
      }
    } catch (err) {
      setError(err.message);
      setBusy(null);
    }
  };

  const open = (step) => (step === "rbd" ? setRbdOpen(true) : go(step));
  const modal = rbdOpen && (
    <AddToRbdModal
      busy={busy === "rbd"}
      error={error}
      onClose={() => { setRbdOpen(false); setError(null); }}
      onAdd={(rbdId) => go("rbd", rbdId)}
    />
  );
  return { open, busy, error: rbdOpen ? null : error, modal };
}

export default function ModelNextSteps({ result, modelId = null, onUse = null, skip = [], variant = "button" }) {
  const [listOpen, setListOpen] = useState(false);
  const { open, busy, error, modal } = useNextStep({ result, modelId, onUse });
  if (!modelId && !onUse) return null;
  const steps = stepsFor(result, skip);
  if (!steps.length) return null;

  if (variant === "menu") {
    return (
      <>
        {steps.map((s) => (
          <button key={s} type="button" className="ovm-item" onClick={() => open(s)} disabled={!!busy}>
            {STEP_LABELS[s]}
          </button>
        ))}
        {modal}
      </>
    );
  }
  // The diagram picker replaces the list rather than opening over it.
  const pick = (s) => {
    if (s === "rbd") setListOpen(false);
    open(s);
  };
  return (
    <>
      {variant === "primary" ? (
        // The model page's main action, top right (the frame's header).
        <button type="button" className="use-model-primary" onClick={() => setListOpen(true)} aria-haspopup="dialog">
          Use this model
        </button>
      ) : (
        <button type="button" className="secondary use-model-btn" onClick={() => setListOpen(true)}
                aria-haspopup="dialog">
          <span>Use this model</span>
          <span aria-hidden="true">›</span>
        </button>
      )}
      {listOpen && (
        <Modal title="Use this model" className="modal-sm use-model-modal" onClose={() => setListOpen(false)}
               locked={!!busy && busy !== "rbd"}>
          <p className="muted-line use-model-intro">Open a tool with this model already chosen.</p>
          <ul className="use-model-list">
            {steps.map((s) => (
              <li key={s}>
                <button type="button" className="use-model-step" onClick={() => pick(s)} disabled={!!busy}>
                  <span className="use-model-step-name">
                    {busy === s ? "Opening…" : STEP_LABELS[s]}
                    <span aria-hidden="true"> ›</span>
                  </span>
                  <span className="use-model-step-what">{STEP_WHAT[s]}</span>
                </button>
              </li>
            ))}
          </ul>
          {!modelId && <p className="muted-line use-model-note">Saves the model first, under the name beside Save.</p>}
          {error && <p className="error use-model-note" role="alert">{error}</p>}
        </Modal>
      )}
      {modal}
    </>
  );
}

// The replacement-interval action under the wear-out reading.
export function ReplacementLink({ result, modelId = null, onUse = null }) {
  const { open, busy, error } = useNextStep({ result, modelId, onUse });
  if ((!modelId && !onUse) || !nextStepsFor(result).replacement) return null;
  return (
    <>
      <button type="button" className="link life-reading-action" onClick={() => open("replacement")} disabled={!!busy}>
        {busy ? "Opening…" : `${STEP_LABELS.replacement} ›`}
      </button>
      {error && <span className="error life-reading-error" role="alert">{error}</span>}
    </>
  );
}

// Which diagram to add the block to: a new one, or one of the user's own.
function AddToRbdModal({ busy, error, onClose, onAdd }) {
  const [rbds, setRbds] = useState(null);
  const [target, setTarget] = useState("");
  useEffect(() => {
    listRbds()
      .then((d) => setRbds((d.rbds || []).filter((r) => !r.read_only)))
      .catch(() => setRbds([]));
  }, []);
  return (
    <Modal
      title="Add to an RBD"
      className="modal-sm"
      onClose={onClose}
      locked={busy}
      footer={
        <div className="row" style={{ margin: 0, marginLeft: "auto" }}>
          <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="button" onClick={() => onAdd(target || null)} disabled={busy || rbds === null}>
            {busy ? "Opening…" : "Add block"}
          </button>
        </div>
      }
    >
      <label className="login-field">
        <span>Diagram</span>
        <Select
          value={target}
          onChange={setTarget}
          options={[
            { value: "", label: "A new diagram" },
            ...(rbds || []).map((r) => ({ value: r.id, label: plainName(r.name) || "Untitled RBD" })),
          ]}
        />
      </label>
      <p className="muted-line">
        {target
          ? "The block is added below the others, not wired in yet: connect it where it belongs, then Save."
          : "A new diagram with this block from Input to Output, ready to calculate."}
      </p>
      {error && <div className="error">{error}</div>}
    </Modal>
  );
}
