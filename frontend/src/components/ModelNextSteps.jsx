import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Modal from "./Modal.jsx";
import Select from "./Select.jsx";
import { getModel, listRbds } from "../api.js";
import { nextStepLink, nextStepsFor, plainName, savedModelRef } from "../modelNext.js";

// "Use this model" (#294): the tools a fitted non-repairable model feeds, each opened
// with the model chosen. A quiet card at the foot of the panel beside the
// plot (``variant="card"``), or items for the saved model's ⋯ menu
// (``variant="menu"``). A saved model is ``modelId``; a fit not saved yet
// passes ``onUse`` (() => Promise<saved id>), which saves it first.
// ``skip`` leaves steps out (the replacement interval, when it already sits
// beside the wear-out reading).

export const STEP_LABELS = {
  replacement: "Find the best replacement interval",
  fleet: "Forecast a fleet",
  test: "Plan a demonstration test",
  rbd: "Add to an RBD",
};
// The panel is narrow: one line a row.
const SHORT = { ...STEP_LABELS, replacement: "Find a replacement interval" };

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

export default function ModelNextSteps({ result, modelId = null, onUse = null, skip = [], variant = "card" }) {
  const { open, busy, error, modal } = useNextStep({ result, modelId, onUse });
  if (!modelId && !onUse) return null;
  const can = nextStepsFor(result);
  const steps = Object.keys(STEP_LABELS).filter((s) => can[s] && !skip.includes(s));
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
  return (
    <div className="gof-card next-steps">
      <div className="gofh">Use this model</div>
      {steps.map((s) => (
        <button key={s} type="button" className="gofr gofr-link next-step" onClick={() => open(s)} disabled={!!busy}>
          <span>{busy === s ? "Opening…" : SHORT[s]}</span>
          <span className="gv" aria-hidden="true">›</span>
        </button>
      ))}
      {!modelId && <p className="next-steps-note">Saves the model first, under the name beside Save.</p>}
      {error && <p className="error next-steps-note" role="alert">{error}</p>}
      {modal}
    </div>
  );
}

// The replacement-interval action beside the wear-out reading.
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
