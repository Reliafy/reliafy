import { useEffect, useState } from "react";
import { lifeAt } from "../api.js";
import { formatNumber } from "../format.js";
import { boundWords } from "../lifeResults.js";
import { unitInText } from "./unitText.js";
import "./RegressionChecks.css";

// The life card of a regression model (#54): B1, B5, B10, B50 and the MTTF at
// the calculator's first covariate combination, each B-life with its one-sided
// lower bound at the calculator's confidence — SurPyval's qf / quantile_cb /
// mean at that row, fetched from the model's life path. Cox PH has none (its
// curve is a step function), and ``note`` says so instead.
const cache = new Map();
const LIFE_NAMES = { B50: "B50 (median)" };

export default function RegressionLife({ path, note, values, level = 90, unit, dot = null }) {
  const key = path ? `${path}|${level}|${JSON.stringify(values || {})}` : null;
  const [got, setGot] = useState(() => (key && cache.has(key) ? { key, data: cache.get(key) } : null));
  useEffect(() => {
    if (!key || !(level > 0 && level < 100)) return undefined;
    if (cache.has(key)) {
      setGot({ key, data: cache.get(key) });
      return undefined;
    }
    let live = true;
    const id = setTimeout(() => {
      lifeAt(path, { confidence: level / 100, covariates: values || {} })
        .then((data) => {
          cache.set(key, data);
          if (live) setGot({ key, data });
        })
        .catch((err) => live && setGot({ key, data: null, error: err.message }));
    }, 300);
    return () => {
      live = false;
      clearTimeout(id);
    };
  }, [key, level, path, values]);

  const u = unit ? unitInText(unit) : "";
  const head = (
    <div className="gofh rl-head">
      <span>
        {dot && <span className="combo-dot" style={{ background: dot }} aria-hidden="true" />}
        Life{u ? <span className="gof-sub">{u}</span> : null}
      </span>
      {path && <span className="gof-sub">{level}% lower bound</span>}
    </div>
  );
  if (!path) {
    return (
      <div className="calc-rail-card calc-rail-params rl-card">
        {head}
        <p className="param-ci-note">{note}</p>
      </div>
    );
  }
  // While another row or level loads, the last values stand.
  const life = got?.data || null;
  const pending = got?.key !== key;
  const rows = life
    ? [
        ...life.b_lives.map((b) => ({
          key: b.label, label: LIFE_NAMES[b.label] || b.label, value: b.value, lower: b.lower,
          what: `${b.label}: ${Math.round(b.p * 100)}% have failed by then`,
        })),
        { key: "MTTF", label: "MTTF (mean)", value: life.mttf?.value, lower: null,
          what: life.mttf_note || "MTTF: the mean time to failure" },
      ]
    : [];
  return (
    <div className="calc-rail-card calc-rail-params rl-card" aria-busy={pending}>
      {head}
      {got?.error && got.key === key ? (
        <p className="param-ci-note">Couldn't compute the B-lives: {got.error}</p>
      ) : !life ? (
        <p className="param-ci-note">Working out the B-lives…</p>
      ) : (
        <>
          {rows.map((r) => (
            <div
              className="gofr rl-row"
              key={r.key}
              title={r.lower != null
                ? `${r.what}. ${boundWords(level, "lower", r.lower, null, (v) => `${formatNumber(v)}${u ? ` ${u}` : ""}`)}.`
                : `${r.what}.`}
            >
              <span className="gk">{r.label}</span>
              <span className="gv">{formatNumber(r.value)}</span>
              <span className="rl-lo">{r.lower != null ? `≥ ${formatNumber(r.lower)}` : pending ? "…" : ""}</span>
            </div>
          ))}
          {life.bounds_note && <p className="param-ci-note">{life.bounds_note}</p>}
        </>
      )}
    </div>
  );
}
