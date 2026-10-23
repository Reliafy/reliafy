import { useEffect, useState } from "react";
import Select from "./Select.jsx";
import { lifeAt } from "../api.js";
import { formatNumber } from "../format.js";
import { boundWords } from "../lifeResults.js";
import { boundUnavailable, meanLevels, meanLifeAnswer, medianOf } from "../meanLife.js";
import { unitInText } from "./unitText.js";

// The Model characteristics tab's mean life: the MTTF with its one-sided
// lower bound at the page's confidence (shared with the calculator), and for
// a non-parametric estimate the mean counted to a horizon the viewer can set.
// The fit carries its life at 90%; another level or horizon is fetched from
// the model's life path and kept here, so going back to it doesn't ask again.
const cache = new Map();

function useMeanLife(result, level, tau) {
  const path = result.functions?.life_path;
  const stored = result.life || null;
  const storedFits = stored && Math.abs(stored.confidence * 100 - level) < 1e-6 && tau == null;
  const key = path ? `${path}|${level}|${tau ?? ""}` : null;
  const [got, setGot] = useState(() => (key && cache.has(key) ? { key, data: cache.get(key) } : null));
  useEffect(() => {
    if (!key || storedFits || !(level > 0 && level < 100)) return undefined;
    if (cache.has(key)) {
      setGot({ key, data: cache.get(key) });
      return undefined;
    }
    let live = true;
    const id = setTimeout(() => {
      lifeAt(path, { confidence: level / 100, ...(tau != null ? { tau } : {}) })
        .then((data) => {
          cache.set(key, data);
          if (live) setGot({ key, data });
        })
        .catch((error) => live && setGot({ key, error }));
    }, 250);
    return () => {
      live = false;
      clearTimeout(id);
    };
  }, [key, storedFits, level, path, tau]);
  if (storedFits || !key) return { life: stored, level: stored ? stored.confidence * 100 : level, pending: false };
  const mine = got?.key === key ? got : null;
  if (mine?.data) return { life: mine.data, level, pending: false };
  // A request that failed (a shared page's viewer can't ask the model):
  // the saved figures at their own level, and why.
  if (mine?.error) return { life: stored, level: stored ? stored.confidence * 100 : level, pending: false, error: mine.error };
  return { life: stored, level, pending: true };
}

// The horizon of a non-parametric mean life (#85), typed in place: sent when
// it is a time above zero; the answer refetches after a pause.
function HorizonInput({ tau, unit, onChange }) {
  const show = (v) => (v != null ? String(+Number(v).toPrecision(6)) : "");
  const [text, setText] = useState(show(tau));
  const [prev, setPrev] = useState(tau);
  if (tau !== prev) {
    setPrev(tau);
    if (Number(text) !== Number(tau)) setText(show(tau));
  }
  return (
    <label className="calc-t model-chars-horizon">
      <span>Count up to{unit ? ` (${unit})` : ""}</span>
      <input
        type="number" inputMode="decimal" min="0" step="any"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          const v = Number(e.target.value);
          if (e.target.value !== "" && Number.isFinite(v) && v > 0) onChange(v);
        }}
      />
    </label>
  );
}

// The Model characteristics tab: labelled rows in the Parameters card's style,
// so more can join later. Today it holds the mean life. ``level`` /
// ``onLevel``: the page's confidence (%), shared with the calculator.
// ``onBLives`` opens the calculator's Time at reliability.
export default function ModelCharacteristics({ result, level, onLevel, onBLives = null }) {
  const [tau, setTau] = useState(null);
  const lvl = Number(level) > 0 && Number(level) < 100 ? Number(level) : 90;
  const { life, level: shownLevel, pending, error } = useMeanLife(result, lvl, tau);
  const unit = result.unit ? unitInText(result.unit) : "";
  const withUnit = (v) => `${formatNumber(v)}${unit ? ` ${unit}` : ""}`;
  const answer = meanLifeAnswer(result, life?.mttf);
  const median = medianOf(life);
  const np = result.kind === "nonparametric";
  const canPick = !!result.functions?.life_path && !!onLevel;
  const horizon = np ? (tau ?? life?.mttf?.tau ?? null) : null;
  const unavailable = boundUnavailable(error, result.life?.confidence);
  const levelText = `${formatNumber(shownLevel)}%`;

  // The rows of the mean-life section: [key, label, value, note under it].
  let rows;
  if (!life) {
    rows = [["mean", "Mean life (MTTF)", pending ? "…" : "—", pending ? null : unavailable || "This model gives no mean life."]];
  } else if (answer.kind === "none") {
    rows = [["mean", "Mean life (MTTF)", "None", answer.why]];
  } else {
    const lower = answer.lower != null ? `≥ ${withUnit(answer.lower)} at ${levelText}` : pending ? "…" : null;
    rows = [[
      "mean",
      answer.kind === "restricted" ? `Mean to ${withUnit(answer.tau)}` : "Mean life (MTTF)",
      withUnit(answer.value),
      lower,
    ]];
  }
  const bound = answer.lower != null ? boundWords(shownLevel, "lower", answer.lower, null, withUnit) : "";

  return (
    <div className="detail-panel model-chars">
      <section className="gof-card model-chars-card" aria-labelledby="model-chars-mean">
        <div className="gofh life-card-head">
          <h3 id="model-chars-mean" className="model-chars-h">Mean life</h3>
          {canPick && life && (
            <Select
              value={lvl}
              onChange={(v) => onLevel(Number(v))}
              className="model-chars-conf"
              ariaLabel="Confidence of the lower bound"
              title="The confidence of the lower bound (one-sided), shared with the Calculator"
              options={meanLevels(lvl).map((l) => ({ value: l, label: `${l}% lower bound` }))}
            />
          )}
        </div>
        {rows.map(([key, label, value, sub]) => (
          <div className="gofr" key={key} title={bound ? `${label}: ${withUnit(answer.value)}; ${bound}.` : undefined}>
            <span className="gk">{label}</span>
            <span className="gv-col">
              <span className="gv">{value}</span>
              {sub && <span className="param-ci">{sub}</span>}
            </span>
          </div>
        ))}
        {np && life && horizon != null && (
          <div className="gofr model-chars-input">
            <HorizonInput tau={horizon} unit={unit} onChange={setTau} />
          </div>
        )}
        {life && (
          <div className="model-chars-what">
            {answer.kind !== "none" && <p>
              {answer.kind === "restricted"
                ? "The average time to failure, counting only up to that time: some units were still running at the end of the data, so the full mean can't be estimated. Move the time to see how the mean grows."
                : "The average time to failure. It isn't the median (B50, when half have failed): a few long-lived units pull the mean up, so it's usually the later of the two."}
              {median != null && answer.kind === "mean" && <> Here the median is <b>{withUnit(median)}</b>.</>}
            </p>}
            {answer.kind === "none" && median != null && (
              <p>The median (B50, when half have failed) is <b>{withUnit(median)}</b>: quote that instead.</p>
            )}
            {answer.caveat && <p className="hint">{answer.caveat}</p>}
            {unavailable && <p className="hint">{unavailable}</p>}
            {life.bounds_note && <p className="muted-line">{life.bounds_note}</p>}
          </div>
        )}
      </section>
      {onBLives && (
        <button type="button" className="link model-chars-blives" onClick={onBLives}>
          B-lives: use Time at reliability in the Calculator ›
        </button>
      )}
    </div>
  );
}
