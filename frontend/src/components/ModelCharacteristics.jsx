import { useEffect, useState } from "react";
import Select from "./Select.jsx";
import RegressionLife from "./RegressionLife.jsx";
import { useTvcEvaluation } from "./TvcResult.jsx";
import { lifeAt } from "../api.js";
import { formatNumber } from "../format.js";
import { boundWords, timeAtValue } from "../lifeResults.js";
import { boundUnavailable, meanLevels, meanLifeAnswer, medianOf } from "../meanLife.js";
import { unitInText } from "./unitText.js";
import { withUnit as covariateWithUnit } from "./stressName.js";

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

// The usual B-lives: the time by which 1%, 5%, 10% and half have failed.
const B_LABELS = [["B1", 0.01], ["B5", 0.05], ["B10", 0.1], ["B50", 0.5]];
const B_NAMES = { B50: "B50 (median)" };

// The B-lives card: each with its one-sided lower bound at the page's
// confidence, from the same life answer as the mean.
function BLivesCard({ life, level, pending, unit, noun = "time" }) {
  const u = unit ? ` ${unit}` : "";
  const rows = (life?.b_lives || []).filter((b) => B_LABELS.some(([l]) => l === b.label));
  return (
    <section className="gof-card model-chars-card" aria-labelledby="model-chars-blives">
      <div className="gofh life-card-head">
        <h3 id="model-chars-blives" className="model-chars-h">B-lives</h3>
        {rows.some((b) => b.lower != null) && <span className="gof-sub">≥ lower bound at {formatNumber(level)}%</span>}
      </div>
      {!rows.length && <p className="mf-note">{pending ? "Working out the B-lives…" : "This model gives no B-lives."}</p>}
      {rows.map((b) => (
        <div className="gofr life-row" key={b.label}
             title={`${b.label}: the ${noun} by which ${Math.round(b.p * 100)}% have failed`}>
          <span className="gk">{B_NAMES[b.label] || b.label}</span>
          <span className="gv">{b.value != null ? `${formatNumber(b.value)}${u}` : "—"}</span>
          <span className="life-lo">{b.lower != null ? `≥ ${formatNumber(b.lower)}` : pending ? "…" : ""}</span>
        </div>
      ))}
      <p className="mf-note">
        B10 is the {noun} by which 10% have failed (90% still running): the usual design life.
      </p>
    </section>
  );
}

// The Model characteristics tab: the model's key figures in one sheet. A
// fitted distribution, spline, estimate or discrete fit: the mean life and
// the B-lives at the page's confidence. A regression: the same at the
// calculator's covariates; covariates that change over time: along its
// schedule. ``level`` / ``onLevel``: the page's confidence (%), shared with
// the calculator. ``onBLives`` opens the calculator's Time at reliability;
// ``calc`` / ``tvc``: the calculator's state (its covariates, its schedule);
// ``onCalc`` opens the calculator.
export default function ModelCharacteristics(props) {
  const { result } = props;
  if (result.kind === "regression" && result.tvc) return <TvcCharacteristics {...props} />;
  if (result.kind === "regression") return <RegressionCharacteristics {...props} />;
  return <LifeCharacteristics {...props} />;
}

function LifeCharacteristics({ result, level, onLevel, onBLives = null }) {
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
  const discrete = result.kind === "discrete";
  const noun = discrete ? "count" : "time";

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
    <div className="detail-panel mf-l6 model-chars">
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
                : `The average ${noun} to failure. It isn't the median (B50, when half have failed): a few long-lived units pull the mean up, so it's usually the later of the two.`}
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
        {onBLives && (
          <button type="button" className="link model-chars-blives" onClick={onBLives}>
            Another reliability: use Time at reliability in the Calculator ›
          </button>
        )}
      </section>
      <BLivesCard life={life} level={shownLevel} pending={pending} unit={unit} noun={noun} />
    </div>
  );
}

// The confidence picker of the B-lives' lower bound, shared with the calculator.
function LevelSelect({ level, onLevel }) {
  if (!onLevel) return null;
  return (
    <Select
      value={level}
      onChange={(v) => onLevel(Number(v))}
      className="model-chars-conf"
      ariaLabel="Confidence of the lower bound"
      title="The confidence of the lower bound (one-sided), shared with the Calculator"
      options={meanLevels(level).map((l) => ({ value: l, label: `${l}% lower bound` }))}
    />
  );
}

