import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { formatNumber, formatPercent, formatTarget, formatWithUnit } from "../format.js";
import { unitInText } from "./unitText.js";
import { useCurrency } from "../WorkspaceProvider.jsx";
import { formatCost } from "../money.js";

// Presentational renderer for a failure-finding-interval result — used by the
// live tool, saved analyses and the public link. Answer first (#311): the
// test interval in one sentence with its cautious (90% one-sided) end, the
// MTTF behind it, then how it was worked out under Details (#313).
// ``actions`` (the live tool's Save) sits with the answer. Analyses saved
// before the interval came from the model's curve keep their old reading.
export default function FfiResult({ result, actions = null, stale = false }) {
  const currency = useCurrency();
  const unit = result?.unit ? unitInText(result.unit) : "";
  const every = formatWithUnit(result.interval, unit);
  // The target as typed: 99.5% never reads as 100%.
  const target = formatTarget(result.target_availability);
  const legacy = result.method !== "mean_unavailability";
  const bound = result.interval_bound;
  const cautious = bound ? formatWithUnit(bound.interval, unit) : null;
  const rough = legacy && result.target_availability < 0.9;

  return (
    <>
      <ResultSummary
        tone={stale ? "neutral" : rough || (result.warnings || []).length ? "caveat" : "neutral"}
        sentence={
          <>
            Test every <b>≈ {every}</b> to keep average availability at <b>{target}</b>.
            {cautious && <> On the cautious 90% bound of the fit, every <b>{cautious}</b>.</>}
          </>
        }
        stats={[
          { label: "Test every", value: `≈ ${every}` },
          cautious && { label: "Cautious end", value: cautious, hint: "90% one-sided" },
          { label: "MTTF", value: formatWithUnit(result.mttf, unit) },
          result.tests_cost_per_year != null && {
            label: "Tests a year", value: formatCost(result.tests_cost_per_year, currency, { sig: 3 }),
            hint: `${formatNumber(result.tests_per_year, { sig: 3 })} tests`,
          },
        ]}
      >
        {stale && "The inputs changed: Compute to update."}
        {!stale && rough && "Below about 90% the approximation is conservative: the true interval can be longer."}
      </ResultSummary>
      {actions && <div className="rs-actions">{actions}</div>}
      {!stale && (result.warnings || []).map((w) => <p key={w} className="calc-warn">{w}</p>)}

      <ResultDetails
        rows={legacy ? [] : [
          { label: "Each test", value: result.renewed_at_test ? "renews the device" : "leaves a working device as it was" },
          result.test_duration > 0 && { label: "Off-line per test", value: formatWithUnit(result.test_duration, unit) },
          { label: "Constant-rate shortcut, 2 × (1 − A) × MTTF", value: formatWithUnit(result.shortcut_interval, unit) },
        ]}
      >
        {legacy ? (
          <p className="rs-note">
            A hidden failure (a protective device) stays undetected until the function is demanded or
            checked. Testing every {every} keeps its average unavailability near{" "}
            {formatPercent(1 - result.target_availability)}. Interval = 2 × (1 − availability) × MTTF ={" "}
            2 × {formatNumber(1 - result.target_availability)} × {formatNumber(result.mttf, { sig: 4 })}, the
            standard first-order approximation (saved before the interval came from the model's curve).
          </p>
        ) : (
          <>
            <p className="rs-note">
              A hidden failure stays undetected until the device is demanded or tested. The interval is the longest
              that keeps the share of time the device sits failed and unnoticed at{" "}
              {formatTarget(1 - result.target_availability)}, worked out from the model's own curve:{" "}
              {result.renewed_at_test
                ? "with each test renewing the device, that share is 1 − (1/T) ∫ R(t) dt over the interval T."
                : "with a working device left as it was, it builds up until a test finds the failure."}
              {result.test_duration > 0 && " Time off-line for the test counts as unavailable."}
            </p>
            {bound && <p className="rs-note">{result.bound_note}</p>}
            {!bound && result.bound_note && <p className="rs-note">{result.bound_note}</p>}
          </>
        )}
      </ResultDetails>
    </>
  );
}
