// Test planning › Accelerated test: which stresses to test at, how many units
// at each, and how many failures to expect, to estimate the B-life at the use
// stress as precisely as the test allows. ``modelId`` (from an ALT model's
// "Plan the next test") starts it from that model's fit.
import { useEffect, useState } from "react";
import Plot from "./Plot.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { Assumptions, Choice, ComputeButton, Field, PlanAnswer, SimulationCheck, usePlan } from "./TestPlanShared.jsx";
import { getAltModel } from "../api.js";
import { formatNumber, formatWithUnit } from "../format.js";
import { ACCENT, COLORWAY } from "../plotTheme.js";
import { PLAN_DISTRIBUTIONS, PLAN_LIFE_MODELS, altPrefill, frac, num } from "../testPlanning.js";
import { unitInText } from "./unitText.js";

const MODEL_OPTIONS = Object.fromEntries(Object.entries(PLAN_LIFE_MODELS).map(([k, v]) => [k, v.label]));
const MODEL_HINT = {
  arrhenius: "Life = b·exp(a / T), T in kelvin.",
  eyring: "A thermal model from reaction-rate theory, an alternative to Arrhenius. T in kelvin.",
  inverse_power: "Life = 1 / (a·Vⁿ).",
};
// A worked example: a part lasting about 6,500 hours (B10) at 50 °C, tested
// up to 120 °C.
const EXAMPLE = {
  distribution: "weibull",
  lifeModel: "arrhenius",
  params: { a: "6694", b: "0.00002" },
  shape: "2",
  useStress: "323",
  highStress: "393",
  unit: "hours",
  stressUnit: "K",
};

const list = (s) => String(s || "").split(/[,\s]+/).filter(Boolean).map(Number);

function AllocationChart({ result }) {
  const rows = result.rows;
  const su = result.stress_unit ? ` ${result.stress_unit}` : "";
  const x = rows.map((r) => `${formatNumber(r.stress)}${su}`);
  return (
    <Plot
      data={[
        { type: "bar", name: "Units", x, y: rows.map((r) => r.units), marker: { color: ACCENT },
          hovertemplate: "%{x}: %{y} units<extra></extra>" },
        { type: "bar", name: "Expected failures", x, y: rows.map((r) => r.expected_failures),
          marker: { color: COLORWAY[1] }, hovertemplate: "%{x}: %{y:.1f} failures expected<extra></extra>" },
      ]}
      layout={{ height: 320, barmode: "group", showlegend: true, xaxis: { title: { text: "Test stress" }, type: "category" },
        yaxis: { title: { text: "Count" }, rangemode: "tozero" } }}
      download="Accelerated test plan"
    />
  );
}

