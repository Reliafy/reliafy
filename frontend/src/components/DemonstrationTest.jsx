import { useState } from "react";
import DemoTestResult from "./DemoTestResult.jsx";
import SaveAnalysisButton from "./SaveAnalysisButton.jsx";
import { demonstrationTest } from "../api.js";
import { unitInText } from "./unitText.js";

const num = (s) => (s === "" || s == null ? null : Number(s));
const frac = (s) => (s === "" || s == null ? null : Number(s) / 100);

// Demonstration test planner: how many units to test, for how long, with how
// many failures allowed, to show a reliability at a confidence (RePyability's
// test planning). Needs no saved model.
export default function DemonstrationTest() {
  const [method, setMethod] = useState("attribute");
  const [solveFor, setSolveFor] = useState("units");
  const [reliability, setReliability] = useState("95");
  const [confidence, setConfidence] = useState("95");
  const [missionTime, setMissionTime] = useState("1000");
  const [unit, setUnit] = useState("hours");
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

  const attribute = method === "attribute";
  const byTime = attribute && solveFor === "test_time";
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
        reliability: frac(reliability),
        mission_time: num(missionTime),
        shape: num(shape),
        design_reliability: frac(design),
      });
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
      : `Demonstration test — R ${(result.reliability * 100).toFixed(4).replace(/\.?0+$/, "")}% at ${(
          result.confidence * 100
        ).toFixed(4).replace(/\.?0+$/, "")}%`
    : "";

  return (
    <div className="strategy-tool">
      <div className="strategy-form">
        <div className="demo-toggles">
          <div className="seg" role="group" aria-label="Test type">
            <button className={"seg-btn" + (attribute ? " active" : "")} onClick={() => setMethod("attribute")}>
              Pass/fail (reliability)
            </button>
            <button className={"seg-btn" + (!attribute ? " active" : "")} onClick={() => setMethod("mtbf")}>
              MTBF (constant rate)
            </button>
          </div>
          {attribute && (
            <div className="seg" role="group" aria-label="Solve for">
              <button className={"seg-btn" + (!byTime ? " active" : "")} onClick={() => setSolveFor("units")}>
                Units to test
              </button>
              <button className={"seg-btn" + (byTime ? " active" : "")} onClick={() => setSolveFor("test_time")}>
                Test time per unit
              </button>
            </div>
          )}
        </div>

        <div className="strategy-costs">
          {attribute
            ? field("Target reliability (%)", reliability, setReliability, { min: "0.1", max: "99.999" })
            : field("MTBF to demonstrate", mtbf, setMtbf, { min: "0" })}
          {field("Confidence (%)", confidence, setConfidence, { min: "1", max: "99.999" })}
          {attribute && field("Mission time (optional)", missionTime, setMissionTime, { min: "0" })}
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
            field("Test length per unit (× mission)", multiple, setMultiple, { min: "0.01", max: "100" })}
          {(byTime || !attribute) &&
            field(attribute ? "Units available" : "Units on test (optional)", units, setUnits, { min: "1", step: "1" })}
          {attribute &&
            field(byTime || Number(multiple) !== 1 ? "Weibull shape β" : "Weibull shape β (optional)", shape, setShape, {
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
          {result && inputs && (
            <SaveAnalysisButton kind="demonstration_test" inputs={inputs} defaultName={defaultName} />
          )}
        </div>
        {attribute && (
          <p className="hint">
            {byTime
              ? "Solving for the test time per unit trades time for units, which depends on the Weibull shape β of the lifetime (assumed known)."
              : "Testing each unit for longer than one mission needs fewer units when the Weibull shape β is known (Weibayes). Leave the length at 1 for a plain success-run / binomial test."}
          </p>
        )}
        <p className="hint">
          {twoRisk
            ? "Keeping both risks: a design at the target passes at most (100 − confidence)% of the time, and the good design fails at most the producer's risk. The plan chooses the failures allowed."
            : "A test sized for the consumer’s risk alone often fails a good design. Give a good design and a producer’s risk (e.g. 20%) for a plan that keeps both."}
        </p>
      </div>

      {error && <div className="error">{error}</div>}

      {result && <DemoTestResult result={result} />}
    </div>
  );
}
