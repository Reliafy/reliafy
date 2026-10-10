import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Modal from "./Modal.jsx";
import Select from "./Select.jsx";
import ResultSummary from "./ui/ResultSummary.jsx";
import { lifeAt } from "../api.js";
import { formatNumber } from "../format.js";
import { bLabel, betaSource, demoLink, requirementVerdict, verdictText } from "../requirement.js";
import { unitInText } from "./unitText.js";
import "./Requirement.css";

// "Does it meet B10 ≥ 50,000 at 90% confidence?" on a fitted life model
// (#295): a row at the foot of the Life card that opens a small form, and
// then carries the verdict. The B-life's lower bound comes from the model's
// life path (SurPyval's); the confidence is the page's shared one. "Plan a
// test to demonstrate this" opens the demonstration test with the
// requirement, the model's unit and its β.

// The requirement checked on each model (by life path), so it survives a tab
// switch and a revisit in the same session.
const remembered = new Map();
const answers = new Map();

function Sentence({ verdict }) {
  return verdict.segments.map(([text, bold], i) => (bold ? <b key={i}>{text}</b> : <span key={i}>{text}</span>));
}

export default function RequirementCheck({ result, level, onLevel, levels, modelId = null, name = null }) {
  const path = result.functions?.life_path;
  const unit = result.unit || "";
  const u = unitInText(unit);
  const navigate = useNavigate();
  const [req, setReq] = useState(() => remembered.get(path) || null);
  const [open, setOpen] = useState(false);
  const [bText, setBText] = useState(() => String(req?.b ?? 10));
  const [lifeText, setLifeText] = useState(() => (req ? String(req.life) : ""));
  const [formError, setFormError] = useState(null);
  const key = req && path ? `${path}|${req.b}|${req.life}|${level}` : null;
  const [answer, setAnswer] = useState(() => (key && answers.has(key) ? { key, data: answers.get(key) } : null));

  useEffect(() => {
    if (!key) return undefined;
    if (answers.has(key)) {
      setAnswer({ key, data: answers.get(key) });
      return undefined;
    }
    let live = true;
    lifeAt(path, { requirement: { b: req.b, life: req.life }, confidence: level / 100, unit })
      .then((data) => {
        answers.set(key, data);
        if (live) setAnswer({ key, data });
      })
      .catch((err) => live && setAnswer({ key, error: err.message }));
    return () => {
      live = false;
    };
  }, [key, path, req, level, unit]);

  if (!path) return null;
  const current = answer?.key === key ? answer : null;
  const verdict = current?.data ? requirementVerdict(current.data, unit) : null;
  const pending = !!key && !current;

  const submit = (e) => {
    e.preventDefault();
    const b = Number(bText);
    const life = Number(lifeText);
    if (!(bText !== "" && b > 0 && b < 100)) return setFormError("The B-life is the percent failed: between 0 and 100, e.g. 10 for B10.");
    if (!(lifeText !== "" && life > 0 && Number.isFinite(life))) return setFormError("Enter the life required, above 0.");
    setFormError(null);
    const next = { b, life };
    remembered.set(path, next);
    setReq(next);
  };

  const planTest = () => {
    const beta = modelId ? null : betaSource(result, name);
    navigate(demoLink({ b: req.b, life: req.life, confidence: level, unit, modelId, beta }));
  };

  const short = req ? `${bLabel(req.b)} ≥ ${formatNumber(req.life)}` : null;
  const rowValue = !req ? "Check" : pending ? "…" : verdict ? verdict.short : "Couldn't check";
  return (
    <>
      <button
        type="button"
        className="gofr gofr-link req-row"
        onClick={() => setOpen(true)}
        aria-label={req ? `Check a requirement: ${short}, ${rowValue}` : "Check a requirement"}
        title={verdict ? verdictText(verdict) : "Does the model meet a B-life requirement at this confidence?"}
      >
        <span className="gk">{short || "Requirement"}</span>
        <span className={"gv" + (verdict ? ` req-${verdict.tone}` : "")}>{rowValue} ›</span>
      </button>
      {open && (
        <Modal
          title="Check a requirement"
          onClose={() => setOpen(false)}
          className="req-modal"
          footer={
            <div className="row" style={{ margin: 0, marginLeft: "auto" }}>
              {req && (
                <button type="button" className="secondary" onClick={planTest}>
                  Plan a test to demonstrate this
                </button>
              )}
              <button type="button" className="secondary" onClick={() => setOpen(false)}>Done</button>
            </div>
          }
        >
          <p className="muted-line req-intro">
            Does the B-life meet a requirement? It's judged on the lower bound, so a pass holds at that confidence.
          </p>
          <form className="req-form" onSubmit={submit}>
            <label className="calc-t">
              <span>B-life (% failed)</span>
              <input type="number" step="any" min="0" max="100" value={bText} onChange={(e) => setBText(e.target.value)} />
            </label>
            <label className="calc-t">
              <span>Required life{u ? ` (${u})` : ""}</span>
              <input type="number" step="any" min="0" value={lifeText} placeholder="e.g. 50000"
                     onChange={(e) => setLifeText(e.target.value)} />
            </label>
            <div className="calc-t">
              <span>Confidence</span>
              <Select
                value={level}
                onChange={(v) => onLevel?.(Number(v))}
                disabled={!onLevel}
                title="The confidence of the lower bound (one-sided), shared with the Life card"
                options={levels.map((l) => ({ value: l, label: `${l}%` }))}
              />
            </div>
            <button type="submit">Check</button>
          </form>
          {formError && <p className="error req-error">{formError}</p>}
          {current?.error && <p className="error req-error">{current.error}</p>}
          {pending && <p className="muted-line">Checking…</p>}
          {verdict && (
            <ResultSummary tone={verdict.tone} sentence={<Sentence verdict={verdict} />} className="req-verdict">
              {verdict.note}
            </ResultSummary>
          )}
        </Modal>
      )}
    </>
  );
}