export default function AcceleratedTestPlan({ modelId = null }) {
  const [mode, setMode] = useState("plan");
  const [distribution, setDistribution] = useState(EXAMPLE.distribution);
  const [lifeModel, setLifeModel] = useState(EXAMPLE.lifeModel);
  const [params, setParams] = useState(EXAMPLE.params);
  const [shape, setShape] = useState(EXAMPLE.shape);
  const [useStress, setUseStress] = useState(EXAMPLE.useStress);
  const [highStress, setHighStress] = useState(EXAMPLE.highStress);
  const [units, setUnits] = useState("40");
  const [censorTime, setCensorTime] = useState("1000");
  const [levels, setLevels] = useState("2");
  const [stresses, setStresses] = useState("353, 373, 393");
  const [unitsAt, setUnitsAt] = useState("20, 10, 10");
  const [bLife, setBLife] = useState("10");
  const [confidence, setConfidence] = useState("90");
  const [unit, setUnit] = useState(EXAMPLE.unit);
  const [stressUnit, setStressUnit] = useState(EXAMPLE.stressUnit);
  const [from, setFrom] = useState(null);
  const [fromError, setFromError] = useState(null);
  const { result, inputs, error, loading, run } = usePlan("accelerated");

  // Start from a saved ALT model's fit.
  useEffect(() => {
    if (!modelId) return undefined;
    let live = true;
    getAltModel(modelId)
      .then((m) => {
        if (!live) return;
        const p = altPrefill(m.results);
        if (!p) {
          setFromError(`“${m.name}” can't be planned from here: plans take one stress, a Weibull or lognormal, and the Arrhenius, Eyring or inverse power law model.`);
          return;
        }
        setDistribution(p.distribution);
        setLifeModel(p.lifeModel);
        setParams(p.params);
        setShape(p.shape);
        if (p.highStress) setHighStress(p.highStress);
        setUseStress("");
        setUnit(p.unit);
        setStressUnit(p.stressUnit);
        setFrom(m.name);
      })
      .catch((e) => live && setFromError(e.message));
    return () => { live = false; };
  }, [modelId]);

  const names = PLAN_LIFE_MODELS[lifeModel].params;
  const compute = () => {
    const body = {
      mode,
      distribution,
      life_model: lifeModel,
      life_params: names.map((name) => ({ name, value: num(params[name]) })),
      shape: num(shape),
      use_stress: num(useStress),
      censor_time: num(censorTime),
      b_life: num(bLife),
      confidence: frac(confidence),
      unit: unit.trim() || null,
      stress_unit: stressUnit.trim() || null,
    };
    if (mode === "plan") Object.assign(body, { high_stress: num(highStress), units: num(units), levels: num(levels) });
    else Object.assign(body, { stresses: list(stresses), units_at: list(unitsAt) });
    run(body);
  };

  const u = result?.unit ? unitInText(result.unit) : "";
  const su = result?.stress_unit ? ` ${result.stress_unit}` : "";
  const stats = result && [
    { label: "Lowest stress", value: `${formatNumber(result.rows[0].stress)}${su}` },
    { label: "Units", value: formatNumber(result.rows.reduce((t, r) => t + r.units, 0), { sig: 7 }) },
    { label: "Expected failures", value: formatNumber(result.total_expected_failures) },
    { label: "Within a factor of", value: formatNumber(result.precision) },
  ];
  const alt = result?.alternatives?.[0];

  return (
    <div className="strategy-tool">
      <p className="tp-explain">
        An accelerated test runs units hotter (or at a higher voltage or load) so they fail sooner, then reads the
        life at normal use off the life-stress model. Testing at the highest safe stress gives failures quickly, but
        the further it is from use, the further the answer is extrapolated. The plan picks the lowest stress and
        splits the units to estimate the B-life at use as precisely as the test allows.
      </p>
      {from && <p className="hint">Starting from the fit of <b>{from}</b>: give the use stress.</p>}
      {fromError && <div className="calc-warn">{fromError}</div>}
      <div className="strategy-form">
        <div className="demo-toggles">
          <SegmentedControl
            label="Plan"
            showLabel
            value={mode}
            onChange={setMode}
            options={[
              { value: "plan", label: "Find the best test" },
              { value: "check", label: "Check a test of my own" },
            ]}
          />
        </div>
        <div className="strategy-costs">
          <Choice label="Life-stress model" value={lifeModel} onChange={setLifeModel} options={MODEL_OPTIONS} />
          {names.map((name) => (
            <Field
              key={name}
              label={`Planning value of ${name}`}
              value={params[name] ?? ""}
              onChange={(v) => setParams((prev) => ({ ...prev, [name]: v }))}
            />
          ))}
          <Choice label="Life distribution" value={distribution} onChange={setDistribution} options={PLAN_DISTRIBUTIONS} />
          <Field label={distribution === "weibull" ? "Shape β" : "σ (log-scale spread)"} value={shape} onChange={setShape} min="0" />
        </div>
        <p className="hint">{MODEL_HINT[lifeModel]} Planning values are your best guess before the test: a similar part&apos;s accelerated life fit gives them.</p>
        <div className="strategy-costs">
          <Field label="Use stress" value={useStress} onChange={setUseStress} />
          {mode === "plan" ? (
            <>
              <Field label="Highest test stress" value={highStress} onChange={setHighStress} />
              <Field label="Units" value={units} onChange={setUnits} min="2" step="1" />
              <Choice label="Stress levels" value={levels} onChange={setLevels}
                options={{ 2: "2 (most precise)", 3: "3 (compromise)", 4: "4 (compromise)" }} />
            </>
          ) : (
            <>
              <Field label="Test stresses (comma-separated)" type="text" value={stresses} onChange={setStresses} />
              <Field label="Units at each" type="text" value={unitsAt} onChange={setUnitsAt} />
            </>
          )}
          <Field label="Test length" value={censorTime} onChange={setCensorTime} min="0" />
          <Field label="Stress unit" type="text" value={stressUnit} onChange={setStressUnit} placeholder="e.g. K" />
          <Field label="Time unit" type="text" value={unit} onChange={setUnit} placeholder="e.g. hours" />
          <Field label="B-life (% failed)" value={bLife} onChange={setBLife} min="0.1" max="99" />
          <Field label="Confidence (%)" value={confidence} onChange={setConfidence} min="1" max="99.999" />
          <ComputeButton loading={loading} onClick={compute} />
        </div>
      </div>

      {error && <div className="error">{error}</div>}
      {result && (
        <>
          <PlanAnswer
            result={result}
            stats={stats}
            tone={result.warnings?.length ? "caveat" : "neutral"}
            note={result.warnings?.join(" ") || (alt && `With ${alt.levels} stress levels instead, the estimate would be within a factor of ${formatNumber(alt.precision)}${alt.levels > 2 ? ", and the middle level can show whether the model holds" : ""}.`)}
          />
          <AllocationChart result={result} />
          <div className="demo-table-wrap">
            <table className="calc-table strategy-table">
              <thead>
                <tr><th>Stress</th><th>Units</th><th>Share</th><th>Expected failures</th></tr>
              </thead>
              <tbody>
                {result.rows.map((r) => (
                  <tr key={r.stress}>
                    <td className="calc-row-label">{formatNumber(r.stress, { sig: 5 })}{su}</td>
                    <td>{r.units}</td>
                    <td>{(r.share * 100).toFixed(0)}%</td>
                    <td>{formatNumber(r.expected_failures)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <SimulationCheck kind="accelerated" inputs={inputs} />
          <Assumptions
            items={result.assumptions}
            rows={[
              { label: `Planned ${result.label} at use`, value: formatWithUnit(result.estimate, u) },
              { label: "Interval", value: `${formatWithUnit(result.interval[0], u)} to ${formatWithUnit(result.interval[1], u)}` },
            ]}
          />
        </>
      )}
    </div>
  );
}
