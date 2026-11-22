import { useEffect, useMemo, useState } from "react";
import ModelPicker from "./ModelPicker.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import { lifeLine } from "./rbdModelText.js";
import { standbyRoute } from "../api.js";
import { describeStandby, MAX_OWN_UNITS, standbyUnits, tidyOwn } from "../standbyWords.js";
import "./RbdBlockOptions.css";
import { Checkbox } from "./ui/Controls.jsx";

// The standby settings of a standby block (#84, #363: standby as plants run
// it): how many units run (k), how many spares, how they wait (cold, warm at
// a dormancy factor, hot), the chance a spare starts, the units that fail by a
// model of their own, and how the block is worked out — exact or numerical
// (free), or, where RePyability has neither, its plain refusal and the offer
// to simulate it (Pro). Self-contained (state in, settings out through
// ``onChange``), so it moves to the table pane (#415) as it is.
//
//   initial     the block's saved data
//   model       the block's own (running units') non-repairable model
//   repairable  a repairable diagram's standby group: identical units, a start
//               chance on cold spares only, no simulation offer
//   unit        the diagram's time unit
//   label       the block's name (for the server's wording)
//   onChange    ({ settings, valid }) whenever anything changes

const KINDS = [
  { id: "cold", label: "Cold", hint: "Idle spares don't age; each must start when switched in." },
  { id: "warm", label: "Warm", hint: "Idle spares age at a fraction of the running rate, and can fail before they're needed." },
  { id: "hot", label: "Hot", hint: "Every unit runs from the start — plain active redundancy." },
];

export const COLD_START_DEFAULT = 1;
export const COLD_START_HINT = "Spares don't always start: 0.95–0.99 is typical for generators and pumps. A spare that fails to start is skipped and the next one is tried.";

function initialKind(initial) {
  const d = initial?.dormancy ?? (initial?.cold ? 0 : 1);
  return d <= 0 ? "cold" : d >= 1 ? "hot" : "warm";
}

// One unit's row: its name, "Block's model" or "Its own", and the picker
// when it has its own.
function UnitRow({ unit, timeUnit, fallback, onChange, shared = false }) {
  const [own, setOwn] = useState(unit.own);
  return (
    <li className="standby-unit">
      <div className="standby-unit-head">
        <span className="standby-unit-name">{unit.label}</span>
        <ChoiceChips
          label={`${unit.label}: which model`}
          value={own ? "own" : "block"}
          onChange={(v) => {
            const next = v === "own";
            setOwn(next);
            if (!next) onChange(null);
          }}
          options={[
            { value: "block", label: unit.role === "spare" && shared ? "Every spare's" : "Block's model" },
            { value: "own", label: "Its own" },
          ]}
        />
      </div>
      {own ? (
        <ModelPicker
          label={unit.role === "every" ? "Every spare's non-repairable model" : `${unit.label}'s non-repairable model`}
          value={unit.own ? unit.model : null}
          onChange={onChange}
          rbdBlock
          unit={timeUnit}
          meanEntry="Mean life, MTBF"
          autoPick={false}
        />
      ) : (
        <p className="hint standby-unit-model">{fallback ? lifeLine(fallback, timeUnit) : "No model yet"}</p>
      )}
    </li>
  );
}