// "temp_C 79.4, load 0.7": the covariate values the figures are at.
function atWords(fields, values) {
  return (fields || []).map((f) => `${covariateWithUnit(f.name, f.unit)} ${values?.[f.name] ?? "—"}`).join(", ");
}

// A regression's B-lives and mean at the calculator's first covariate
// combination: with lower bounds from its life path, or (Cox, frailty: no
// life path) read off its curve there, without bounds.
function RegressionCharacteristics({ result, level, onLevel, calc, onCalc }) {
  const fns = result.functions || {};
  const s0 = calc?.series?.[0];
  const lvl = Number(level) > 0 && Number(level) < 100 ? Number(level) : 90;
  const unit = result.unit ? unitInText(result.unit) : "";
  const at = atWords(fns.covariates, s0?.values);
  const curve = s0?.curves || fns.curves;
  const read = !fns.life_path && curve
    ? B_LABELS.map(([label, p]) => ({ label, p, value: timeAtValue(curve.x, curve.sf, 1 - p), lower: null }))
    : null;
  return (
    <div className="detail-panel mf-l6 model-chars">
      <section className="gof-card model-chars-card" aria-labelledby="model-chars-at">
        <div className="gofh life-card-head">
          <h3 id="model-chars-at" className="model-chars-h">At these covariates</h3>
          {fns.life_path && <LevelSelect level={lvl} onLevel={onLevel} />}
        </div>
        <p className="mf-note">
          A regression model's life depends on the covariates. These figures are at <b>{at || "the defaults"}</b>
          {calc?.series?.length > 1 ? " (the Calculator's first combination)" : ""}.
          {onCalc && <> <button type="button" className="link" onClick={onCalc}>Change them in the Calculator ›</button></>}
        </p>
      </section>
      {fns.life_path ? (
        <div className="model-chars-card rl-wrap">
          <RegressionLife path={fns.life_path} note={fns.life_note} values={s0?.values} level={lvl} unit={result.unit} />
        </div>
      ) : (
        <>
          <BLivesCard life={{ b_lives: read || [] }} level={lvl} pending={false} unit={unit} />
          {fns.life_note && <p className="hint model-chars-note">{fns.life_note}</p>}
        </>
      )}
    </div>
  );
}

// Covariates that change over time: the B-lives and mean along the
// calculator's schedule.
function TvcCharacteristics({ result, tvc, onCalc }) {
  const { res, error, body } = useTvcEvaluation(result, tvc || {}, { on: "sf" });
  const unit = result.unit ? unitInText(result.unit) : "";
  const curves = res?.curves;
  const rows = B_LABELS.map(([label, p]) => ({
    label, p, value: curves ? timeAtValue(curves.x, curves.sf, 1 - p) : null, lower: null,
  }));
  const u = unit ? ` ${unit}` : "";
  const sched = body?.schedule || [];
  return (
    <div className="detail-panel mf-l6 model-chars">
      <section className="gof-card model-chars-card" aria-labelledby="model-chars-sched">
        <div className="gofh life-card-head"><h3 id="model-chars-sched" className="model-chars-h">On this schedule</h3></div>
        <p className="mf-note">
          These figures follow the Calculator's covariate schedule
          {sched.length ? ` (${sched.length} step${sched.length === 1 ? "" : "s"})` : ""}.
          {onCalc && <> <button type="button" className="link" onClick={onCalc}>Change it in the Calculator ›</button></>}
        </p>
        {result.tvc?.mean && (
          <div className="gofr">
            <span className="gk">Mean life</span>
            <span className="gv">{res?.mean != null && Number.isFinite(Number(res.mean)) ? `${formatNumber(res.mean)}${u}` : res ? "—" : "…"}</span>
          </div>
        )}
        {body?.error && <p className="hint mf-note">{body.error}</p>}
        {error && <p className="hint mf-note">Couldn't evaluate the schedule: {error}</p>}
      </section>
      <BLivesCard life={{ b_lives: curves ? rows : [] }} level={90} pending={!res && !error} unit={unit} />
    </div>
  );
}
