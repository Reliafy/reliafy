import { useEffect, useState } from "react";
import DemoTestResult from "./DemoTestResult.jsx";
import DemoShapeSource, { fmtBeta } from "./DemoShapeSource.jsx";
import SaveAnalysisButton from "./SaveAnalysisButton.jsx";
import { demonstrationTest, getModel } from "../api.js";
import { betaSource, bLabel } from "../requirement.js";
import { formatNumber } from "../format.js";
import { unitInText } from "./unitText.js";
import SegmentedControl from "./ui/SegmentedControl.jsx";

const num = (s) => (s === "" || s == null ? null : Number(s));
const frac = (s) => (s === "" || s == null ? null : Number(s) / 100);

// Demonstration test planner: how many units to test, for how long, with how
// many failures allowed, to show a reliability (or a B-life) at a confidence
// (RePyability's test planning). Needs no saved model; ``initial`` (from
// requirement.js's parseDemoPrefill) starts it from a model's requirement
// (#295): the B-life, its life, the confidence, the model's unit and its β.
export default function DemonstrationTest({ initial = null }) {
  const [method, setMethod] = useState("attribute");
  const [solveFor, setSolveFor] = useState("units");
  const [target, setTarget] = useState(initial?.target || "reliability");
  const [bLife, setBLife] = useState(initial?.bLife || "10");
  const [reliability, setReliability] = useState("95");
  const [confidence, setConfidence] = useState(initial?.confidence || "95");
  const [missionTime, setMissionTime] = useState(initial?.missionTime || "1000");
  const [unit, setUnit] = useState(initial?.unit || "hours");
  // β from a saved model (or the fit the requirement came from), and which
  // end of it to plan with.
  const [betaSrc, setBetaSrc] = useState(initial?.beta || null);
  const [betaBound, setBetaBound] = useState("estimate");
  const [failures, setFailures] = useState("0");
  const [multiple, setMultiple] = useState("1");
  const [shape, setShape] = useState("");
  const [units, setUnits] = useState("20");
  const [mtbf, setMtbf] = useState("1000");
  const [design, setDesign] = useState("");
  const [producerRisk, setProducerRisk] = useState("");
  const [result, setResult] = useState(null);
  const [inputs, setInputs] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  // The requirement's model: its β, when it's a Weibull.
  const initialModel = initial?.modelId;
  useEffect(() => {
    if (!initialModel) return undefined;
    let live = true;
    getModel(initialModel)
      .then((full) => {
        const src = betaSource(full.results, full.name, initialModel);
        if (live && src) setBetaSrc(src);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [initialModel]);

  const attribute = method === "attribute";
  const byTime = attribute && solveFor === "test_time";
  const byB = attribute && target === "b_life";
  const betaValue = betaSrc ? (betaBound === "lower" && betaSrc.lower != null ? betaSrc.lower : betaSrc.estimate) : null;
  const onSource = (src, srcUnit) => {
    setBetaSrc(src);
    setBetaBound("estimate");
    if (src && srcUnit && !initial?.unit) setUnit(srcUnit);
  };
  // Typing a β by hand lets go of the model's.
  const setShapeByHand = (v) => {
    setBetaSrc(null);
    setShape(v);
  };
  const shapeShown = betaSrc ? fmtBeta(betaValue) : shape;
  // Both risks (#223): the plan chooses the failures allowed.
  const twoRisk = producerRisk !== "" && producerRisk != null;

  const buildBody = () => {
    const body = {
      method,
      confidence: frac(confidence),
      failures: num(failures) ?? 0,
      unit: unit.trim() || null,
    };
    if (twoRisk) body.producer_risk = frac(producerRisk);
    if (attribute) {
      Object.assign(body, {
        mission_time: num(missionTime),
        shape: betaSrc ? betaValue : num(shape),
        design_reliability: frac(design),
      });
      if (byB) body.b_life = num(bLife);
      else body.reliability = frac(reliability);
      if (betaSrc) {
        body.shape_model = betaSrc.name;
        if (betaSrc.lower != null && betaSrc.upper != null) body.shape_interval = [betaSrc.lower, betaSrc.upper];
      }
      if (byTime) body.units = num(units);
      else body.test_multiple = num(multiple) ?? 1;
    } else {
      Object.assign(body, { mtbf: num(mtbf), units: num(units), design_mtbf: num(design) });
    }
    return body;
  };

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const body = buildBody();
      const res = await demonstrationTest(body);
      setResult(res);
      setInputs(body);
    } catch (err) {
      setError(err.message);
      setResult(null);
      setInputs(null);
    } finally {
      setLoading(false);
    }
  };

  const field = (label, value, set, props = {}) => (
    <label className="calc-t">
      <span>{label}</span>
      <input type="number" step="any" value={value} onChange={(e) => set(e.target.value)} {...props} />
    </label>
  );

  const defaultName = result
    ? result.method === "mtbf"
      ? `MTBF test — ${result.mtbf} ${unitInText(result.unit)}`.trim()
      : result.b_life != null
      ? `Demonstration test — ${bLabel(result.b_life)} ≥ ${[formatNumber(result.mission_time), unitInText(result.unit)]
          .filter(Boolean).join(" ")} at ${Number((result.confidence * 100).toFixed(4))}%`
      : `Demonstration test — R ${(result.reliability * 100).toFixed(4).replace(/\.?0+$/, "")}% at ${(
          result.confidence * 100
        ).toFixed(4).replace(/\.?0+$/, "")}%`
    : "";

  return (
    <div className="strategy-tool">
      <div className="strategy-form">
        <div className="demo-toggles">
          <SegmentedControl
            label="Test type"
            showLabel
            value={attribute ? "attribute" : "mtbf"}
            onChange={setMethod}
            options={[
              { value: "attribute", label: "Pass/fail (reliability)" },
              { value: "mtbf", label: "MTBF (constant rate)" },
            ]}
          />
          {attribute && (
            <SegmentedControl
              label="Requirement"
              showLabel
              value={byB ? "b_life" : "reliability"}
              onChange={setTarget}
              options={[
                { value: "reliability", label: "Reliability over a mission" },
                { value: "b_life", label: "B-life (e.g. B10 ≥ a life)" },
              ]}
            />
          )}
          {attribute && (
            <SegmentedControl
              label="Solve for"
              showLabel
              value={byTime ? "test_time" : "units"}
              onChange={setSolveFor}
              options={[
                { value: "units", label: "Units to test" },
                { value: "test_time", label: "Test time per unit" },
              ]}
            />
          )}
        </div>

        <div className="strategy-costs">
          {byB
            ? field("B-life (% failed)", bLife, setBLife, { min: "0.001", max: "99.999" })
            : attribute
            ? field("Target reliability (%)", reliability, setReliability, { min: "0.1", max: "99.999" })
            : field("MTBF to demonstrate", mtbf, setMtbf, { min: "0" })}
          {byB && field("Life required", missionTime, setMissionTime, { min: "0" })}
          {field("Confidence (%)", confidence, setConfidence, { min: "1", max: "99.999" })}
          {attribute && !byB && field("Mission time (optional)", missionTime, setMissionTime, { min: "0" })}
          <label className="calc-t">
            <span>Unit</span>
            <input type="text" placeholder="e.g. hours" value={unit} onChange={(e) => setUnit(e.target.value)} />
          </label>
          {field("Failures allowed", twoRisk ? "" : failures, setFailures, {
            min: "0",
            max: "100",
            step: "1",
            disabled: twoRisk,
            placeholder: twoRisk ? "chosen by the plan" : undefined,
          })}
        </div>

        <div className="strategy-costs">
          {attribute && !byTime &&
            field(byB ? "Test length per unit (× the life)" : "Test length per unit (× mission)", multiple, setMultiple, { min: "0.01", max: "100" })}
          {(byTime || !attribute) &&
            field(attribute ? "Units available" : "Units on test (optional)", units, setUnits, { min: "1", step: "1" })}
          {attribute &&
            field(byTime || Number(multiple) !== 1 ? "Weibull shape β" : "Weibull shape β (optional)", shapeShown, setShapeByHand, {
              min: "0",
              placeholder: "e.g. 2",
            })}
          {attribute
            ? field(twoRisk ? "Good design's reliability (%)" : "Design's true reliability (%, optional)", design, setDesign, {
                min: "0.1",
                max: "99.999",
                placeholder: "e.g. 99",
              })
            : field(twoRisk ? "Good design's MTBF" : "Design's true MTBF (optional)", design, setDesign, {
                min: "0",
                placeholder: "e.g. 3000",
              })}
          {field("Producer's risk (%, optional)", producerRisk, setProducerRisk, {
            min: "0.1",
            max: "99.9",
            placeholder: "e.g. 20",
          })}
          <button onClick={run} disabled={loading}>
            {loading ? "Computing…" : "Compute"}
          </button>
        </div>
        {attribute && (
          <DemoShapeSource source={betaSrc} onSource={onSource} bound={betaBound} onBound={setBetaBound} />
        )}
        {attribute && (
          <p className="hint">
            {byTime
              ? "Solving for the test time per unit trades time for units, which depends on the Weibull shape β of the lifetime (assumed known)."
              : `Testing each unit for longer than ${byB ? "the life" : "one mission"} needs fewer units when the Weibull shape β is known (Weibayes). Leave the length at 1 for a plain success-run / binomial test.`}
          </p>
        )}
        <p className="hint">
          {twoRisk
            ? "With a producer’s risk, the plan chooses the failures allowed."
            : "A test sized for the consumer’s risk alone often fails a good design. Give a good design and a producer’s risk (e.g. 20%) for a plan that keeps both."}
        </p>
      </div>

      {error && <div className="error">{error}</div>}

      {result && (
        <DemoTestResult
          result={result}
          actions={inputs && (
            <SaveAnalysisButton kind="demonstration_test" inputs={inputs} defaultName={defaultName} />
          )}
        />
      )}
    </div>
  );
}