export default function StandbySettings({ initial, model, repairable = false, unit = "", label = "", onChange }) {
  const [spares, setSpares] = useState(initial?.spares ?? 1);
  const [running, setRunning] = useState(initial?.k ?? 1);
  const [kind, setKind] = useState(initialKind(initial));
  const [dormancy, setDormancy] = useState(initial?.dormancy > 0 && initial?.dormancy < 1 ? initial.dormancy : 0.2);
  const [startProb, setStartProb] = useState(initial?.startProb ?? COLD_START_DEFAULT);
  const [standbyModel, setStandbyModel] = useState(initial?.standbyModel ?? null);
  const [runningModels, setRunningModels] = useState(initial?.runningModels ?? []);
  const [spareModels, setSpareModels] = useState(initial?.spareModels ?? []);
  const [simulate, setSimulate] = useState(!!initial?.simulate);
  const [route, setRoute] = useState(null);

  const cold = kind === "cold";
  const sparesNum = Number(spares);
  const runNum = Number(running);
  const probNum = Number(startProb);
  const dormNum = Number(dormancy);
  const validSpares = Number.isInteger(sparesNum) && sparesNum >= 1;
  const validRunning = Number.isInteger(runNum) && runNum >= 1;
  // A repairable diagram's standby group takes a start chance on cold spares only.
  const takesStart = cold || !repairable;
  const validProb = !takesStart || (probNum >= 0 && probNum <= 1);
  const validDorm = kind !== "warm" || (dormNum > 0 && dormNum < 1);
  const total = (validRunning ? runNum : 1) + (validSpares ? sparesNum : 1);
  // Units of their own: non-repairable blocks of up to MAX_OWN_UNITS units.
  const ownAllowed = !repairable && total <= MAX_OWN_UNITS;

  const settings = useMemo(() => {
    const s = {
      spares: sparesNum,
      k: runNum > 1 ? runNum : null,
      cold,
      dormancy: cold ? 0 : kind === "hot" ? 1 : dormNum,
      startProb: takesStart ? probNum : 1,
      // A repairable group's units are identical: no models of their own.
      standbyModel: repairable ? null : standbyModel,
      runningModels: ownAllowed ? tidyOwn(runningModels, runNum) : null,
      spareModels: ownAllowed ? tidyOwn(spareModels, sparesNum) : null,
      simulate: null,
    };
    return s;
  }, [sparesNum, runNum, cold, kind, dormNum, takesStart, probNum, repairable, standbyModel, ownAllowed,
    runningModels, spareModels]);
  const exact = route && route.route !== "simulated";
  const settingsOut = useMemo(
    // Kept while the route is still being read (null), dropped once the block can be worked out.
    () => ({ ...settings, simulate: !repairable && simulate && (!route || route.route === "simulated") ? true : null }),
    [settings, repairable, route, simulate]);
  // A block RePyability can only simulate is saved only once simulating it is
  // chosen (or the settings change so it can be worked out).
  const refused = !repairable && route?.route === "simulated" && !simulate;
  const valid = validSpares && validRunning && validProb && validDorm && !refused;

  useEffect(() => {
    onChange?.({ settings: settingsOut, valid });
  }, [settingsOut, valid]); // eslint-disable-line react-hooks/exhaustive-deps

  // How the block is worked out, from the server (RePyability's own answer), a
  // moment after the last change.
  const sig = JSON.stringify({ model, ...settings });
  useEffect(() => {
    if (repairable || !model || !(validSpares && validRunning && validProb && validDorm)) {
      setRoute(null);
      return undefined;
    }
    let live = true;
    const t = setTimeout(() => {
      standbyRoute({ type: "standby", data: { label, model, ...settings } })
        .then((r) => { if (live) setRoute(r); })
        .catch((e) => { if (live) setRoute({ route: "error", reason: e?.message || "Couldn't read the block." }); });
    }, 300);
    return () => { live = false; clearTimeout(t); };
  }, [sig, repairable]); // eslint-disable-line react-hooks/exhaustive-deps

  const words = describeStandby({ ...settings, model });
  const units = standbyUnits({ model, ...settings, runningModels, spareModels });
  const setUnit = (u, m) => {
    const setter = u.role === "running" ? setRunningModels : setSpareModels;
    setter((list) => {
      const next = [...(list || [])];
      while (next.length <= u.index) next.push(null);
      next[u.index] = m || null;
      return next;
    });
  };

  return (
    <div className="standby-settings">
      <p className="standby-words" role="status" aria-live="polite">
        <b>{words.charAt(0).toUpperCase() + words.slice(1)}.</b>
      </p>
      {!repairable && route && (
        <div className={`standby-route${route.route === "simulated" ? " is-sim" : ""}`} role="status">
          {exact && route.route !== "error" && (
            <p className="hint">
              Worked out {route.route === "exact" ? "exactly" : "numerically"} — free.
            </p>
          )}
          {route.route === "error" && <p className="hint rbd-limit">{route.reason}</p>}
          {route.route === "simulated" && (
            <>
              <p className="rbd-limit">{route.reason}</p>
              <Checkbox className="rbd-instant-repair" checked={simulate} onChange={(e) => setSimulate(e.target.checked)}
                label={<span>
                  Simulate this block <span className="muted">— Pro: its reliability is estimated from{" "}
                  {Number(route.lives || 200000).toLocaleString("en-GB")} simulated lifetimes, the same every run</span>
                </span>} />
            </>
          )}
        </div>
      )}
      <div className="param-fields">
        <label className="param-field" title="How many units must run at once: 2 running and 1 spare is a 2-of-3 duty/standby train.">
          <span>Units running</span>
          <input type="number" inputMode="numeric" min="1" step="1" value={running} onChange={(e) => setRunning(e.target.value)} />
        </label>
        <label className="param-field">
          <span>Spares</span>
          <input type="number" inputMode="numeric" min="1" step="1" value={spares} onChange={(e) => setSpares(e.target.value)} />
        </label>
        {kind === "warm" && (
          <label className="param-field" title="How fast an idle spare ages relative to a running one: 0 is cold, 1 is hot. 0.3 ages a waiting spare at 30% of the running rate.">
            <span>Dormancy factor</span>
            <input type="number" inputMode="decimal" step="any" min="0" max="1" value={dormancy}
                   onChange={(e) => setDormancy(e.target.value)} />
          </label>
        )}
        {takesStart && (
          <label className="param-field" title="The chance a spare starts when it's switched in. A spare that fails to start is skipped and the next one is tried. 1 means every spare starts; 0.99 is one failed start in 100.">
            <span>Chance a spare starts</span>
            <input type="number" inputMode="decimal" step="any" min="0" max="1" value={startProb}
                   onChange={(e) => setStartProb(e.target.value)} />
          </label>
        )}
      </div>
      {!validRunning && <p className="hint rbd-limit" role="alert">Units running must be a whole number, 1 or more.</p>}
      {!validSpares && <p className="hint rbd-limit" role="alert">Spares must be a whole number, 1 or more.</p>}
      {!validDorm && <p className="hint rbd-limit" role="alert">A warm spare's dormancy factor is between 0 and 1, e.g. 0.3.</p>}
      {!validProb && <p className="hint rbd-limit" role="alert">The chance a spare starts is between 0 and 1, e.g. 0.97.</p>}
      {takesStart && <p className="hint standby-start-hint">{COLD_START_HINT}</p>}
      <div className="standby-kind">
        <SegmentedControl
          label="Standby type"
          value={kind}
          onChange={setKind}
          options={KINDS.map((k) => ({ value: k.id, label: k.label }))}
        />
        <p className="hint">{KINDS.find((k) => k.id === kind).hint}</p>
      </div>

      {!repairable && (
        <details className="standby-units" open={units.some((u) => u.own) || !!standbyModel}>
          <summary>Units that differ</summary>
          {ownAllowed ? (
            <>
              <p className="hint">
                Every unit fails by the block's model unless you give it its own: an older duty unit, a smaller
                spare. Spares are switched in in this order.
              </p>
              <ul className="standby-unit-list">
                <UnitRow
                  key="every-spare"
                  unit={{ role: "every", index: 0, label: "Every spare", model: standbyModel, own: !!standbyModel }}
                  timeUnit={unit}
                  fallback={model}
                  onChange={setStandbyModel}
                />
                {units.map((u) => (
                  <UnitRow
                    key={`${u.role}${u.index}`}
                    unit={u}
                    timeUnit={unit}
                    fallback={u.role === "spare" ? standbyModel || model : model}
                    shared={!!standbyModel}
                    onChange={(m) => setUnit(u, m)}
                  />
                ))}
              </ul>
            </>
          ) : (
            <p className="hint">
              Units take a model of their own when the block has at most {MAX_OWN_UNITS} units; this one has {total}.
            </p>
          )}
        </details>
      )}

    </div>
  );
}
