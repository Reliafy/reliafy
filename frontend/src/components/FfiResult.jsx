import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { formatNumber, formatPercent, formatWithUnit } from "../format.js";
import { unitInText } from "./unitText.js";

// Presentational renderer for a failure-finding-interval result — used by the
// live tool, saved analyses and the public link. Answer first (#311): the
// test interval in one sentence, the MTTF behind it, and the formula once,
// under Details (#313). ``actions`` (the live tool's Save) sits with the answer.
export default function FfiResult({ result, actions = null }) {
  const unit = result?.unit ? unitInText(result.unit) : "";
  const every = formatWithUnit(result.interval, unit);
  const target = formatPercent(result.target_availability, { sig: 4 });
  // The first-order formula is accurate for targets above about 90%.
  const rough = result.target_availability < 0.9;

  return (
    <>
      <ResultSummary
        tone={rough ? "caveat" : "neutral"}
        sentence={
          <>
            Test every <b>≈ {every}</b> to keep availability at <b>{target}</b>.
          </>
        }
        stats={[
          { label: "Test every", value: `≈ ${every}` },
          { label: "MTTF", value: formatWithUnit(result.mttf, unit) },
        ]}
      >
        {rough && "Below about 90% the approximation is conservative: the true interval can be longer."}
      </ResultSummary>
      {actions && <div className="rs-actions">{actions}</div>}

      <ResultDetails>
        <p className="rs-note">
          A hidden failure (a protective device) stays undetected until the function is demanded or
          checked. Testing every {every} keeps its average unavailability near{" "}
          {formatPercent(1 - result.target_availability)}. Interval = 2 × (1 − availability) × MTTF ={" "}
          2 × {formatNumber(1 - result.target_availability)} × {formatNumber(result.mttf, { sig: 4 })}, the
          standard first-order approximation.
        </p>
      </ResultDetails>
    </>
  );
}
